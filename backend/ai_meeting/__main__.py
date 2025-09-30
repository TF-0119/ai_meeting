"""`python -m backend.ai_meeting` 用の暫定ラッパー。"""
from __future__ import annotations

from . import get_main


def main() -> None:
    """旧 `main()` を呼び出す。"""

    legacy_main = get_main()
    legacy_main()


if __name__ == "__main__":
    main()
