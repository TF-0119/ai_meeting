"""CLI オプションでエージェントメモリ設定を制御できることを確認するテスト。"""

from backend.ai_meeting import cli
from backend.ai_meeting.config import MeetingConfig


def test_agent_memory_defaults_match_meeting_config_defaults() -> None:
    """未指定時には MeetingConfig の既定値がそのまま利用される。"""

    args = cli.parse_args(["--topic", "テスト"])
    cfg = cli.build_meeting_config(args)

    assert cfg.agent_memory_limit == MeetingConfig.model_fields["agent_memory_limit"].default
    assert cfg.agent_memory_window == MeetingConfig.model_fields["agent_memory_window"].default


def test_agent_memory_options_override_values() -> None:
    """CLI オプションで値を上書きできる。"""

    args = cli.parse_args(
        [
            "--topic",
            "テスト",
            "--agent-memory-limit",
            "12",
            "--agent-memory-window",
            "3",
        ]
    )
    cfg = cli.build_meeting_config(args)

    assert cfg.agent_memory_limit == 12
    assert cfg.agent_memory_window == 3
