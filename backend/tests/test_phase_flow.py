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
        resolve_phase=True,
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


def _patch_summaries(monkeypatch, texts):
    sequence = iter(texts)

    def _fake(self, new_turn):  # type: ignore[override]
        text = next(sequence, "")
        return {"summary": text}

    monkeypatch.setattr(Meeting, "_summarize_round", _fake)


def test_resolution_phase_resolves_all_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "resolution_success"
    agents = build_agents(["Alice", "Bob"])
    cfg = MeetingConfig(
        topic="残課題多段解消テスト",
        precision=5,
        agents=agents,
        phase_turn_limit={"resolution": 4},
        resolve_phase=True,
        outdir=str(outdir),
    )
    meeting = Meeting(cfg)
    meeting._pending.items.update({"課題Aの担当調整", "課題Bの仕様確定"})  # type: ignore[attr-defined]

    _patch_summaries(
        monkeypatch,
        [
            "- 課題: 課題Bの仕様確定\n- 課題: 課題Cのリスク整理",
            "- 課題: 課題Bの仕様確定",
            "- 課題: 課題Bの仕様確定",
            "全て解決済みです",
        ],
    )

    last_summary, global_turn = meeting._run_resolution_phase(meeting.cfg.agents, "", 1)

    assert last_summary == "全て解決済みです"
    assert meeting._pending.items == set()
    assert meeting._unresolved_history[-1] == 0
    assert global_turn == 5
    assert len(meeting.history) == 4
    meeting.metrics.stop()


def test_resolution_phase_retains_unresolved_when_stalled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "resolution_stall"
    agents = build_agents(["Alice", "Bob"])
    cfg = MeetingConfig(
        topic="残課題停滞テスト",
        precision=5,
        agents=agents,
        phase_turn_limit={"resolution": 2},
        resolve_phase=True,
        outdir=str(outdir),
    )
    meeting = Meeting(cfg)
    meeting._pending.items.update({"課題Aの担当調整", "課題Bの仕様確定"})  # type: ignore[attr-defined]

    _patch_summaries(
        monkeypatch,
        [
            "- 課題: 課題Aの担当調整\n- 課題: 課題Bの仕様確定",
            "- 課題: 課題Aの担当調整\n- 課題: 課題Bの仕様確定",
        ],
    )

    last_summary, global_turn = meeting._run_resolution_phase(meeting.cfg.agents, "", 1)

    assert last_summary == "- 課題: 課題Aの担当調整\n- 課題: 課題Bの仕様確定"
    assert meeting._pending.items == {"課題Aの担当調整", "課題Bの仕様確定"}
    assert meeting._unresolved_history[-1] == 2
    assert global_turn == 3
    assert len(meeting.history) == 2
    meeting.metrics.stop()
