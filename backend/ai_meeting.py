#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import re, typing
import textwrap
from typing import Dict, List, Optional, Tuple
import math
import traceback
import random
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.evaluation import KPIEvaluator
from backend.ai_meeting.logging import LiveLogWriter
from backend.ai_meeting.metrics import MetricsLogger
from backend.ai_meeting.utils import banner, clamp

# ===== LLM Backends =====

class LLMRequest(BaseModel):
    system: str
    messages: List[Dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 800

class LLMBackend:
    def generate(self, req: LLMRequest) -> str:
        raise NotImplementedError

# --- OpenAI backend ---
class OpenAIBackend(LLMBackend):
    def __init__(self, model: Optional[str] = None):
        try:
            from openai import OpenAI
            self.client = OpenAI()
        except ImportError as e:
            raise RuntimeError("OpenAI backend requires 'openai' package. Please `pip install openai` or use `--backend ollama`.") from e
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def generate(self, req: LLMRequest) -> str:
        # OpenAI Chat Completions
        messages: list[dict[str, str]] = [{"role":"system","content":req.system}] + req.messages
        
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=typing.cast(typing.Iterable[typing.Any], messages),
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

# --- Ollama backend (local) ---
class OllamaBackend(LLMBackend):
    def __init__(self, model: str = "llama3", host: str = "http://localhost:11434"):
        import requests
        self.requests = requests
        self.model = model
        self.host = host
        if not self.host.startswith("http://localhost"):
            raise RuntimeError("Ollama host must be localhost for 100% local run.")

    def generate(self, req: LLMRequest) -> str:
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": [{"role":"system","content":req.system}] + req.messages,
            "options": {"temperature": req.temperature},
            "stream": False,
        }
        r = self.requests.post(url, json=payload, timeout=600)
        r.raise_for_status()
        data = r.json()
        return data.get("message",{}).get("content","").strip()


# ---- Step 4: Monitor（裏方AI：フェーズ検知） ----
class Monitor:
    """
    ルールベースMVP：
      - 直近W発言の“まとまり度（cohesion）”をトークンJaccardの平均で近似
      - 未解決件数が W 内で一定割合以上 減っている
      - もしくは高類似（>=0.9相当）のループが K 回連続
    満たしたらフェーズ確定。本文には何も挿入せず、phases.jsonl にだけ記録。
    """
    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self._last_turn_idx = 0
        self._loop_streak = 0

    def observe(self, history: List[Turn], unresolved_hist: List[int], window: int) -> Optional[Dict]:
        if len(history) - self._last_turn_idx < 1:
            return None
        self._last_turn_idx = len(history)
        W = min(window, len(history))
        if W < 3:
            return None
        recent = history[-W:]
        # まとまり度（Jaccard平均）
        sets = [self._token_set(t.content) for t in recent]
        sim_sum = 0.0; cnt = 0
        for i in range(W-1):
            for j in range(i+1, W):
                sim_sum += self._jacc(sets[i], sets[j]); cnt += 1
        cohesion = (sim_sum/cnt) if cnt else 0.0
        # ループ監視（直近2発言の高類似）
        loop_hit = 0.0
        if len(recent) >= 2:
            sA, sB = sets[-1], sets[-2]
            loop_hit = self._jacc(sA, sB)
            self._loop_streak = self._loop_streak + 1 if loop_hit >= 0.90 else 0
        # 未解決の減少率（正なら減っている）
        unresolved_drop = 0.0
        if len(unresolved_hist) >= 2:
            first = unresolved_hist[0]; last = unresolved_hist[-1]
            if first > 0:
                unresolved_drop = max(0.0, (first - last) / first)
        # 判定
        reason = None
        if self._loop_streak >= self.cfg.phase_loop_threshold:
            reason = "loop"
        elif cohesion >= self.cfg.phase_cohesion_min and unresolved_drop >= self.cfg.phase_unresolved_drop:
            reason = "cohesion_unresolved"
        if not reason:
            return None
        # 要約（裏方。本文に挿入しない）
        summary = self._summarize_phase(recent)
        return {
            "start_turn": len(history)-W+1,
            "end_turn": len(history),
            "cohesion": round(cohesion,3),
            "unresolved_drop": round(unresolved_drop,3),
            "loop_streak": self._loop_streak,
            "reason": reason,
            "summary": summary,
        }

    def _summarize_phase(self, turns: List[Turn]) -> str:
        # LLMを使わず簡潔な要約（先頭/末尾/頻出語を抽出）。将来はLLM要約に差し替え可。
        texts = [t.content for t in turns]
        head = texts[0][:60]; tail = texts[-1][:60]
        return f"フェーズ要約: 先頭『{head}…』→末尾『{tail}…』"

    @staticmethod
    def _token_set(text: str) -> set:
        t = re.sub(r"[0-9]+", " ", text)
        t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", t, flags=re.UNICODE)
        toks = [w for w in t.lower().split() if len(w) > 1]
        return set(toks)

    @staticmethod
    def _jacc(a:set, b:set) -> float:
        if not a or not b: return 0.0
        inter = len(a & b); union = len(a | b)
        return inter/union

