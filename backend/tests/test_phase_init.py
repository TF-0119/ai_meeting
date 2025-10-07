"""フェーズ初期化に関するテスト。"""

from pathlib import Path
import sys

import pytest

# `backend` パッケージをインポートできるよう、リポジトリルートをパスに追加する。
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.ai_meeting.cli import build_meeting_config, parse_args
from backend.ai_meeting.config import AgentConfig, MeetingConfig
from backend.ai_meeting.meeting import Meeting


@pytest.mark.parametrize("backend_name", ["ollama"])
def test_meeting_initial_phase_safe(tmp_path, monkeypatch, backend_name):
    """Meeting 初期化時にフェーズ種別の参照が安全に行われることを検証する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "phase_init"
    cfg = MeetingConfig(
        topic="フェーズ初期化テスト",
        precision=5,
        agents=[
            AgentConfig(name="Alice", system="あなたは会議参加者です。"),
            AgentConfig(name="Bob", system="あなたは会議参加者です。"),
        ],
        backend_name=backend_name,
        phase_turn_limit={"discussion": 2},
        outdir=str(outdir),
    )

    meeting = Meeting(cfg)

    assert meeting._phase_state is not None
    assert meeting._phase_state.kind == "discussion"


def test_meeting_monitor_enabled_by_default(tmp_path, monkeypatch):
    """監視AIが既定で有効になり Meeting._monitor が初期化されることを検証する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "monitor_default"
    cfg = MeetingConfig(
        topic="モニター既定値テスト",
        precision=5,
        agents=[
            AgentConfig(name="Alice", system="あなたは会議参加者です。"),
            AgentConfig(name="Bob", system="あなたは会議参加者です。"),
        ],
        backend_name="ollama",
        outdir=str(outdir),
    )

    assert cfg.monitor is True

    meeting = Meeting(cfg)

    assert meeting._monitor is not None


def test_cli_monitor_flags(monkeypatch):
    """CLI の --monitor/--no-monitor フラグが既定値と上書きを適切に扱う。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")

    base_args = ["--topic", "CLI モニター既定", "--agents", "Alice", "Bob"]

    cfg_default = build_meeting_config(parse_args(base_args))
    assert cfg_default.monitor is True

    cfg_disabled = build_meeting_config(parse_args(base_args + ["--no-monitor"]))
    assert cfg_disabled.monitor is False

    cfg_enabled = build_meeting_config(parse_args(base_args + ["--monitor"]))
    assert cfg_enabled.monitor is True
