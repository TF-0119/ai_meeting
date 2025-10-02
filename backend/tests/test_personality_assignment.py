"""個性テンプレートの割り当てとメモリ反映を検証するテスト。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_meeting.config import AgentConfig, MeetingConfig
from backend.ai_meeting.meeting import Meeting


def test_personality_assignment_is_deterministic(tmp_path, monkeypatch):
    """テストモードでは個性が巡回割り当てされメモリへ保存される。"""

    monkeypatch.setenv("AI_MEETING_TEST_MODE", "deterministic")
    cfg = MeetingConfig(
        topic="個性テスト",
        precision=5,
        agents=[
            AgentConfig(name="Alice", system="会議参加者として振る舞う。"),
            AgentConfig(name="Bob", system="会議参加者として振る舞う。"),
            AgentConfig(name="Carol", system="会議参加者として振る舞う。"),
        ],
        backend_name="ollama",
        outdir=str(tmp_path / "logs"),
    )
    meeting = Meeting(cfg)

    meeting._assign_personalities()

    assigned = [
        meeting._personality_profiles[agent.name].name for agent in meeting.cfg.agents
    ]
    assert assigned == ["ASSERTIVE", "ANALYTICAL", "EMPATHIC"]

    for agent in meeting.cfg.agents:
        memory_text = meeting._agent_personality_memory.get(agent.name)
        assert memory_text is not None
        assert "個性プロファイル" in memory_text
        formatted = meeting._format_agent_memory(agent.name)
        assert formatted is not None
        assert memory_text in formatted
