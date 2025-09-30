"""旧 `backend.ai_meeting` モジュールの互換ラッパー。"""
from __future__ import annotations

import warnings

from backend.ai_meeting.cli import build_agents, main, parse_args
from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting

warnings.warn(
    "`backend.ai_meeting` モジュールはパッケージ化されました。"
    "今後は `backend.ai_meeting.meeting` など新構造を直接参照してください。",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AgentConfig",
    "MeetingConfig",
    "Turn",
    "Meeting",
    "parse_args",
    "build_agents",
    "main",
]
