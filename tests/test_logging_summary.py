from pathlib import Path

from backend.ai_meeting.logging import LiveLogWriter


def test_append_summary_non_minimal_markdown(tmp_path):
    writer = LiveLogWriter(
        topic="Test",
        outdir=str(tmp_path),
        ui_minimal=False,
        enable_markdown=True,
        enable_jsonl=False,
    )

    writer.append_summary(round_id=2, summary="Summary content")

    markdown_path = Path(writer.dir) / "meeting_live.md"
    content = markdown_path.read_text(encoding="utf-8")

    assert "### Round 2 要約" in content
    assert "Summary content" in content
