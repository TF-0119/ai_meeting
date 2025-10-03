"""失敗時のフォールバック挙動を検証するユニットテスト。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting


def _create_meeting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Meeting:
    """テスト専用の Meeting インスタンスを生成する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "1")
    cfg = MeetingConfig(
        topic="例外時のフォールバック検証",
        agents=[
            AgentConfig(name="Alice", system="要約重視"),
            AgentConfig(name="Bob", system="補足を行う"),
        ],
        outdir=str(tmp_path / "logs"),
        summary_probe_enabled=True,
        summary_probe_log_enabled=False,
    )
    return Meeting(cfg)


def _read_warnings(log_path: Path) -> list[dict]:
    """warning レコードのみを抽出して返す。"""

    records = []
    if not log_path.exists():
        return records
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("type") == "warning":
            records.append(data)
    return records


def test_summarize_round_failure_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """要約生成失敗時に空要約へフォールバックし、警告が記録されることを確認する。"""

    meeting = _create_meeting(tmp_path, monkeypatch)
    turn = Turn(speaker="Alice", content="テスト発言")
    meeting.history.append(turn)

    def _raise_probe(*_: object, **__: object) -> dict:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(meeting._summary_probe, "generate_summary", _raise_probe)

    try:
        result = meeting._summarize_round(turn)
        assert result == {"summary": ""}

        warnings = _read_warnings(meeting.logger.jsonl)
        assert warnings, "summary_probe_failed が記録されること"
        assert warnings[-1]["message"] == "summary_probe_failed"
    finally:
        shutil.rmtree(meeting.logger.dir, ignore_errors=True)


def test_record_agent_memory_skips_invalid_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """不正な要約テキストが渡された場合でも例外なく処理し、警告を残すこと。"""

    meeting = _create_meeting(tmp_path, monkeypatch)
    meeting.history.append(Turn(speaker="Alice", content="正しい発言"))

    try:
        meeting._record_agent_memory(["Alice"], {"summary": ["誤った形式"]}, speaker_name="Alice")

        memory = meeting._agent_memory.get("Alice")
        assert memory and memory[-1].text == "正しい発言"

        warnings = _read_warnings(meeting.logger.jsonl)
        assert warnings, "agent_memory_invalid_summary_text の警告が出力されること"
        assert warnings[-1]["message"] == "agent_memory_invalid_summary_text"
    finally:
        shutil.rmtree(meeting.logger.dir, ignore_errors=True)


def test_conversation_summary_handles_invalid_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """会話サマリー更新時に不正な型があっても例外を出さず警告のみを記録する。"""

    meeting = _create_meeting(tmp_path, monkeypatch)

    try:
        result = meeting._conversation_summary(
            new_turn=Turn(speaker="Alice", content=12345),
            round_summary={"invalid": "type"},
        )

        assert result == ""
        assert meeting._conversation_summary_points == []

        warnings = _read_warnings(meeting.logger.jsonl)
        messages = [w["message"] for w in warnings]
        assert "conversation_summary_invalid_round_summary" in messages
        assert "conversation_summary_invalid_turn_content" in messages
    finally:
        shutil.rmtree(meeting.logger.dir, ignore_errors=True)
