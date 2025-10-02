"""Meeting._agent_prompt に関するテスト。"""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting


def _build_meeting(tmp_path, monkeypatch, *, chat_mode: bool = False, chat_window: int = 2):
    """テスト用の Meeting インスタンスを生成する補助関数。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    outdir = tmp_path / "prompt"
    cfg = MeetingConfig(
        topic="テスト会議",
        precision=5,
        agents=[AgentConfig(name="Alice", system="あなたは会議参加者です。")],
        backend_name="ollama",
        chat_mode=chat_mode,
        chat_window=chat_window,
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


def test_agent_prompt_injects_summary_in_chat_mode(tmp_path, monkeypatch):
    """チャットモードで会話サマリーが先頭に入ることを検証する。"""

    meeting = _build_meeting(tmp_path, monkeypatch, chat_mode=True, chat_window=2)
    agent = meeting.cfg.agents[0]
    meeting.history = [
        Turn(speaker="Bob", content="課題を共有する"),
        Turn(speaker="Carol", content="対策案を示す"),
        Turn(speaker="Dave", content="役割を確認する"),
    ]
    meeting._conversation_summary(new_turn=meeting.history[-1], round_summary="- 決定: 対策案を採用\n- 次: 担当と期限を整理")

    req = meeting._agent_prompt(agent, last_summary="無視されるサマリー")

    assert req.messages[0]["content"].startswith("会話サマリー:")
    assert "- 決定: 対策案を採用" in req.messages[0]["content"]
    assert req.messages[1]["content"] == f"Carol: {meeting.history[-2].content}"
    assert req.messages[2]["content"] == f"Dave: {meeting.history[-1].content}"


def test_agent_prompt_skips_summary_when_disabled(tmp_path, monkeypatch):
    """サマリー注入が無効な場合は従来どおり直近発言のみになる。"""

    meeting = _build_meeting(tmp_path, monkeypatch, chat_mode=True, chat_window=2)
    meeting.cfg.chat_context_summary = False
    agent = meeting.cfg.agents[0]
    meeting.history = [
        Turn(speaker="Bob", content="課題を共有する"),
        Turn(speaker="Carol", content="対策案を示す"),
    ]
    meeting._conversation_summary(new_turn=meeting.history[-1], round_summary="- 決定: 対策案を採用")

    req = meeting._agent_prompt(agent, last_summary="無視されるサマリー")

    assert not req.messages[0]["content"].startswith("会話サマリー:")
    assert req.messages[0]["content"] == f"Bob: {meeting.history[-2].content}"
    assert req.messages[1]["content"] == f"Carol: {meeting.history[-1].content}"
