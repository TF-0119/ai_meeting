"""`Meeting` クラスの本実装。"""
from __future__ import annotations

import json
import math
import os
import random
import re
import textwrap
import time
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .config import AgentConfig, MeetingConfig, Turn
from .controllers import KPIFeedback, Monitor, PendingTracker, ShockEngine
from .evaluation import KPIEvaluator
from .llm import LLMRequest, OllamaBackend, OpenAIBackend
from .logging import LiveLogWriter
from .metrics import MetricsLogger
from .testing import NullMetricsLogger, is_test_mode, setup_test_environment
from .utils import banner, clamp


class Meeting:
    """会議の進行を管理するメインクラス。"""

    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self.history: List[Turn] = []
        # backend
        self._test_mode = is_test_mode()
        if self._test_mode:
            self.backend = setup_test_environment([a.name for a in self.cfg.agents])
        elif cfg.backend_name == "openai":
            self.backend = OpenAIBackend(model=cfg.openai_model)
        else:
            model = cfg.ollama_model or os.getenv("OLLAMA_MODEL", "llama3")
            host = cfg.ollama_url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
            self.backend = OllamaBackend(model=model, host=host)
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
        self._last_spoke: Dict[str, int] = {}  # speaker_name -> last turn index (global)
        if self._test_mode:
            self.metrics = NullMetricsLogger(self.logger.dir)
        else:
            self.metrics = MetricsLogger(self.logger.dir, interval=1.0)
        self.metrics.start()

    # === 思考→審査→当選発言 用の補助 ===
    def _recent_context(self, n: int) -> str:
        if not self.history:
            return ""
        tail = self.history[-max(1, n):]
        return " / ".join(f"{t.speaker}:{t.content}" for t in tail)

    def _think(self, agent: AgentConfig, last_summary: str) -> str:
        sys = (
            "あなたは会議参加者です。これは『内面の思考』であり出力は他者に公開されません。"
            "短く（1〜2文、日本語）、次の一手として有効な案だけを書いてください。"
            "見出し・箇条書き・メタ言及は禁止。"
        )
        recent = self._recent_context(self.cfg.chat_window)
        user = f"Topic: {self.cfg.topic}\n直近: {recent}\n要約: {last_summary}\n\n次の一手（思考のみ）:"
        req = LLMRequest(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=min(0.9, self.temperature + 0.1),
            max_tokens=120,
        )
        return self._enforce_chat_constraints(self.backend.generate(req)).strip()

    def _judge_thoughts(self, bundle: Dict[str, str]) -> Dict:
        # エージェント名をキーにしたJSONだけを許可
        names = list(bundle.keys())
        recent = self._recent_context(self.cfg.chat_window)
        sys = (
            "あなたは中立の審査員です。各候補の『流れ適合/目的適合/質/新規性/実行性』を0〜1で採点し、"
            "総合scoreを算出して勝者を1名だけ選びます。出力はJSONのみ。"
        )
        # 例は“実名”で示す（A/Bなどを使わない）
        example_scores = ", ".join(
            [
                f"\"{n}\":{{\"flow\":0.0,\"goal\":0.0,\"quality\":0.0,\"novelty\":0.0,\"action\":0.0,\"score\":0.0,\"rationale\":\"短文\"}}"
                for n in names[:2]
            ]
        )
        schema = f"{{\"scores\":{{{example_scores}, ...}},\"winner\":\"{names[0]}\"}}"
        lines = [f"{name}: {txt}" for name, txt in bundle.items()]
        user = (
            f"Topic: {self.cfg.topic}\n直近: {recent}\n\n候補:\n" + "\n".join(lines) + "\n\nJSON形式で厳密に出力（キーは各候補の“名前”）：\n" + schema
        )
        req = LLMRequest(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=0.15,
            max_tokens=600,
        )
        raw = self.backend.generate(req).strip()
        j = self._try_parse_json(raw)
        # フォールバック：最低限 score だけ用意
        if not isinstance(j, dict):
            j = {}
        scores = j.get("scores")
        if not isinstance(scores, dict):
            scores = {}

        def _normalize_name(value: object) -> str:
            return str(value).strip().casefold() if value is not None else ""

        name_lookup = {_normalize_name(n): n for n in names}

        normalized_scores = {}
        for key, rec in scores.items():
            canonical = name_lookup.get(_normalize_name(key))
            if canonical and canonical not in normalized_scores:
                normalized_scores[canonical] = rec

        # 欠損を埋める＆scoreを正規化
        out_scores = {}
        for n in names:
            rec = normalized_scores.get(n, {})
            sc = float(rec.get("score", 0.0)) if isinstance(rec, dict) else 0.0
            out_scores[n] = {
                "flow": float(rec.get("flow", 0.0)) if isinstance(rec, dict) else 0.0,
                "goal": float(rec.get("goal", 0.0)) if isinstance(rec, dict) else 0.0,
                "quality": float(rec.get("quality", 0.0)) if isinstance(rec, dict) else 0.0,
                "novelty": float(rec.get("novelty", 0.0)) if isinstance(rec, dict) else 0.0,
                "action": float(rec.get("action", 0.0)) if isinstance(rec, dict) else 0.0,
                "score": max(0.0, min(1.0, sc)),
                "rationale": (rec.get("rationale") or "" if isinstance(rec, dict) else "")[:60],
            }
        win_raw = j.get("winner")
        win_norm = _normalize_name(win_raw)
        requested_winner = name_lookup.get(win_norm)
        if requested_winner:
            win = requested_winner
        elif out_scores:
            top_score = max(v["score"] for v in out_scores.values())
            top_candidates = [
                name
                for name, record in out_scores.items()
                if math.isclose(record["score"], top_score, rel_tol=1e-9, abs_tol=1e-9)
            ]
            win = random.choice(top_candidates if top_candidates else names)
        else:
            win = random.choice(names)
        result = {"scores": out_scores, "winner": win}
        if requested_winner or isinstance(win_raw, str):
            raw_text = requested_winner or str(win_raw).strip()
            result["raw_winner"] = raw_text
        return result

    def _resolve_winner(self, verdict: Dict, previous_name: Optional[str]) -> str:
        """直前の発言者を考慮しつつ最終的な勝者を決定する。"""

        agent_names = [agent.name for agent in self.cfg.agents]
        if not agent_names:
            raise ValueError("エージェントが1人も設定されていません。")

        requested = verdict.get("winner") if isinstance(verdict, dict) else None
        previous = previous_name if previous_name in agent_names else None

        if isinstance(requested, str) and requested in agent_names and requested != previous:
            return requested

        scores: Dict[str, Dict[str, float]] = verdict.get("scores") if isinstance(verdict, dict) else {}
        candidates: List[Tuple[str, float]] = []
        for name in agent_names:
            if name == previous:
                continue
            score = 0.0
            if isinstance(scores, dict):
                record = scores.get(name)
                if isinstance(record, dict):
                    raw_score = record.get("score")
                    try:
                        score = float(raw_score)
                    except (TypeError, ValueError):
                        score = 0.0
                    else:
                        if math.isnan(score):
                            score = 0.0
            candidates.append((name, score))

        if not candidates:
            if isinstance(requested, str) and requested in agent_names:
                return requested
            return previous or agent_names[0]

        top_score = max(score for _, score in candidates)
        top_candidates = [
            name
            for name, score in candidates
            if math.isclose(score, top_score, rel_tol=1e-9, abs_tol=1e-9)
        ]
        if not top_candidates:
            top_candidates = [candidates[0][0]]
        return top_candidates[0]

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

    def _speak_from_thought(self, agent: AgentConfig, thought: str) -> str:
        sys = (
            agent.system
            + "\n※以下はあなた自身の非公開メモです。要点だけを1〜2文の発言にし、"
            + "『メモ/思考/ヒント』等の語は本文に含めないこと。"
        )
        user = f"[自分の思考] {thought}\n\nこの要点を1〜2文の発言として述べてください。"
        req = LLMRequest(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=160,
        )
        return self._enforce_chat_constraints(self.backend.generate(req)).strip()

    def _agent_prompt(self, agent: AgentConfig, last_summary: str) -> LLMRequest:
        # ベースとなる役割プロンプト
        sys_prompt = agent.system
        if not self.cfg.chat_mode:
            # 既存の“発表型”ルール
            sys_prompt += textwrap.dedent(
                f"""
                \n--- 会議ルール ---
- テーマ: {self.cfg.topic}
- 名前: {agent.name}
- 出力は必ず日本語。簡潔、箇条書き主体。過度な前置きは省略。
- 先の発言・要約を踏まえ、話を前に進める。
- 最後に「次に誰が何をするべきか」を1行で明示。
                """
            )
        else:
            # 短文チャット用の厳格ルール
            sys_prompt += textwrap.dedent(
                f"""
                \n--- 会話ルール（短文チャット）---
- テーマ: {self.cfg.topic}
- 名前: {agent.name}
- 出力は必ず日本語。絵文字・見出し・箇条書き・コードブロックは禁止。
- {self.cfg.chat_max_sentences}文以内、1文{self.cfg.chat_max_chars}文字以内。冗長な前き禁止。
- 直前の発言に一言で応答し、具体的な次の一歩を短く示す。
                """
            )
        # 直近コンテキスト
        prior_msgs: List[Dict[str, str]] = []
        if self.cfg.chat_mode:
            # 直近チャット窓だけを見せる（台本化防止）
            for t in self.history[-self.cfg.chat_window :]:
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
            max_tokens=(180 if self.cfg.chat_mode else self.cfg.max_tokens),
        )

    def _summarize_round(self, new_turn: Turn) -> str:
        # 最低限のサマライザ（同じLLMを使い回す）
        req = LLMRequest(
            system="あなたは議事要約アシスタント。新しい発言を日本語で要点化し、意思決定に重要な差分だけを3〜6点で箇条書きに。",
            messages=[{"role": "user", "content": new_turn.content}],
            temperature=0.4,
            max_tokens=300,
        )
        return self.backend.generate(req)

    def _critic_pass(self, text: str) -> str:
        # 簡易ファクトチェック／自省（外部Webアクセスなし）
        req = LLMRequest(
            system="あなたは自己検証アシスタント。論点の穴、前提の曖昧さ、検証手段を列挙し、修正提案を日本語で箇条書きに。",
            messages=[{"role": "user", "content": text}],
            temperature=0.3,
            max_tokens=300,
        )
        critique = self.backend.generate(req)
        # 反映案の再生成（短く）
        req2 = LLMRequest(
            system="あなたは編集者。上記の指摘を反映して、元テキストを簡潔に改善し直す。",
            messages=[{"role": "user", "content": f"元:\n{text}\n\n指摘:\n{critique}"}],
            temperature=0.5,
            max_tokens=400,
        )
        improved = self.backend.generate(req2)
        return improved

    def _enforce_chat_constraints(self, text: str) -> str:
        """短文チャットの制約: 箇条書き/見出し除去、文数と長さを強制。"""
        if not self.cfg.chat_mode:
            return text.strip()
        s = text.replace("\r", "").strip()
        s = re.sub(r"^\s*[#>\-\*\u30fb・]+", "", s, flags=re.MULTILINE)
        parts = re.split(r"(?<=[。！？])\s+", s)
        trimmed = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(p) > self.cfg.chat_max_chars:
                p = p[: self.cfg.chat_max_chars] + "…"
            trimmed.append(p)
            if len(trimmed) >= self.cfg.chat_max_sentences:
                break
        return "\n".join(trimmed) if trimmed else s[: self.cfg.chat_max_chars]

    def _dedupe_bullets(self, text: str) -> str:
        """重複行を取り除いてスッキリさせる（先頭の・-数字. を無視して比較）"""
        seen = set()
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            norm = re.sub(r"^[\s\-\*\u30fb・\d\.\)]{0,3}", "", line)
            if norm in seen:
                continue
            seen.add(norm)
            out.append(raw)
        return "\n".join(out)

    def run(self) -> None:
        banner("AI Meeting Start")
        print(f"Topic: {self.cfg.topic}")
        print(f"Agents: {[a.name for a in self.cfg.agents]}")
        print(f"Precision: {self.cfg.precision} (Temp={self.temperature:.2f}, CritiquePasses={self.critique_passes})")
        print(f"Rounds: {self.cfg.rounds}")
        print()

        last_summary = ""
        order = self.cfg.agents[:]  # 発言順
        global_turn = 0
        for r in range(1, self.cfg.rounds + 1):
            # UI最小化時は“Round”見出しを出さない
            if not self.cfg.ui_minimal:
                banner(f"Round {r}")

            # ★ 新フロー: 思考→審査→勝者発言
            if self.cfg.think_mode:
                # 1) 全員が非公開の思考
                thoughts: Dict[str, str] = {ag.name: self._think(ag, last_summary) for ag in self.cfg.agents}
                # 2) 均衡AIが審査→勝者
                verdict = self._judge_thoughts(thoughts)
                previous_speaker = self.history[-1].speaker if self.history else None
                winner_name = self._resolve_winner(verdict, previous_speaker)
                verdict["resolved_winner"] = winner_name
                winner = next((a for a in self.cfg.agents if a.name == winner_name), self.cfg.agents[0])
                # 3) 勝者が自分の思考だけで発言
                content = self._speak_from_thought(winner, thoughts.get(winner.name, ""))
                # 4) デバッグ出力（本文には出さない）
                if self.cfg.think_debug:
                    self.logger.append_thoughts(
                        {
                            "round": r,
                            "turn": len(self.history) + 1,
                            "thoughts": thoughts,
                            "verdict": verdict,
                            "winner": winner.name,
                        }
                    )
                # 5) ログへ
                self.history.append(Turn(speaker=winner.name, content=content))
                print(
                    f"{winner.name}: {content}\n"
                    if self.cfg.ui_minimal
                    else f"{winner.name}:\n{content}\n"
                )

                self.logger.append_turn(r, len(self.history), winner.name, content)
                current_speaker = winner  # ← 後段のrevealチェック用
                self._last_spoke[current_speaker.name] = global_turn  # Update _last_spoke with current_speaker
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
                self._last_spoke[current_speaker.name] = global_turn  # Update _last_spoke with current_speaker

            global_turn += 1

            # 内省スコア → 次話者決定
            if self.equilibrium_enabled:
                # 直近文脈 + 各エージェントの system を与えて「誰が次に最も有益か」を一度で採点
                recent = self._recent_context(self.cfg.chat_window)
                roster = "\n".join([f"- {a.name}: {a.system[:120]}" for a in self.cfg.agents])
                sys_eq = (
                    "あなたはモデレーターです。直近の流れに対して、各参加者が次の1手で"
                    "どれだけ有益な発言をできるかを0〜1で採点します。出力はJSONのみ。"
                )
                schema = "{ \"scores\": { \"NAME\": 0-1, ... }, \"rationale\": \"短文\" }"
                user_eq = (
                    f"Topic: {self.cfg.topic}\n直近: {recent}\n\n直前の発言:\n{content}\n\n"
                    f"参加者と視点:\n{roster}\n\nJSON形式で厳密に出力:\n{schema}"
                )
                req2 = LLMRequest(
                    system=sys_eq,
                    messages=[{"role": "user", "content": user_eq}],
                    temperature=0.2,
                    max_tokens=600,
                )
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
                adj: Dict[str, float] = {}
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
                top = sorted(adj.items(), key=lambda kv: kv[1], reverse=True)[: max(1, self.cfg.topk)]
                winner = self._softmax_pick(top, self.cfg.select_temp)
                order.sort(key=lambda a: 0 if a.name == winner else 1)
            else:
                # 1ラウンド1発言のローテーション
                order = order[1:] + order[:1]

            last_summary = self._dedupe_bullets(self._summarize_round(self.history[-1]))
            self.logger.append_summary(r, last_summary)
            # 未解決トラッカー更新（Step2以前からの _pending を流用）
            if hasattr(self, "_pending"):
                self._pending.add_from_text(last_summary)
                self._unresolved_history.append(len(self._pending.items))
                if len(self._unresolved_history) > max(4, self.cfg.phase_window):
                    self._unresolved_history = self._unresolved_history[-self.cfg.phase_window :]

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
                            self.cfg.cooldown = clamp(self.cfg.cooldown - 0.05, 0.0, 0.35)
                        elif self._shock_engine.mode == "exploit":
                            self.cfg.select_temp = clamp(self.cfg.select_temp - 0.2, 0.5, 1.5)
                            self.cfg.sim_penalty = clamp(self.cfg.sim_penalty + 0.1, 0.0, 0.6)
                            self.cfg.cooldown = clamp(self.cfg.cooldown + 0.05, 0.0, 0.35)
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
                    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "type": "kpi_control"}
                    rec.update(fb)
                    self.logger.append_control(rec)
                    # 1) 隠しプロンプト
                    if self.cfg.kpi_auto_prompt and fb.get("hint"):
                        self._ctrl_hint = fb["hint"]
                        self._ctrl_ttl = 1  # 次ターンだけ
                    # 2) 自動チューニング
                    if self.cfg.kpi_auto_tune and "tune" in fb:
                        for key, val in fb["tune"].items():
                            if key == "shock_mode" and self._shock_engine:
                                self._shock_engine.mode = val
                            elif key == "sim_penalty":
                                self.cfg.sim_penalty = clamp(self.cfg.sim_penalty + val[1], val[2], val[3])
                            elif key == "select_temp":
                                self.cfg.select_temp = clamp(self.cfg.select_temp + val[1], val[2], val[3])
                            elif key == "cooldown":
                                self.cfg.cooldown = clamp(self.cfg.cooldown + val[1], val[2], val[3])
            except Exception:
                traceback.print_exc()

            # ヒントの寿命（ターンの最後にデクリメント）
            if self._ctrl_ttl > 0:
                self._ctrl_ttl -= 1
                if self._ctrl_ttl == 0:
                    self._ctrl_hint = None

            if not self._test_mode:
                time.sleep(0.2)

        # --- 残課題消化ラウンド（任意） ---
        if self.cfg.resolve_round and self._pending.items:
            banner("Resolution Round / 残課題の消化")
            # 残課題の要約をプロンプトに渡す
            pending_text = "- " + "\n- ".join(sorted(self._pending.items))
            for agent in order:
                # 残課題を解消する指示を追加
                extra = (
                    f"\n\n【残課題（要解消）】\n{pending_text}\n\n"
                    f"あなたの視点で、上記の残課題を具体的に解消してください。必ず日本語で、実行可能な手順・責任分担・期限を含めてください。"
                )
                req = self._agent_prompt(agent, last_summary)  # 直前の要約も参照
                req.messages.append({"role": "user", "content": extra})
                content = self.backend.generate(req)
                content = self._enforce_chat_constraints(content)
                # クリティカルな役割で軽く自省
                if self.critique_passes > 0:
                    content = self._critic_pass(content)
                self.history.append(Turn(speaker=agent.name, content=content))
                print(f"{agent.name}:\n{content}\n")
                self.logger.append_turn(self.cfg.rounds + 1, len(self.history), agent.name, content)
                last_summary = self._dedupe_bullets(self._summarize_round(self.history[-1]))
                self.logger.append_summary(self.cfg.rounds + 1, last_summary)
            # 解消したのでペンディングをクリア
            self._pending.clear()

        # 最終統合（Finisherがいない場合は内蔵フィニッシャ）
        final_req_system = (
            "あなたは議論の編集者です。これまでの発言を統合し、"
            "『合意事項』『残課題』『直近アクション』の3項目で日本語要約してください。"
        )
        final_messages = [
            {
                "role": "user",
                "content": "これまでの全発言:\n"
                + "\n\n".join([f"{t.speaker}:\n{t.content}" for t in self.history]),
            }
        ]
        final = self.backend.generate(
            LLMRequest(
                system=final_req_system,
                messages=final_messages,
                temperature=clamp(self.temperature, 0.2, 0.6),
                max_tokens=800,
            )
        )
        banner("Final Decision / 合意案")
        print(final)
        self.logger.append_final(final)

        # Step6: KPI 評価と保存（最後の Meeting クラスにも入れる）
        kpi_result: Optional[Dict] = None
        try:
            evaluator = KPIEvaluator(self.cfg)
            pending = getattr(self, "_pending", None)
            kpi_result = evaluator.evaluate(self.history, pending, final)
            self.logger.append_kpi(kpi_result)
            print("\n=== KPI ===\n" + json.dumps(kpi_result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[KPI] 評価で例外: {e}")

        print(f"\n（ライブログ: {self.logger.dir / 'meeting_live.md'} / {self.logger.dir / 'meeting_live.jsonl'}）")
        result_path = self.logger.dir / "meeting_result.json"
        print(f"\n（保存: {result_path}）")
        base_dir = self.logger.dir

        def _relative(path: Path) -> str:
            """成果物を meeting_result.json からの相対パスで表現する。"""

            try:
                return str(path.relative_to(base_dir))
            except ValueError:
                return path.name

        artifact_candidates = {
            "meeting_live_md": self.logger.md,
            "meeting_live_jsonl": self.logger.jsonl,
            "meeting_live_html": self.logger.html,
            "phases_jsonl": self.logger.phase_log,
            "thoughts_jsonl": self.logger.thoughts_log,
            "control_jsonl": base_dir / "control.jsonl",
            "kpi_json": base_dir / "kpi.json",
            "metrics_csv": base_dir / "metrics.csv",
            "metrics_cpu_mem_png": base_dir / "metrics_cpu_mem.png",
            "metrics_gpu_png": base_dir / "metrics_gpu.png",
        }
        files = {key: _relative(path) for key, path in artifact_candidates.items()}
        with result_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "topic": self.cfg.topic,
                    "precision": self.cfg.precision,
                    "rounds": self.cfg.rounds,
                    "resolve_round": self.cfg.resolve_round,
                    "agents": [a.model_dump() for a in self.cfg.agents],
                    "turns": [t.__dict__ for t in self.history],
                    "final": final,
                    "kpi": kpi_result or {},
                    "files": files,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        # メトリクス停止＆グラフ作成
        try:
            self.metrics.stop()
            print(
                f"（メトリクス: {self.logger.dir / 'metrics.csv'}, {self.logger.dir / 'metrics_cpu_mem.png'}, {self.logger.dir / 'metrics_gpu.png'}）"
            )
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

    def _softmax_pick(self, pairs: List[Tuple[str, float]], temp: float) -> str:
        # pairs: [(name, score), ...] -> name をソフトマックス抽選
        vals = [p[1] for p in pairs]
        m = max(vals)
        exps = [math.exp((v - m) / max(1e-6, temp)) for v in vals]
        s = sum(exps)
        probs = [e / s for e in exps]
        r = random.random()
        acc = 0.0
        for (name, _), p in zip(pairs, probs):
            acc += p
            if r <= acc:
                return name
        return pairs[0][0]  # フォールバック

