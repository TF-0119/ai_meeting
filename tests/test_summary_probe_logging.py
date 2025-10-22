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


def _normalize_semantic_core(core: object) -> dict[str, list[dict[str, object]]]:
    """ヘルパー: セマンティックコアの形式差異や揮発的なタイムスタンプを吸収する。"""

    if isinstance(core, list):
        core = {"open_issues": core}

    normalized: dict[str, list[dict[str, object]]] = {}
    if not isinstance(core, dict):
        return normalized

    for category, entries in core.items():
        if not isinstance(entries, list):
            continue
        cleaned: list[dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cleaned_entry = {
                key: value
                for key, value in entry.items()
                if key not in {"created_at", "updated_at"}
            }
            cleaned.append(cleaned_entry)
        if cleaned:
            normalized[str(category)] = cleaned

    return normalized


def _create_config(outdir: Path) -> MeetingConfig:
    """テスト用 MeetingConfig を生成する。"""

    return MeetingConfig(
        topic="要約プローブのログ検証",
        agents=[
            AgentConfig(name="Alice", system="要点を簡潔に整理する"),
            AgentConfig(name="Bob", system="視点を補う"),
        ],
        phase_turn_limit=2,
        resolve_phase=False,
        think_debug=False,
        summary_probe_enabled=True,
        summary_probe_log_enabled=True,
        summary_probe_phase_log_enabled=True,
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
        summary_entries = list(meeting.logger.iter_summary_probe())
        assert summary_entries, "summary_probe ログに JSON エントリが存在すること"

        phase_summary_path = log_dir / cfg.summary_probe_phase_filename
        phase_records = [
            json.loads(line)
            for line in phase_summary_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert phase_records, "フェーズ要約ログにエントリが存在すること"
        assert all("phase" in rec and "summary" in rec for rec in phase_records)

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

        result_data = json.loads((log_dir / "meeting_result.json").read_text(encoding="utf-8"))
        semantic_core = _normalize_semantic_core(result_data.get("semantic_core"))
        assert semantic_core, "meeting_result.json に semantic_core が記録されていること"
        for category, entries in semantic_core.items():
            assert entries, f"カテゴリ {category} にエントリが記録されていること"
            for entry in entries:
                assert "text" in entry and entry["text"], "エントリに text が含まれること"
                assert "source" in entry and entry["source"], "エントリに source が含まれること"
                assert "weight" in entry, "エントリに weight が含まれること"
                assert "mentions" in entry, "エントリに mentions が含まれること"
        files_meta = result_data.get("files", {})
        assert files_meta.get("summary_probe_phase_json") == cfg.summary_probe_phase_filename
    finally:
        shutil.rmtree(meeting.logger.dir, ignore_errors=True)

