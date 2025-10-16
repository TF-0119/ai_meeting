"""Meeting._think の新しい挙動に関するテスト。"""

import json
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
    user_prompt = req.messages[0]["content"]
    assert "last_turn_detail: Bob: 議論の現状を整理したので、次は役割分担を決めたい。" in user_prompt
    assert "前回の発言者（名前）への応答方針を1文でまとめ、必要なら次の質問を用意する。" in req.messages[0]["content"]
    assert "Cycleメモ候補: Diverge/仮説, Learn/観測, Converge/確証, next_goal/次の焦点。" in req.messages[0]["content"]
    assert "Diverge（探索仮説）/Learn（観測や学び）/Converge（収束判断）/next_goal（次に検証する焦点）" in req.system


def test_think_prompt_includes_agent_memory(tmp_path, monkeypatch):
    """覚書や個性が思考プロンプトと結果へ反映されることを検証する。"""

    meeting = _build_meeting(tmp_path, monkeypatch)
    meeting._assign_personalities()
    agent = meeting.cfg.agents[0]
    meeting._agent_memory[agent.name].append(
        meeting._create_memory_entry("重要顧客との約束を最優先で守る", category="info")
    )

    captured = {}

    def _fake_generate(req):
        captured["req"] = req
        return "重要顧客との約束を再確認し、次の打ち手を準備する。"

    meeting.backend.generate = _fake_generate  # type: ignore[method-assign]

    result = meeting._think(agent, last_summary="顧客の期待に応える必要がある")

    assert "重要顧客との約束" in result

    req = captured["req"]
    user_content = req.messages[0]["content"]
    assert "最近の覚書" in user_content
    assert "個性プロファイル" in user_content
    assert "重要顧客との約束を最優先で守る" in user_content
    assert "あなたの個性は『ASSERTIVE』" in req.system


def test_run_emits_cycle_payload_in_think_mode(tmp_path, monkeypatch):
    """run 実行時に content が JSON テンプレへ変換されることを検証する。"""

    meeting = _build_meeting(tmp_path, monkeypatch)
    meeting.cfg.phase_turn_limit = {"discussion": 1}
    meeting.cfg.resolve_phase = False
    meeting.cfg.phase_goal = {"discussion": "見出し禁止のゴール"}

    def _fake_think(self, agent, last_summary):  # noqa: ANN001 - テスト用
        return "見出し案を検討し、箇条書きで共有する"

    def _fake_judge(self, thoughts, last_summary, flow_summary):  # noqa: ANN001 - テスト用
        return {"winner": "Alice", "scores": {"Alice": {"score": 1.0}}}

    def _fake_speak(self, agent, thought):  # noqa: ANN001 - テスト用
        return "箇条書きではなく結論だけ述べます"

    def _fake_summarize(self, new_turn):  # noqa: ANN001 - テスト用
        return {"summary": "- 決定: 方針を共有"}

    monkeypatch.setattr(Meeting, "_think", _fake_think)
    monkeypatch.setattr(Meeting, "_judge_thoughts", _fake_judge)
    monkeypatch.setattr(Meeting, "_speak_from_thought", _fake_speak)
    monkeypatch.setattr(Meeting, "_summarize_round", _fake_summarize)

    meeting.run()
    meeting.metrics.stop()

    assert meeting.history, "少なくとも1ターン生成されること"
    payload = json.loads(meeting.history[0].content)

    assert payload["cycle"] == 1
    assert payload["assumptions"] == []
    assert payload["links"] == []
    assert "見出し" not in payload["diverge"]
    assert "箇条書き" not in payload["converge"]
    assert payload["next_goal"].endswith("ゴール")
    assert "見出し" not in payload["next_goal"]
