"""均衡ロジックにおける類似度調整の挙動を検証するテスト。"""

from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.meeting import Meeting


@pytest.mark.parametrize("sim_window", [1])
def test_similarity_penalty_uses_last_utterance_and_skips_missing(monkeypatch, tmp_path, sim_window):
    """直近発言を利用した類似度ペナルティ適用を確認する。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "1")
    cfg = MeetingConfig(
        topic="テスト議題",
        agents=[
            AgentConfig(name="Alice", system="- 名前: Alice"),
            AgentConfig(name="Bob", system="- 名前: Bob"),
            AgentConfig(name="Charlie", system="- 名前: Charlie"),
        ],
        equilibrium=True,
        sim_window=sim_window,
        cooldown=0.0,
        cooldown_span=0,
        outdir=str(tmp_path / "logs"),
    )
    meeting = Meeting(cfg)
    meeting.history = [
        Turn(speaker="Bob", content="独自の提案を提示"),
        Turn(speaker="Alice", content="安全性について議論"),
    ]
    meeting._last_spoke = {}

    last_utterances = meeting._collect_last_utterances()
    assert last_utterances == {
        "Alice": "安全性について議論",
        "Bob": "独自の提案を提示",
        "Charlie": None,
    }

    sim_recent_text = meeting._concat_recent_text(meeting.cfg.sim_window)
    sim_tokens_recent = meeting._token_set(sim_recent_text)
    base_scores = {name: 0.8 for name in ["Alice", "Bob", "Charlie"]}

    adj = {}
    global_turn = len(meeting.history)
    for ag in meeting.cfg.agents:
        score = base_scores.get(ag.name, 0.0)
        if ag.name in meeting._last_spoke:
            ago = global_turn - meeting._last_spoke[ag.name]
            if 0 <= ago <= meeting.cfg.cooldown_span:
                score -= meeting.cfg.cooldown
        agent_last = last_utterances.get(ag.name)
        if sim_tokens_recent and agent_last:
            sim = meeting._similarity_tokens(
                meeting._token_set(agent_last),
                sim_tokens_recent,
            )
            score -= meeting.cfg.sim_penalty * sim
        adj[ag.name] = score

    expected_alice = base_scores["Alice"] - meeting.cfg.sim_penalty
    assert math.isclose(adj["Alice"], expected_alice)
    assert math.isclose(adj["Bob"], base_scores["Bob"])
    assert math.isclose(adj["Charlie"], base_scores["Charlie"])

    meeting.metrics.stop()
