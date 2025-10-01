"""フェーズ状態のデータ構造を定義するモジュール。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class PhaseState:
    """会議フェーズの進行状況を保持する。"""

    id: int
    start_turn: int
    turn_indices: List[int] = field(default_factory=list)
    unresolved_counts: List[int] = field(default_factory=list)
    status: str = "open"


__all__ = ["PhaseState"]
