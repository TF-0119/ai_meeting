"""`backend.ai_meeting` パッケージの暫定エントリーポイント。"""
from __future__ import annotations

from ._legacy import get_main, load_legacy_module
from .cli import main
from .config import MeetingConfig
from .meeting import Meeting

__all__ = [
    "load_legacy_module",
    "get_main",
    "MeetingConfig",
    "main",
    "Meeting",
]
