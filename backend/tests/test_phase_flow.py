import json
from pathlib import Path

import pytest

from backend.ai_meeting.cli import build_agents
from backend.ai_meeting.config import MeetingConfig
from backend.ai_meeting.meeting import Meeting


@pytest.mark.parametrize("pending_item", ["安全要件の整理"])
def test_meeting_result_includes_phase_timeline(tmp_path: Path, monkeypatch, pending_item: str) -> None:
    """meeting_result.json にフェーズ設定とタイムラインが含まれることを検証する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "phase_flow"
    agents = build_agents(["Alice", "Bob"])
    cfg = MeetingConfig(
        topic="フェーズ遷移テスト",
        precision=5,
        agents=agents,
        phase_turn_limit={"discussion": 1, "resolution": 1},
        phase_goal={"discussion": "議題を整理", "resolution": "残課題を解消"},
        max_phases=4,
        resolve_round=True,
        outdir=str(outdir),
    )
    meeting = Meeting(cfg)
    meeting._pending.items.add(pending_item)  # type: ignore[attr-defined]
    meeting.run()

    result_path = outdir / "meeting_result.json"
    data = json.loads(result_path.read_text(encoding="utf-8"))

    assert data["phase_turn_limit"] == {"discussion": 1, "resolution": 1}
    assert data["phase_goal"] == {"discussion": "議題を整理", "resolution": "残課題を解消"}
    assert data["rounds"] == 1

    phases = data["phases"]
    assert len(phases) >= 2
    assert phases[0]["kind"] == "discussion"
    assert phases[0]["goal"] == "議題を整理"

    resolution_phases = [p for p in phases if p["kind"] == "resolution"]
    assert resolution_phases, "残課題消化フェーズが記録されていません"
    assert resolution_phases[0]["goal"] == "残課題を解消"
    assert resolution_phases[0]["turn_count"] >= 1

    for phase in phases:
        assert "turn_indices" in phase and isinstance(phase["turn_indices"], list)
        assert "unresolved_counts" in phase