class KPIFeedback:
    """直近ウィンドウでミニKPIを計算し、隠しプロンプトと調整案を返す。"""
    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self._last_hint = None

    def assess(self, turns: List[Turn], unresolved_hist: List[int]) -> Dict[str, typing.Any]:
        W = max(3, int(self.cfg.kpi_window))
        window = turns[-W:] if len(turns) >= W else turns[:]
        if len(window) < 3:
            return {}
        texts = [t.content for t in window]
        # diversity（Jaccardの連続平均を反転）
        sims = []
        for i in range(len(texts)-1):
            a = self._token_set(texts[i]); b = self._token_set(texts[i+1])
            sims.append(self._jacc(a,b))
        diversity = 1 - (sum(sims)/len(sims) if sims else 0.0)
        # decision density
        decision_words = ("決定","合意","採用","実施","次回","担当","期限")
        hits = sum(1 for t in texts if any(w in t for w in decision_words))
        decision_density = hits/max(1,len(texts))
        # progress（未解決の停滞を簡易判定）
        stall = False
        if len(unresolved_hist) >= min(4, W):
            recent = unresolved_hist[-min(4, W):]
            non_increasing = all(recent[i] <= recent[i-1] for i in range(1, len(recent)))
            no_change = len(set(recent)) == 1
            stall = no_change or (non_increasing and not any(recent[i] < recent[i-1] for i in range(1, len(recent)))) is False and \
                (len(set(recent)) == 1)

        actions: Dict[str, typing.Any] = {
            "metrics": {
                "diversity": round(diversity, 3),
                "decision_density": round(decision_density, 3),
                "stall": bool(stall)}}
        hints = []
        tune = {}
        # 規則1：多様性不足 → 新観点 + 反復抑制
        if diversity < self.cfg.th_diversity_min:
            if self.cfg.kpi_auto_tune:
                tune["select_temp"] = ("inc", 0.20, 0.7, 1.5)     # よりランダムに
                tune["sim_penalty"] = ("inc", 0.10, 0.15, 0.60)   # 現在値に+0.10、最小+上限
            else:
                hints.append("新しい観点を必ず1つだけ追加し、直前の発言にない要素を入れてください。")
        # 規則2：決定密度不足 → 担当+期限の強制
        if decision_density < self.cfg.th_decision_min:
            if self.cfg.kpi_auto_tune:
                tune["cooldown"] = ("inc", 0.05, 0.10, 0.35)      # 連投抑制
            else:
                hints.append("次の発言には担当者と期限を必ず1行で含めてください（例: 担当:A、期限:9/30）。")
        # 規則3：進捗停滞 → 収束ショック
        if stall:
            hints.append("抽象を避け、数値・手順・失敗時対策を各1行で具体化してください。")
            tune["shock_mode"] = "exploit"

        if not hints and not tune:
            return actions
        actions["hint"] = " / ".join(hints)
        actions["tune"] = tune
        return actions

    @staticmethod
    def _token_set(text: str) -> set:
        t = re.sub(r"[0-9]+"," ", text); t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+"," ", t)
        return set(w for w in t.lower().split() if len(w)>1)
    @staticmethod
    def _jacc(a:set,b:set)->float:
        if not a or not b: return 0.0
        return len(a&b)/len(a|b)
