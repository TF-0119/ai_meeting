"""summary_probe ログの出力を検証する統合テスト。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig  # noqa: E402
from backend.ai_meeting.meeting import Meeting  # noqa: E402


def _create_config(outdir: Path) -> MeetingConfig:
    """テスト用 MeetingConfig を生成する。"""

    return MeetingConfig(
        topic="要約プローブのログ検証",
        agents=[
            AgentConfig(name="Alice", system="要点を簡潔に整理する"),
            AgentConfig(name="Bob", system="視点を補う"),
        ],
        phase_turn_limit=2,
        resolve_round=False,
        think_debug=False,
        summary_probe_enabled=True,
        summary_probe_log_enabled=True,
        outdir=str(outdir),
    )


def test_summary_probe_logging_appends_json(tmp_path, monkeypatch) -> None:
    """summary_probe ログが JSON 追記され、既存ログ形式に影響しないことを確認する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "1")
    outdir = tmp_path / "logs"
    cfg = _create_config(outdir)
    meeting = Meeting(cfg)

    try:
        meeting.run()
        log_dir = meeting.logger.dir
        summary_path = log_dir / cfg.summary_probe_filename

        summary_entries = [
            json.loads(line)
            for line in summary_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert summary_entries, "summary_probe ログに JSON エントリが存在すること"

        live_records = [
            json.loads(line)
            for line in (log_dir / "meeting_live.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary_records = [rec for rec in live_records if rec.get("type") == "summary"]
        expected_rounds = cfg.get_phase_turn_limit() or 0
        assert len(summary_records) == expected_rounds
        assert all("summary" in rec for rec in summary_records)
        assert all(rec.get("type") != "summary_probe" for rec in live_records)
        assert len(summary_entries) == len(summary_records)
        assert [rec["summary"] for rec in summary_records] == [entry["summary"] for entry in summary_entries]
    finally:
        shutil.rmtree(meeting.logger.dir, ignore_errors=True)
