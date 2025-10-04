"""`backend.ai_meeting` 内で利用する共通ユーティリティ関数群。"""
from __future__ import annotations

import sys
from typing import Final


_DEFAULT_ENCODING: Final[str] = "utf-8"


def safe_console_print(text: str) -> None:
    """コンソールのエンコーディングに合わせて安全に文字列を出力する。"""

    encoding = getattr(sys.stdout, "encoding", None) or _DEFAULT_ENCODING
    errors = "backslashreplace"
    try:
        processed = text.encode(encoding, errors=errors).decode(encoding, errors=errors)
    except LookupError:
        processed = text.encode(_DEFAULT_ENCODING, errors=errors).decode(
            _DEFAULT_ENCODING, errors=errors
        )
    print(processed)


def clamp(value: float, lower: float, upper: float) -> float:
    """値を下限・上限で挟み込んで返す。"""

    return max(lower, min(upper, value))


def banner(title: str) -> None:
    """シンプルな区切り線付きタイトルを出力する。"""

    safe_console_print("\n" + "=" * 80)
    safe_console_print(title)
    safe_console_print("=" * 80 + "\n")


__all__ = ["clamp", "banner", "safe_console_print"]