# ---- Step 5: ShockEngine（裏方AI：奇想天外な刺激を注入）----
class ShockEngine:
    """
    mode:
      - random  : 無方向のアイデア飛び石
      - explore : 発散寄り（新規性を強調）
      - exploit : 収束寄り（具体化・制約強化）
    出力は“非公開ヒント”。本文には出さず、次の数ターンにだけ影響。
    """
    def __init__(self, cfg: MeetingConfig):
        self.mode = cfg.shock

    def generate(self, ctx: Dict) -> Tuple[str, str]:
        topic = ctx.get("topic","")
        reason = ctx.get("reason","")
        summ = ctx.get("summary","")
        if self.mode == "explore":
            hint = self._hint_explore(topic, reason, summ)
            note = "explore"
        elif self.mode == "exploit":
            hint = self._hint_exploit(topic, reason, summ)
            note = "exploit"
        else:
            hint = self._hint_random(topic, reason, summ)
            note = "random"
        return hint, note

    def _hint_random(self, topic, reason, summ) -> str:
        seeds = [
            "制約を1つ極端に強めてみて（時間=120秒、道具=1点、人数=2名など）。",
            "逆転発想：目的を真逆にすると何が生まれる？",
            "異分野の比喩を1つだけ移植して（料理/ダンス/将棋/交通のいずれか）。",
            "禁止語を1つ決めて、それを回避するルールを作って。",
        ]
        return random.choice(seeds)

    def _hint_explore(self, topic, reason, summ) -> str:
        return "現状の発想の前提を1つ外して、全く別系統の案を1つだけ提示して。実験可能性は低くても良い。"

    def _hint_exploit(self, topic, reason, summ) -> str:
        return "直前の合意要素を3つ選び、数値・手順・失敗時対策を各1行で具体化して。抽象語は禁止。"

class PendingTracker:
    """要約から“残課題・リスク・改善案”を抽出して蓄積し、重複を除去して持つ。"""
    KEYS = ("残課題", "課題", "リスク", "改善", "是正", "対策")
    def __init__(self):
        self.items = set()
    def add_from_text(self, text: str):
        for line in text.splitlines():
            s = line.strip(" ・-*\t")
            if not s:
                continue
            if any(k in s for k in self.KEYS):
                # “: ”以降や「- 」以降を抽出して短文化
                s = re.sub(r'^[^:：]*[:：]\s*', '', s)
                self.items.add(s)
    def clear(self):
        self.items.clear()

