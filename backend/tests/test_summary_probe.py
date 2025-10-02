"""SummaryProbe クラスの挙動に関するテスト。"""

from backend.ai_meeting.config import AgentConfig, MeetingConfig, Turn
from backend.ai_meeting.summary_probe import SummaryProbe
from backend.ai_meeting.testing import DeterministicLLMBackend


def _make_config() -> MeetingConfig:
    """テスト用の最小構成設定を生成する。"""

    return MeetingConfig(
        topic="要約テスト",
        agents=[
            AgentConfig(name="Alice", system="要約せよ"),
            AgentConfig(name="Bob", system="要約せよ"),
        ],
        summary_probe_temperature=0.6,
        summary_probe_max_tokens=128,
    )


def test_generate_summary_returns_expected_payload():
    """要約が辞書形式で取得できることを検証する。"""

    cfg = _make_config()
    backend = DeterministicLLMBackend([agent.name for agent in cfg.agents])
    probe = SummaryProbe(backend, cfg)
    turn = Turn(speaker="Alice", content="最新の提案を共有する")
    history = [turn]

    payload = probe.generate_summary(turn, history)

    assert payload["turn_index"] == 1
    assert payload["speaker"] == "Alice"
    assert payload["input_text"] == "最新の提案を共有する"
    assert payload["summary"] == "- 差分: 最新の提案を共有する"
    assert payload["parameters"] == {
        "temperature": cfg.summary_probe_temperature,
        "max_tokens": cfg.summary_probe_max_tokens,
    }
    assert payload["meta"] == {}
