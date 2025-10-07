"""会議制御用の補助クラス群。"""
from __future__ import annotations

import random
import re
import typing
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import MeetingConfig, Turn


@dataclass
class PhaseEvent:
    """フェーズ検知の状態遷移を表現するイベント。"""

    phase_id: Optional[int]
    start_turn: int
    end_turn: int
    status: str
    confidence: float
    summary: str
    reason: Optional[str] = None
    cohesion: Optional[float] = None
    unresolved_drop: Optional[float] = None
    loop_streak: Optional[int] = None
    shock_used: Optional[str] = None
    kind: Optional[str] = None


class Monitor:
    """フェーズ検知を担う監視クラス。"""

    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self._last_turn_idx = 0
        self._loop_streak = 0
        self._current_event: Optional[PhaseEvent] = None
        self._candidate_hits = 0
        self._confirm_required = 2

    def observe(
        self, history: List[Turn], unresolved_hist: List[int], window: int
    ) -> Optional[PhaseEvent]:
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
            if not self._current_event:
                return None
            if self._current_event.status == "confirmed":
                self._current_event.status = "closed"
                event = self._current_event
                self._current_event = None
                self._candidate_hits = 0
                return event
            self._current_event = None
            self._candidate_hits = 0
            return None

        start_turn = len(history) - W + 1
        end_turn = len(history)
        summary = self._summarize_phase(recent)
        confidence = self._estimate_confidence(reason, cohesion, unresolved_drop)

        if not self._current_event:
            self._candidate_hits = 1
            self._current_event = PhaseEvent(
                phase_id=None,
                start_turn=start_turn,
                end_turn=end_turn,
                status="candidate",
                confidence=round(confidence, 3),
                summary=summary,
                reason=reason,
                cohesion=round(cohesion, 3),
                unresolved_drop=round(unresolved_drop, 3),
                loop_streak=self._loop_streak,
            )
            return self._current_event

        # すでに候補/確定済みのイベントが進行中
        self._current_event.start_turn = min(self._current_event.start_turn, start_turn)
        self._current_event.end_turn = end_turn
        self._current_event.summary = summary
        self._current_event.reason = reason
        self._current_event.cohesion = round(cohesion, 3)
        self._current_event.unresolved_drop = round(unresolved_drop, 3)
        self._current_event.loop_streak = self._loop_streak
        self._current_event.confidence = round(confidence, 3)

        if self._current_event.status == "candidate":
            self._candidate_hits += 1
            if self._candidate_hits >= self._confirm_required:
                self._current_event.status = "confirmed"
                return self._current_event
            return None

        # confirmed 状態のまま継続中
        return None

    def _estimate_confidence(
        self, reason: Optional[str], cohesion: float, unresolved_drop: float
    ) -> float:
        """簡易的な信頼度スコアを算出する。"""

        if reason == "loop":
            over = max(0, self._loop_streak - self.cfg.phase_loop_threshold + 1)
            base = 0.55 + 0.1 * over
        else:
            coh_span = max(1e-6, 1.0 - self.cfg.phase_cohesion_min)
            coh_score = max(0.0, (cohesion - self.cfg.phase_cohesion_min) / coh_span)
            unresolved_req = max(1e-6, self.cfg.phase_unresolved_drop)
            drop_score = max(0.0, unresolved_drop / unresolved_req)
            base = 0.45 + 0.3 * min(1.0, coh_score) + 0.25 * min(1.0, drop_score)
        return max(0.0, min(1.0, base))

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
        low_diversity = diversity < self.cfg.th_diversity_min
        low_decision = decision_density < self.cfg.th_decision_min
        if low_diversity:
            if self.cfg.kpi_auto_tune:
                tune["select_temp"] = ("inc", 0.20, 0.7, 1.5)
                tune["sim_penalty"] = ("inc", 0.10, 0.15, 0.60)
            else:
                hints.append("新しい観点を必ず1つだけ追加し、直前の発言にない要素を入れてください。")
        if low_decision:
            if self.cfg.kpi_auto_tune:
                tune["cooldown"] = ("inc", 0.05, 0.10, 0.35)
            else:
                hints.append("次の発言には担当者と期限を必ず1行で含めてください（例: 担当:A、期限:9/30）。")
        if stall:
            hints.append("抽象を避け、数値・手順・失敗時対策を各1行で具体化してください。")
            tune["shock_mode"] = "exploit"

        if low_diversity and low_decision:
            actions["trigger_shock"] = True
            actions["shock_reason"] = "diversity_decision_drop"

        if not hints and not tune:
            return actions
        actions["hint"] = " / ".join(hints)
        actions["tune"] = tune
        return actions

    def reset(self) -> None:
        """フェーズ境界で内部状態をリセットする。"""

        self._last_hint = None

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
    """会議を活性化するショック揺らぎを算出するクラス。"""

    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self.mode = cfg.shock
        self._rng = random.Random()

    def generate(self, ctx: Dict[str, typing.Any]) -> Dict[str, float]:
        """現在モードに応じた揺らぎ量を返す。

        `ctx` には KPI 指標などの情報を含め、モード別の強度調整に利用する。
        戻り値は `{"temperature": +0.15}` のような「ベースラインに足し込む差分」。
        """

        metrics = ctx.get("metrics") or {}
        mode = ctx.get("mode") or self.mode or "random"
        if mode == "explore":
            return self._mode_explore(metrics, ctx)
        if mode == "exploit":
            return self._mode_exploit(metrics, ctx)
        return self._mode_random(metrics, ctx)

    # --- 個別モード ---
    def _mode_explore(
        self, metrics: Dict[str, typing.Any], ctx: Dict[str, typing.Any]
    ) -> Dict[str, float]:
        """発散を促す揺らぎ量を計算する。"""

        diversity = self._extract_number(metrics.get("diversity"))
        severity = self._severity(
            current=diversity,
            threshold=getattr(self.cfg, "th_diversity_min", 0.55),
            default=0.25,
        )
        if metrics.get("stall"):
            severity = max(severity, 0.6)
        adjustments = {
            "temperature": round(0.30 * severity, 3),
            "select_temp": round(0.40 * severity, 3),
            "sim_penalty": round(-0.20 * severity, 3),
            "cooldown": round(-0.12 * severity, 3),
        }
        return self._remove_near_zero(adjustments)

    def _mode_exploit(
        self, metrics: Dict[str, typing.Any], ctx: Dict[str, typing.Any]
    ) -> Dict[str, float]:
        """収束を促す揺らぎ量を計算する。"""

        decision = self._extract_number(metrics.get("decision_density"))
        severity = self._severity(
            current=decision,
            threshold=getattr(self.cfg, "th_decision_min", 0.40),
            default=0.25,
        )
        if metrics.get("stall"):
            severity = max(severity, 0.5)
        adjustments = {
            "temperature": round(-0.28 * severity, 3),
            "select_temp": round(-0.35 * severity, 3),
            "sim_penalty": round(0.18 * severity, 3),
            "cooldown": round(0.15 * severity, 3),
        }
        return self._remove_near_zero(adjustments)

    def _mode_random(
        self, metrics: Dict[str, typing.Any], ctx: Dict[str, typing.Any]
    ) -> Dict[str, float]:
        """軽微なランダム揺らぎを返す。"""

        span = ctx.get("random_span", 0.15)
        def _rand(delta: float) -> float:
            return round(self._rng.uniform(-delta, delta), 3)

        adjustments = {
            "temperature": _rand(span),
            "select_temp": _rand(span),
            "sim_penalty": _rand(span * 0.6),
            "cooldown": _rand(span * 0.5),
        }
        return self._remove_near_zero(adjustments)

    # --- 補助関数 ---
    @staticmethod
    def _extract_number(value: typing.Any) -> Optional[float]:
        """数値に変換可能なら float を返す。"""

        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _remove_near_zero(adjustments: Dict[str, float]) -> Dict[str, float]:
        """丸め誤差でほぼゼロになった揺らぎを取り除く。"""

        return {k: v for k, v in adjustments.items() if abs(v) >= 0.001}

    @staticmethod
    def _severity(
        *, current: Optional[float], threshold: float, default: float
    ) -> float:
        """閾値との差分から 0.0-1.0 の強度を算出する。"""

        default = max(0.0, min(1.0, default))
        if current is None or threshold <= 0:
            return default
        gap = threshold - current
        if gap <= 0:
            return default
        ratio = gap / threshold if threshold else 1.0
        return max(default, min(1.0, ratio))


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
