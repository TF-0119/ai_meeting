"""Meeting._think の新しい挙動に関するテスト。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting


def _build_meeting(tmp_path, monkeypatch):
    """テスト用の Meeting インスタンスを生成する補助関数。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "think"
    cfg = MeetingConfig(
        topic="テスト会議",
        precision=5,
        agents=[AgentConfig(name="Alice", system="あなたは会議参加者です。")],
        backend_name="ollama",
        outdir=str(outdir),
    )
    return Meeting(cfg)


def test_think_prompt_focuses_on_last_speaker(tmp_path, monkeypatch):
    """思考プロンプトが直前発言者への応答指示と抜粋を含むことを検証する。"""

    meeting = _build_meeting(tmp_path, monkeypatch)
    meeting.history.append(
        Turn(speaker="Bob", content="議論の現状を整理したので、次は役割分担を決めたい。")
    )
    agent = meeting.cfg.agents[0]

    captured = {}

    def _fake_generate(req):
        captured["req"] = req
        return "Bobへの応答方針を固める。質問も考える。"

    meeting.backend.generate = _fake_generate  # type: ignore[method-assign]

    result = meeting._think(agent, last_summary="前回までに課題共有済み")

    assert "Bob" in result  # 応答方針に相手の名前が含まれていること

    req = captured["req"]
    assert req.last_turn_detail == "Bob: 議論の現状を整理したので、次は役割分担を決めたい。"
    assert "last_turn_detail: Bob:" in req.messages[0]["content"]
    assert "前回の発言者（名前）への応答方針を1文でまとめ、必要なら次の質問を用意する。" in req.messages[0]["content"]

