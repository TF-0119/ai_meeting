"""フェーズ初期化に関するテスト。"""

import pytest

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
