from pathlib import Path
import sys
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting


def _build_meeting(
    tmp_path,
    monkeypatch,
    *,
    memory_limit=3,
    memory_window=2,
    agents: Optional[Iterable[AgentConfig]] = None,
):
    """メモリ検証用の Meeting を生成する補助関数。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    cfg = MeetingConfig(
        topic="メモリ検証",  # テスト用
        precision=5,
        agents=list(
            agents
            if agents is not None
            else [
                AgentConfig(
                    name="Alice",
                    system="あなたは会議参加者です。",
                )
            ]
        ),
        backend_name="ollama",
        agent_memory_limit=memory_limit,
        agent_memory_window=memory_window,
        outdir=str(tmp_path / "memory"),
    )
    return Meeting(cfg)


def test_record_agent_memory_appends_and_trims(tmp_path, monkeypatch):
    """ターンごとの要約がエージェントメモリに追記され上限で切り詰められることを検証する。"""

    meeting = _build_meeting(tmp_path, monkeypatch, memory_limit=3)
    agent = meeting.cfg.agents[0]

    meeting.history.append(Turn(speaker=agent.name, content="最初の提案を共有。"))
    meeting._record_agent_memory(agent.name, {"summary": "- 決定: 提案を採用\n- 次: 実行プランを策定"})

    assert meeting._agent_memory[agent.name] == ["決定: 提案を採用", "次: 実行プランを策定"]

    meeting.history.append(Turn(speaker=agent.name, content="進捗を報告。"))
    meeting._record_agent_memory(agent.name, {"summary": "- 進捗: 実装を開始"})

    assert meeting._agent_memory[agent.name] == [
        "決定: 提案を採用",
        "次: 実行プランを策定",
        "進捗: 実装を開始",
    ]

    meeting.history.append(Turn(speaker=agent.name, content="懸念点を共有。"))
    meeting._record_agent_memory(agent.name, {"summary": "- 注意: 期限が厳しい"})

    # 上限3のため最古の1件が捨てられ、直近3件が残る
    assert meeting._agent_memory[agent.name] == [
        "次: 実行プランを策定",
        "進捗: 実装を開始",
        "注意: 期限が厳しい",
    ]


def test_record_agent_memory_broadcasts_to_all_agents(tmp_path, monkeypatch):
    """要約が全エージェントに共有され、話者名が付与されることを検証する。"""

    meeting = _build_meeting(
        tmp_path,
        monkeypatch,
        memory_limit=3,
        agents=[
            AgentConfig(name="Alice", system="司会者"),
            AgentConfig(name="Bob", system="参加者"),
            AgentConfig(name="Carol", system="参加者"),
        ],
    )
    speaker = meeting.cfg.agents[0]
    others = meeting.cfg.agents[1:]
    everyone = [ag.name for ag in meeting.cfg.agents]

    meeting.history.append(Turn(speaker=speaker.name, content="初回の提案。"))
    meeting._record_agent_memory(
        everyone,
        {"summary": "- 決定: プロトタイプを作成\n- 次: レビューの準備"},
        speaker_name=speaker.name,
    )

    assert meeting._agent_memory[speaker.name] == [
        "決定: プロトタイプを作成",
        "次: レビューの準備",
    ]

    for listener in others:
        assert meeting._agent_memory[listener.name] == [
            f"{speaker.name}の発言: 決定: プロトタイプを作成",
            f"{speaker.name}の発言: 次: レビューの準備",
        ]

    meeting.history.append(Turn(speaker=speaker.name, content="二度目の共有。"))
    meeting._record_agent_memory(
        everyone,
        {"summary": "- 決定: プロトタイプを作成\n- 次: レビューの準備"},
        speaker_name=speaker.name,
    )

    assert meeting._agent_memory[speaker.name] == [
        "決定: プロトタイプを作成",
        "次: レビューの準備",
    ]
    for listener in others:
        assert meeting._agent_memory[listener.name] == [
            f"{speaker.name}の発言: 決定: プロトタイプを作成",
            f"{speaker.name}の発言: 次: レビューの準備",
        ]

    meeting.history.append(Turn(speaker=speaker.name, content="追加の注意喚起。"))
    meeting._record_agent_memory(
        everyone,
        {"summary": "- 注意: スケジュールを見直す"},
        speaker_name=speaker.name,
    )

    assert meeting._agent_memory[speaker.name] == [
        "決定: プロトタイプを作成",
        "次: レビューの準備",
        "注意: スケジュールを見直す",
    ]

    for listener in others:
        assert meeting._agent_memory[listener.name] == [
            f"{speaker.name}の発言: 決定: プロトタイプを作成",
            f"{speaker.name}の発言: 次: レビューの準備",
            f"{speaker.name}の発言: 注意: スケジュールを見直す",
        ]
        snapshot = meeting._agent_memory_snapshot(listener.name)
        assert snapshot == [
            f"{speaker.name}の発言: 次: レビューの準備",
            f"{speaker.name}の発言: 注意: スケジュールを見直す",
        ]

    assert meeting._agent_memory_snapshot(speaker.name) == [
        "次: レビューの準備",
        "注意: スケジュールを見直す",
    ]


def test_agent_prompt_includes_existing_memory(tmp_path, monkeypatch):
    """エージェント設定の初期メモリがプロンプトへ注入されることを検証する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    cfg = MeetingConfig(
        topic="メモリ検証",
        precision=5,
        agents=[
            AgentConfig(
                name="Bob",
                system="あなたは会議参加者です。",
                memory=["事前調査済み: 競合はA社"],
            )
        ],
        backend_name="ollama",
        agent_memory_window=2,
        outdir=str(tmp_path / "prompt"),
    )
    meeting = Meeting(cfg)
    agent = meeting.cfg.agents[0]

    req = meeting._agent_prompt(agent, last_summary="")

    assert any("最近の覚書" in msg["content"] for msg in req.messages)
    assert any("競合はA社" in msg["content"] for msg in req.messages)
