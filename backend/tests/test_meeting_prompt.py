"""Meeting._agent_prompt に関するテスト。"""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting


def _build_meeting(tmp_path, monkeypatch):
    """テスト用の Meeting インスタンスを生成する補助関数。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "prompt"
    cfg = MeetingConfig(
        topic="テスト会議",
        precision=5,
        agents=[AgentConfig(name="Alice", system="あなたは会議参加者です。")],
        backend_name="ollama",
        chat_mode=False,
        outdir=str(outdir),
    )
    return Meeting(cfg)


@pytest.mark.parametrize("last_summary", ["直前ラウンドのまとめ", ""])
def test_agent_prompt_includes_last_turn_context(tmp_path, monkeypatch, last_summary):
    """非チャットモードで直前発言がプロンプトに含まれることを検証する。"""

    meeting = _build_meeting(tmp_path, monkeypatch)
    meeting.history.append(Turn(speaker="Bob", content="前回のアクションプランを提案。"))
    agent = meeting.cfg.agents[0]

    req = meeting._agent_prompt(agent, last_summary)

    # システムプロンプトに新しい会議ルールが含まれること
    assert "直前の発言（発言者名と要約）に対して具体的に応答する。" in req.system

    # prior_msgs の先頭に直前発言のコンテキストが入ること
    assert req.messages[0]["content"].startswith("前回の発言者: Bob")
    assert "発言要約: 前回のアクションプランを提案。" in req.messages[0]["content"]

    # last_summary が存在する場合は次の要素として含まれること
    if last_summary:
        assert req.messages[1]["content"].startswith("前ラウンド要約:")
    else:
        assert not req.messages[1]["content"].startswith("前ラウンド要約:")
