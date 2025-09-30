"""会議の KPI を算出する評価関連ロジック。"""
from __future__ import annotations

import re
from typing import Dict, List

from .config import MeetingConfig, Turn


class KPIEvaluator:
    """会議ログから KPI を算出するユーティリティ。"""

    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg

    def evaluate(self, history: List[Turn], pending, final_text: str) -> Dict:
        """会議の進捗状況を表す各種 KPI を計算する。"""

        turns = [h.content for h in history]
        n_turns = len(turns)
        if pending is not None and hasattr(pending, "items"):
            init_unres = getattr(pending, "initial", None)
            if init_unres is None:
                init_unres = len(pending.items)
                setattr(pending, "initial", init_unres)
            final_unres = len(pending.items)
        else:
            init_unres = 0
            final_unres = 0
        progress = (init_unres - final_unres) / max(1, init_unres)
        sims = []
        for i in range(n_turns - 1):
            a = self._token_set(turns[i])
            b = self._token_set(turns[i + 1])
            sims.append(self._jacc(a, b))
        diversity = 1 - (sum(sims) / len(sims) if sims else 0)
        decision_words = ["決定", "合意", "採用", "実施", "次回", "担当", "期限"]
        hits = sum(1 for t in turns if any(w in t for w in decision_words))
        decision_density = hits / n_turns if n_turns else 0
        must = ["空間", "用具", "動作", "得点", "安全", "手順", "KPI"]
        coverage = sum(1 for m in must if m in final_text) / len(must)
        return {
            "progress": round(progress, 3),
            "diversity": round(diversity, 3),
            "decision_density": round(decision_density, 3),
            "spec_coverage": round(coverage, 3),
        }

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
        return len(a & b) / len(a | b)


__all__ = ["KPIEvaluator"]
