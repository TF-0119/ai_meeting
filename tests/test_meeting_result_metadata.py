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
    """ログチャネル切り替え検証用の設定を生成する。"""

    return MeetingConfig(
        topic="ログチャネル出力の回帰テスト",
        agents=[
            AgentConfig(name="Alice", system="論点をまとめる"),
            AgentConfig(name="Bob", system="補足視点を出す"),
        ],
        phase_turn_limit=1,
        resolve_round=False,
        think_debug=False,
        log_markdown_enabled=False,
        log_jsonl_enabled=True,
        outdir=str(outdir),
    )


def test_meeting_result_retains_required_metadata(tmp_path, monkeypatch) -> None:
    """meeting_result.json に必要なメタ情報が残ることを確認する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "1")
    outdir = tmp_path / "logs"
    cfg = _create_config(outdir)
    meeting = Meeting(cfg)

    try:
        meeting.run()
        log_dir = meeting.logger.dir
        result_path = log_dir / "meeting_result.json"
        assert result_path.exists(), "meeting_result.json が生成されていること"

        data = json.loads(result_path.read_text(encoding="utf-8"))
        files = data.get("files", {})

        assert "meeting_live_jsonl" in files, "JSONL ログのメタ情報が保持されていること"
        assert files["meeting_live_jsonl"] == "meeting_live.jsonl"
        assert "meeting_live_md" not in files, "Markdown ログを無効化した場合はメタ情報が含まれないこと"
        assert not (log_dir / "meeting_live.md").exists(), "無効化した Markdown ログファイルが生成されていないこと"
    finally:
        shutil.rmtree(meeting.logger.dir, ignore_errors=True)
