"""MeetingConfig の要約プローブ関連フィールドに関するテスト。"""

import pytest
from pydantic import ValidationError

from backend.ai_meeting.config import AgentConfig, MeetingConfig


def _base_agents():
    """最小構成のエージェントリストを返すヘルパー。"""

    return [
        AgentConfig(name="Alice", system="短く要点をまとめてください。"),
        AgentConfig(name="Bob", system="短く要点をまとめてください。"),
    ]


def test_summary_probe_defaults_and_assignment():
    """要約プローブ関連フィールドのデフォルトと代入を確認する。"""

    cfg = MeetingConfig(topic="要約プローブの確認", agents=_base_agents())

    # 既定値では無効化され、ファイル名は定数になる。
    assert cfg.summary_probe_enabled is False
    assert cfg.summary_probe_filename == "summary_probe.json"
    assert cfg.summary_probe_temperature == 0.4
    assert cfg.summary_probe_max_tokens == 300

    # 代入時に validate_assignment が働くか確認する。
    cfg.summary_probe_enabled = True
    assert cfg.summary_probe_enabled is True
    cfg.summary_probe_temperature = 0.55
    cfg.summary_probe_max_tokens = 512
    assert cfg.summary_probe_temperature == 0.55
    assert cfg.summary_probe_max_tokens == 512


def test_summary_probe_filename_validation():
    """summary_probe_filename への不正代入が検出されることを確認する。"""

    cfg = MeetingConfig(
        topic="要約プローブのファイル名検証",
        agents=_base_agents(),
        summary_probe_enabled=True,
        summary_probe_filename="custom_summary.json",
        summary_probe_temperature=0.3,
        summary_probe_max_tokens=256,
    )

    assert cfg.summary_probe_enabled is True
    assert cfg.summary_probe_filename == "custom_summary.json"
    assert cfg.summary_probe_temperature == 0.3
    assert cfg.summary_probe_max_tokens == 256

    with pytest.raises(ValidationError):
        cfg.summary_probe_filename = 42  # type: ignore[assignment]
