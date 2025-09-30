"""会議制御用の補助クラス群。"""
from __future__ import annotations

import random
import re
import typing
from typing import Dict, List, Optional, Tuple

from .config import MeetingConfig, Turn


class Monitor:
    """フェーズ検知を担う監視クラス。"""

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
        sets = [self._token_set(t.content) for t in recent]
        sim_sum = 0.0
        cnt = 0
        for i in range(W - 1):
            for j in range(i + 1, W):
                sim_sum += self._jacc(sets[i], sets[j])
                cnt += 1
        cohesion = (sim_sum / cnt) if cnt else 0.0
        loop_hit = 0.0
        if len(recent) >= 2:
            sA, sB = sets[-1], sets[-2]
            loop_hit = self._jacc(sA, sB)
            self._loop_streak = self._loop_streak + 1 if loop_hit >= 0.90 else 0
        unresolved_drop = 0.0
        if len(unresolved_hist) >= 2:
            first = unresolved_hist[0]
            last = unresolved_hist[-1]
            if first > 0:
                unresolved_drop = max(0.0, (first - last) / first)
        reason = None
        if self._loop_streak >= self.cfg.phase_loop_threshold:
            reason = "loop"
        elif cohesion >= self.cfg.phase_cohesion_min and unresolved_drop >= self.cfg.phase_unresolved_drop:
            reason = "cohesion_unresolved"
        if not reason:
            return None
        summary = self._summarize_phase(recent)
        return {
            "start_turn": len(history) - W + 1,
            "end_turn": len(history),
            "cohesion": round(cohesion, 3),
            "unresolved_drop": round(unresolved_drop, 3),
            "loop_streak": self._loop_streak,
            "reason": reason,
            "summary": summary,
        }

    def _summarize_phase(self, turns: List[Turn]) -> str:
        texts = [t.content for t in turns]
        head = texts[0][:60]
        tail = texts[-1][:60]
        return f"フェーズ要約: 先頭『{head}…』→末尾『{tail}…』"

    @staticmethod
    def _token_set(text: str) -> set:
        t = re.sub(r"[0-9]+", " ", text)
        t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", t, flags=re.UNICODE)
        toks = [w for w in t.lower().split() if len(w) > 1]
        return set(toks)

    @staticmethod
    def _jacc(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union


class KPIFeedback:
    """直近ウィンドウでミニ KPI を計算する制御クラス。"""

    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self._last_hint = None

    def assess(self, turns: List[Turn], unresolved_hist: List[int]) -> Dict[str, typing.Any]:
        W = max(3, int(self.cfg.kpi_window))
        window = turns[-W:] if len(turns) >= W else turns[:]
        if len(window) < 3:
            return {}
        texts = [t.content for t in window]
        sims = []
        for i in range(len(texts) - 1):
            a = self._token_set(texts[i])
            b = self._token_set(texts[i + 1])
            sims.append(self._jacc(a, b))
        diversity = 1 - (sum(sims) / len(sims) if sims else 0.0)
        decision_words = ("決定", "合意", "採用", "実施", "次回", "担当", "期限")
        hits = sum(1 for t in texts if any(w in t for w in decision_words))
        decision_density = hits / max(1, len(texts))
        stall = False
        if len(unresolved_hist) >= min(4, W):
            recent = unresolved_hist[-min(4, W):]
            non_increasing = all(recent[i] <= recent[i - 1] for i in range(1, len(recent)))
            strictly_decreased = any(recent[i] < recent[i - 1] for i in range(1, len(recent)))
            no_change = len(set(recent)) == 1
            stall = no_change or (non_increasing and not strictly_decreased)

        actions: Dict[str, typing.Any] = {
            "metrics": {
                "diversity": round(diversity, 3),
                "decision_density": round(decision_density, 3),
                "stall": bool(stall),
            }
        }
        hints: list[str] = []
        tune: Dict[str, typing.Any] = {}
        if diversity < self.cfg.th_diversity_min:
            if self.cfg.kpi_auto_tune:
                tune["select_temp"] = ("inc", 0.20, 0.7, 1.5)
                tune["sim_penalty"] = ("inc", 0.10, 0.15, 0.60)
            else:
                hints.append("新しい観点を必ず1つだけ追加し、直前の発言にない要素を入れてください。")
        if decision_density < self.cfg.th_decision_min:
            if self.cfg.kpi_auto_tune:
                tune["cooldown"] = ("inc", 0.05, 0.10, 0.35)
            else:
                hints.append("次の発言には担当者と期限を必ず1行で含めてください（例: 担当:A、期限:9/30）。")
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
        t = re.sub(r"[0-9]+", " ", text)
        t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", t)
        return {w for w in t.lower().split() if len(w) > 1}

    @staticmethod
    def _jacc(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)


class ShockEngine:
    """会議を活性化するショックヒント生成クラス。"""

    def __init__(self, cfg: MeetingConfig):
        self.mode = cfg.shock

    def generate(self, ctx: Dict) -> Tuple[str, str]:
        topic = ctx.get("topic", "")
        reason = ctx.get("reason", "")
        summ = ctx.get("summary", "")
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
    """残課題やリスクを抽出して管理するトラッカー。"""

    KEYS = ("残課題", "課題", "リスク", "改善", "是正", "対策")

    def __init__(self):
        self.items = set()

    def add_from_text(self, text: str):
        for line in text.splitlines():
            s = line.strip(" ・-*\t")
            if not s:
                continue
            if any(k in s for k in self.KEYS):
                s = re.sub(r"^[^:：]*[:：]\s*", "", s)
                self.items.add(s)

    def clear(self):
        self.items.clear()


__all__ = [
    "KPIFeedback",
    "Monitor",
    "PendingTracker",
    "ShockEngine",
]
