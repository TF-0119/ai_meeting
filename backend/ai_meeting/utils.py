"""`backend.ai_meeting` 内で利用する共通ユーティリティ関数群。"""
from __future__ import annotations


def clamp(value: float, lower: float, upper: float) -> float:
    """値を下限・上限で挟み込んで返す。"""

    return max(lower, min(upper, value))


def banner(title: str) -> None:
    """シンプルな区切り線付きタイトルを出力する。"""

    print("\n" + "=" * 80)
    print(title)
    print("=" * 80 + "\n")


__all__ = ["clamp", "banner"]
