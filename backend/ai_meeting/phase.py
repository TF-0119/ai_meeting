"""フェーズ状態のデータ構造を定義するモジュール。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PhaseState:
    """会議フェーズの進行状況を保持する。"""

    id: int
    start_turn: int
    turn_indices: List[int] = field(default_factory=list)
    unresolved_counts: List[int] = field(default_factory=list)
    status: str = "open"
    turn_limit: Optional[int] = None
    turn_count: int = 0
    kind: str = "discussion"
    legacy_round_base: int = 0

    def register_turn(self, turn_index: int, unresolved_count: int) -> None:
        """フェーズ内で1ターン進行したことを記録する。"""

        self.turn_count += 1
        self.turn_indices.append(turn_index)
        self.unresolved_counts.append(unresolved_count)

    def is_completed(self) -> bool:
        """フェーズがターン上限またはクローズ状態に達したか判定する。"""

        if self.status == "closed":
            return True
        if self.turn_limit is None:
            return False
        return self.turn_count >= self.turn_limit


__all__ = ["PhaseState"]