class Meeting:
    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self.history: List[Turn] = []
        # backend
        if cfg.backend_name == "openai":
            self.backend = OpenAIBackend(model=cfg.openai_model)
        else:
            model = cfg.ollama_model or os.getenv("OLLAMA_MODEL","llama3")
            self.backend = OllamaBackend(model=model)
        rp = self.cfg.runtime_params()
        self.temperature = rp["temperature"]
        self.critique_passes = rp["critique_passes"]
        self._pending = PendingTracker()  # 残課題トラッカー
        self.logger = LiveLogWriter(self.cfg.topic, outdir=self.cfg.outdir, ui_minimal=self.cfg.ui_minimal)
        self.equilibrium_enabled = self.cfg.equilibrium
        self._monitor = Monitor(self.cfg) if self.cfg.monitor else None
        self._phase_id = 0
        self._unresolved_history: List[int] = []
        # Step5: ショック管理を有効化
        self._shock_engine = ShockEngine(self.cfg) if self.cfg.shock != "off" else None
        self._shock_hint: Optional[str] = None
        self._shock_ttl: int = 0
        # Step7: KPIフィードバック
        self._ctrl = KPIFeedback(self.cfg)
        self._ctrl_hint: Optional[str] = None
        self._ctrl_ttl: int = 0


        # メトリクスロガー開始
        self._last_spoke: Dict[str,int] = {}  # speaker_name -> last turn index (global)
        self.metrics = MetricsLogger(self.logger.dir, interval=1.0)
        self.metrics.start()

    # === 思考→審査→当選発言 用の補助 ===
    def _recent_context(self, n:int) -> str:
        if not self.history: return ""
        tail = self.history[-max(1,n):]
        return " / ".join(f"{t.speaker}:{t.content}" for t in tail)

    def _think(self, agent: "AgentConfig", last_summary: str) -> str:
        sys = ("あなたは会議参加者です。これは『内面の思考』であり出力は他者に公開されません。"
               "短く（1〜2文、日本語）、次の一手として有効な案だけを書いてください。"
               "見出し・箇条書き・メタ言及は禁止。")
        recent = self._recent_context(self.cfg.chat_window)
        user = f"Topic: {self.cfg.topic}\n直近: {recent}\n要約: {last_summary}\n\n次の一手（思考のみ）:"
        req = LLMRequest(system=sys, messages=[{"role":"user","content":user}],
                         temperature=min(0.9, self.temperature+0.1), max_tokens=120)
        return self._enforce_chat_constraints(self.backend.generate(req)).strip()

    def _judge_thoughts(self, bundle: Dict[str, str]) -> Dict:
        # エージェント名をキーにしたJSONだけを許可
        names = list(bundle.keys())
        recent = self._recent_context(self.cfg.chat_window)
        sys = ("あなたは中立の審査員です。各候補の『流れ適合/目的適合/質/新規性/実行性』を0〜1で採点し、"
               "総合scoreを算出して勝者を1名だけ選びます。出力はJSONのみ。")
        # 例は“実名”で示す（A/Bなどを使わない）
        example_scores = ", ".join(
            [f"\"{n}\":{{\"flow\":0.0,\"goal\":0.0,\"quality\":0.0,\"novelty\":0.0,\"action\":0.0,\"score\":0.0,\"rationale\":\"短文\"}}" for n in names[:2]]
        )
        schema = f"{{\"scores\":{{{example_scores}, ...}},\"winner\":\"{names[0]}\"}}"
        lines = [f"{name}: {txt}" for name, txt in bundle.items()]
        user = (
            f"Topic: {self.cfg.topic}\n直近: {recent}\n\n候補:\n" + "\n".join(lines) +
            "\n\nJSON形式で厳密に出力（キーは各候補の“名前”）：\n" + schema
        )
        req = LLMRequest(system=sys, messages=[{"role": "user", "content": user}], temperature=0.15, max_tokens=600)
        raw = self.backend.generate(req).strip()
        j = self._try_parse_json(raw)
        # フォールバック：最低限 score だけ用意
        if not isinstance(j, dict):
            j = {}
        scores = j.get("scores")
        if not isinstance(scores, dict):
            scores = {}
        # 欠損を埋める＆scoreを正規化
        out_scores = {}
        for n in names:
            rec = scores.get(n, {})
            sc = float(rec.get("score", 0.0)) if isinstance(rec, dict) else 0.0
            out_scores[n] = {
                "flow": float(rec.get("flow", 0.0)) if isinstance(rec, dict) else 0.0,
                "goal": float(rec.get("goal", 0.0)) if isinstance(rec, dict) else 0.0,
                "quality": float(rec.get("quality", 0.0)) if isinstance(rec, dict) else 0.0,
                "novelty": float(rec.get("novelty", 0.0)) if isinstance(rec, dict) else 0.0,
                "action": float(rec.get("action", 0.0)) if isinstance(rec, dict) else 0.0,
                "score": max(0.0, min(1.0, sc)),
                "rationale": (rec.get("rationale") or "" if isinstance(rec, dict) else "")[:60]
            }
        win = j.get("winner")
        if win not in names:
            win = max(out_scores.items(), key=lambda kv: kv[1]["score"])[0] if out_scores else names[0]
        return {"scores": out_scores, "winner": win}

    def _try_parse_json(self, raw: str):
        # ```json ... ``` または テキスト中の最外郭JSON を頑丈に抽出
        try:
            m = re.findall(r"\{[\s\S]*\}", raw)
            for s in reversed(m):  # 最後のブロックがJSONであることが多い
                try:
                    return json.loads(s)
                except Exception:
                    continue
            return json.loads(raw)  # そのままJSONの可能性
        except Exception:
            return None

    def _speak_from_thought(self, agent: "AgentConfig", thought: str) -> str:
        sys = (agent.system +
               "\n※以下はあなた自身の非公開メモです。要点だけを1〜2文の発言にし、"
               "『メモ/思考/ヒント』等の語は本文に含めないこと。")
        user = f"[自分の思考] {thought}\n\nこの要点を1〜2文の発言として述べてください。"
        req = LLMRequest(system=sys, messages=[{"role":"user","content":user}],
                         temperature=self.temperature, max_tokens=160)
        return self._enforce_chat_constraints(self.backend.generate(req)).strip()

    def _agent_prompt(self, agent: AgentConfig, last_summary: str) -> LLMRequest:
        # ベースとなる役割プロンプト
        sys_prompt = agent.system
        if not self.cfg.chat_mode:
            # 既存の“発表型”ルール
            sys_prompt += textwrap.dedent(f"""
            \n--- 会議ルール ---
- テーマ: {self.cfg.topic}
- 名前: {agent.name}
- 出力は必ず日本語。簡潔、箇条書き主体。過度な前置きは省略。
- 先の発言・要約を踏まえ、話を前に進める。
- 最後に「次に誰が何をするべきか」を1行で明示。
            """)
        else:
            # 短文チャット用の厳格ルール
            sys_prompt += textwrap.dedent(f"""
            \n--- 会話ルール（短文チャット）---
- テーマ: {self.cfg.topic}
- 名前: {agent.name}
- 出力は必ず日本語。絵文字・見出し・箇条書き・コードブロックは禁止。
- {self.cfg.chat_max_sentences}文以内、1文{self.cfg.chat_max_chars}文字以内。冗長な前置き禁止。
- 直前の発言に一言で応答し、具体的な次の一歩を短く示す。
            """)
        # 直近コンテキスト
        prior_msgs: List[Dict[str, str]] = []
        if self.cfg.chat_mode:
            # 直近チャット窓だけを見せる（台本化防止）
            for t in self.history[-self.cfg.chat_window:]:
                prior_msgs.append({"role": "user", "content": f"{t.speaker}: {t.content}"})
        else:
            if last_summary:
                prior_msgs.append({"role": "user", "content": f"前ラウンド要約:\n{last_summary}"})
        prior_msgs.append({"role": "user", "content": f"テーマ再掲: {self.cfg.topic}"})
        if agent.style:
            prior_msgs.append({"role": "user", "content": f"話し方のトーン: {agent.style}"})
        # Step5/7: 非公開ヒント（ショック/コントローラ）。本文に「ヒント」等は書かない。
        # 何も入れない（パラメータ側で制御）
        return LLMRequest(
            system=sys_prompt,
            messages=prior_msgs,
            temperature=self.temperature,
            max_tokens=(180 if self.cfg.chat_mode else self.cfg.max_tokens)
        )

    def _summarize_round(self, new_turn: Turn) -> str:
        # 最低限のサマライザ（同じLLMを使い回す）
        req = LLMRequest(
            system="あなたは議事要約アシスタント。新しい発言を日本語で要点化し、意思決定に重要な差分だけを3〜6点で箇条書きに。",
            messages=[{"role":"user","content":new_turn.content}],
            temperature=0.4,
            max_tokens=300
        )
        return self.backend.generate(req)

    def _critic_pass(self, text: str) -> str:
        # 簡易ファクトチェック／自省（外部Webアクセスなし）
        req = LLMRequest(
            system="あなたは自己検証アシスタント。論点の穴、前提の曖昧さ、検証手段を列挙し、修正提案を日本語で箇条書きに。",
            messages=[{"role":"user","content":text}],
            temperature=0.3,
            max_tokens=300
        )
        critique = self.backend.generate(req)
        # 反映案の再生成（短く）
        req2 = LLMRequest(
            system="あなたは編集者。上記の指摘を反映して、元テキストを簡潔に改善し直す。",
            messages=[{"role":"user","content":f"元:\n{text}\n\n指摘:\n{critique}"}],
            temperature=0.5,
            max_tokens=400
        )
        improved = self.backend.generate(req2)
        return improved

    def _enforce_chat_constraints(self, text: str) -> str:
        """短文チャットの制約: 箇条書き/見出し除去、文数と長さを強制。"""
        if not self.cfg.chat_mode:
            return text.strip()
        s = text.replace("\r", "").strip()
        s = re.sub(r'^\s*[#>\-\*\u30fb・]+', '', s, flags=re.MULTILINE)
        parts = re.split(r'(?<=[。！？])\s+', s)
        trimmed = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(p) > self.cfg.chat_max_chars:
                p = p[:self.cfg.chat_max_chars] + "…"
            trimmed.append(p)
            if len(trimmed) >= self.cfg.chat_max_sentences:
                break
        return "\n".join(trimmed) if trimmed else s[:self.cfg.chat_max_chars]

    def _dedupe_bullets(self, text: str) -> str:
        """重複行を取り除いてスッキリさせる（先頭の・-数字. を無視して比較）"""
        seen = set()
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            norm = re.sub(r'^[\s\-\*\u30fb・\d\.\)]{0,3}', '', line)
            if norm in seen:
                continue
            seen.add(norm)
            out.append(raw)
        return "\n".join(out)

    def run(self):
        banner("AI Meeting Start")
        print(f"Topic: {self.cfg.topic}")
        print(f"Agents: {[a.name for a in self.cfg.agents]}")
        print(f"Precision: {self.cfg.precision} (Temp={self.temperature:.2f}, CritiquePasses={self.critique_passes})")
        print(f"Rounds: {self.cfg.rounds}")
        print()

        last_summary = ""
        order = self.cfg.agents[:]  # 発言順
        global_turn = 0
        for r in range(1, self.cfg.rounds+1):
            # UI最小化時は“Round”見出しを出さない
            if not self.cfg.ui_minimal:
                banner(f"Round {r}")

            # ★ 新フロー: 思考→審査→勝者発言
            if self.cfg.think_mode:
                # 1) 全員が非公開の思考
                thoughts: Dict[str,str] = {ag.name: self._think(ag, last_summary) for ag in self.cfg.agents}
                # 2) 均衡AIが審査→勝者
                verdict = self._judge_thoughts(thoughts)
                winner_name = verdict.get("winner") or max(
                    [(k, v.get("score",0.0)) for k,v in verdict.get("scores",{}).items()],
                    key=lambda kv: kv[1])[0]
                winner = next((a for a in self.cfg.agents if a.name == winner_name), self.cfg.agents[0])
                # 3) 勝者が自分の思考だけで発言
                content = self._speak_from_thought(winner, thoughts.get(winner.name, ""))
                # 4) デバッグ出力（本文には出さない）
                if self.cfg.think_debug:
                    self.logger.append_thoughts({"round": r, "turn": len(self.history)+1,
                                                 "thoughts": thoughts, "verdict": verdict, "winner": winner.name})
                # 5) ログへ
                self.history.append(Turn(speaker=winner.name, content=content))
                print(f"{winner.name}: {content}\n" if self.cfg.ui_minimal else f"{winner.name}:\n{content}\n")

                self.logger.append_turn(r, len(self.history), winner.name, content)
                current_speaker = winner  # ← 後段のrevealチェック用
                self._last_spoke[current_speaker.name] = global_turn # Update _last_spoke with current_speaker
            else:
                # 旧フロー
                # 発言権を持つのは order[0]
                speaker = order[0]
                req = self._agent_prompt(speaker, last_summary)
                content = self.backend.generate(req)
                content = self._enforce_chat_constraints(content)
                if self.critique_passes > 0:
                    tmp = content
                    for _ in range(int(self.critique_passes)):
                        tmp = self._critic_pass(tmp)
                    content = tmp
                self.history.append(Turn(speaker=speaker.name, content=content))
                print(f"{speaker.name}: {content}\n")
                self.logger.append_turn(r, len(self.history), speaker.name, content)
                current_speaker = speaker
                self._last_spoke[current_speaker.name] = global_turn # Update _last_spoke with current_speaker

            global_turn += 1

            # 内省スコア → 次話者決定
            if self.equilibrium_enabled:
                # 直近文脈 + 各エージェントの system を与えて「誰が次に最も有益か」を一度で採点
                recent = self._recent_context(self.cfg.chat_window)
                roster = "\n".join([f"- {a.name}: {a.system[:120]}" for a in self.cfg.agents])
                sys_eq = ("あなたはモデレーターです。直近の流れに対して、各参加者が次の1手で"
                          "どれだけ有益な発言をできるかを0〜1で採点します。出力はJSONのみ。")
                schema = "{ \"scores\": { \"NAME\": 0-1, ... }, \"rationale\": \"短文\" }"
                user_eq = (f"Topic: {self.cfg.topic}\n直近: {recent}\n\n直前の発言:\n{content}\n\n"
                           f"参加者と視点:\n{roster}\n\nJSON形式で厳密に出力:\n{schema}")
                req2 = LLMRequest(system=sys_eq, messages=[{"role":"user","content":user_eq}], temperature=0.2, max_tokens=600)
                raw2 = self.backend.generate(req2).strip()
                j2 = self._try_parse_json(raw2) if hasattr(self, "_try_parse_json") else None
                base_scores: Dict[str, float] = {}
                if isinstance(j2, dict) and isinstance(j2.get("scores"), dict):
                    for a in self.cfg.agents:
                        v = j2["scores"].get(a.name)
                        try:
                            base_scores[a.name] = float(v)
                        except Exception:
                            base_scores[a.name] = 0.0
                else:
                    # フォールバック：全員フラット
                    base_scores = {a.name: 0.5 for a in self.cfg.agents}
                # --- Step3: スコアの調整（クールダウン＆重複ペナルティ） ---
                adj: Dict[str,float] = {}
                sim_recent_text = self._concat_recent_text(self.cfg.sim_window)
                sim_tokens_recent = self._token_set(sim_recent_text) if sim_recent_text else set()
                for ag in self.cfg.agents:
                    s = base_scores.get(ag.name, 0.0)
                    # クールダウン（直近発言者, または span 以内）
                    if ag.name in self._last_spoke:
                        ago = global_turn - self._last_spoke[ag.name]
                        if 0 <= ago <= self.cfg.cooldown_span:
                            s -= self.cfg.cooldown
                    # 重複ペナルティ（提案が直近と似すぎなら下げる）
                    if sim_tokens_recent:
                        sim = self._similarity_tokens(self._token_set(content), sim_tokens_recent)
                        s -= self.cfg.sim_penalty * sim
                    adj[ag.name] = s
                # 上位Kからソフトマックス抽選
                top = sorted(adj.items(), key=lambda kv: kv[1], reverse=True)[:max(1,self.cfg.topk)]
                winner = self._softmax_pick(top, self.cfg.select_temp)
                order.sort(key=lambda a: 0 if a.name==winner else 1)
            else:
                # 1ラウンド1発言のローテーション
                order = order[1:]+order[:1]

            last_summary = self._dedupe_bullets(self._summarize_round(self.history[-1]))
            self.logger.append_summary(r, last_summary)
            # 未解決トラッカー更新（Step2以前からの _pending を流用）
            if hasattr(self, "_pending"):
                self._pending.add_from_text(last_summary)
                self._unresolved_history.append(len(self._pending.items))
                if len(self._unresolved_history) > max(4, self.cfg.phase_window):
                    self._unresolved_history = self._unresolved_history[-self.cfg.phase_window:]

            # Step 4: 監視AIが裏でフェーズ判定（ログのみ）
            if self._monitor:
                ev = self._monitor.observe(self.history, self._unresolved_history, self.cfg.phase_window)
                if ev:  # フェーズ確定
                    self._phase_id += 1
                    ev["phase_id"] = self._phase_id
                    # Step5: ショック生成（裏方）
                    if self._shock_engine:
                        # modeに応じてパラメータを滑らかに変更（本文には一切出さない）
                        if self._shock_engine.mode == "explore":
                            self.cfg.select_temp = clamp(self.cfg.select_temp + 0.2, 0.7, 1.5)
                            self.cfg.sim_penalty = clamp(self.cfg.sim_penalty - 0.1, 0.0, 0.6)
                            self.cfg.cooldown    = clamp(self.cfg.cooldown - 0.05, 0.0, 0.35)
                        elif self._shock_engine.mode == "exploit":
                            self.cfg.select_temp = clamp(self.cfg.select_temp - 0.2, 0.5, 1.5)
                            self.cfg.sim_penalty = clamp(self.cfg.sim_penalty + 0.1, 0.0, 0.6)
                            self.cfg.cooldown    = clamp(self.cfg.cooldown + 0.05, 0.0, 0.35)
                        ev["shock_used"] = self._shock_engine.mode
                    self.logger.append_phase(ev)
                    # フェーズが変わっても “会議本文には何も挿入しない”（参加AIは気づかない）
            
            # 発言者がどちらの経路でも安全に参照できるよう current_speaker を使う
            if getattr(current_speaker, "reveal_think", False):
                print(textwrap.indent(f"(思考ログ/自己検証)\n{last_summary}", prefix="    "))  # 簡易版
            # ショックの寿命（ターン末にデクリメント）
            if getattr(self, "_shock_ttl", 0) > 0:
                self._shock_ttl -= 1
                if self._shock_ttl == 0:
                    self._shock_hint = None
            # Step7: KPIフィードバック（直近ウィンドウ）
            try:
                fb = self._ctrl.assess(self.history, self._unresolved_history)
                if fb and (self.cfg.kpi_auto_prompt or self.cfg.kpi_auto_tune):
                    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "type":"kpi_control"}
                    rec.update(fb)
                    self.logger.append_control(rec)
                    # 1) 隠しプロンプト
                    if self.cfg.kpi_auto_prompt and fb.get("hint"):
                        self._ctrl_hint = fb["hint"]
                        self._ctrl_ttl = 1  # 次ターンだけ
                    # 2) 自動チューニング
                    if self.cfg.kpi_auto_tune and "tune" in fb:
                        for key,val in fb["tune"].items():
                            if key=="shock_mode" and self._shock_engine:
                                self._shock_engine.mode = val
                            elif key=="sim_penalty":
                                self.cfg.sim_penalty = clamp(self.cfg.sim_penalty + val[1], val[2], val[3])
                            elif key=="select_temp":
                                self.cfg.select_temp = clamp(self.cfg.select_temp + val[1], val[2], val[3])
                            elif key=="cooldown":
                                self.cfg.cooldown = clamp(self.cfg.cooldown + val[1], val[2], val[3])
            except Exception:
                traceback.print_exc()

            # ヒントの寿命（ターンの最後にデクリメント）
            if self._ctrl_ttl > 0:
                self._ctrl_ttl -= 1
                if self._ctrl_ttl == 0:
                    self._ctrl_hint = None

            time.sleep(0.2)

        # --- 残課題消化ラウンド（任意） ---
        if self.cfg.resolve_round and self._pending.items:
            banner("Resolution Round / 残課題の消化")
            # 残課題の要約をプロンプトに渡す
            pending_text = "- " + "\n- ".join(sorted(self._pending.items))
            for agent in order:
                # 残課題を解消する指示を追加
                extra = f"\n\n【残課題（要解消）】\n{pending_text}\n\n" \
                        f"あなたの視点で、上記の残課題を具体的に解消してください。必ず日本語で、実行可能な手順・責任分担・期限を含めてください。"
                req = self._agent_prompt(agent, last_summary)  # 直前の要約も参照
                req.messages.append({"role": "user", "content": extra})
                content = self.backend.generate(req)
                content = self._enforce_chat_constraints(content)
                # クリティカルな役割で軽く自省
                if self.critique_passes > 0:
                    content = self._critic_pass(content)
                self.history.append(Turn(speaker=agent.name, content=content))
                print(f"{agent.name}:\n{content}\n")
                self.logger.append_turn(self.cfg.rounds+1, len(self.history), agent.name, content)
                last_summary = self._dedupe_bullets(self._summarize_round(self.history[-1]))
                self.logger.append_summary(self.cfg.rounds+1, last_summary)
            # 解消したのでペンディングをクリア
            self._pending.clear()

        # 最終統合（Finisherがいない場合は内蔵フィニッシャ）
        final_req_system = (
            "あなたは議論の編集者です。これまでの発言を統合し、"
            "『合意事項』『残課題』『直近アクション』の3項目で日本語要約してください。"
        )
        final_messages = [{"role":"user","content":"これまでの全発言:\n" + "\n\n".join(
            [f"{t.speaker}:\n{t.content}" for t in self.history]
        )}]
        final = self.backend.generate(LLMRequest(system=final_req_system, messages=final_messages,
                                                 temperature=clamp(self.temperature,0.2,0.6), max_tokens=800))
        banner("Final Decision / 合意案")
        print(final)
        self.logger.append_final(final)

        # Step6: KPI 評価と保存（最後の Meeting クラスにも入れる）
        try:
            evaluator = KPIEvaluator(self.cfg)
            pending = getattr(self, "_pending", None)
            kpi = evaluator.evaluate(self.history, pending, final)
            self.logger.append_kpi(kpi)
            print("\n=== KPI ===\n" + json.dumps(kpi, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[KPI] 評価で例外: {e}")

        print(f"\n（ライブログ: {self.logger.dir / 'meeting_live.md'} / {self.logger.dir / 'meeting_live.jsonl'}）")
        result_path = self.logger.dir / "meeting_result.json"
        print(f"\n（保存: {result_path}）")
        with result_path.open("w",encoding="utf-8") as f:
            json.dump({
                "topic": self.cfg.topic,
                "precision": self.cfg.precision,
                "rounds": self.cfg.rounds,
                "resolve_round": self.cfg.resolve_round,
                "agents": [a.model_dump() for a in self.cfg.agents],
                "turns": [t.__dict__ for t in self.history],
                "final": final,
            }, f, ensure_ascii=False, indent=2)
        # メトリクス停止＆グラフ作成
        try:
            self.metrics.stop()
            print(f"（メトリクス: {self.logger.dir / 'metrics.csv'}, {self.logger.dir / 'metrics_cpu_mem.png'}, {self.logger.dir / 'metrics_gpu.png'}）")
        except Exception:
            traceback.print_exc()

    # ---- Step3 helpers ----
    def _concat_recent_text(self, window: int) -> str:
        if window <= 0 or not self.history:
            return ""
        lines = [t.content for t in self.history[-window:]]
        return "\n".join(lines)

    def _token_set(self, text: str) -> set:
        # 記号・数字を落として簡易トークン集合に（日本語/英語混在でもそこそこ効く）
        t = re.sub(r"[0-9]+", " ", text)
        t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", t, flags=re.UNICODE)
        toks = [w for w in t.lower().split() if len(w) > 1]
        return set(toks)

    def _similarity_tokens(self, a: set, b: set) -> float:
        # Jaccard 類似（0〜1）
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union

    def _softmax_pick(self, pairs: List[Tuple[str,float]], temp: float) -> str:
        # pairs: [(name, score), ...] -> name をソフトマックス抽選
        vals = [p[1] for p in pairs]
        m = max(vals)
        exps = [math.exp((v - m)/max(1e-6, temp)) for v in vals]
        s = sum(exps)
        probs = [e/s for e in exps]
        r = random.random()
        acc = 0.0
        for (name,_), p in zip(pairs, probs):
            acc += p
            if r <= acc:
                return name
        return pairs[0][0]  # フォールバック

# ===== CLI (互換目的のエイリアス) =====

from backend.ai_meeting.cli import build_agents, main, parse_args


if __name__ == "__main__":
    main()
