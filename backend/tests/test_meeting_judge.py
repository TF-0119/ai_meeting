"""`Meeting._judge_thoughts` に関する回帰テスト群。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.ai_meeting.meeting as meeting_module  # noqa: E402
from backend.ai_meeting.meeting import Meeting  # noqa: E402


class _StubBackend:
    """固定レスポンスを返す LLM バックエンドのスタブ。"""

    def __init__(self, response: str):
        self.response = response
        self.requests = []

    def generate(self, req):  # noqa: D401 - Meeting と同一シグネチャを維持
        self.requests.append(req)
        return self.response


def _make_meeting(response: str, agent_names: Optional[List[str]] = None) -> Meeting:
    """テスト用に必要最低限の属性だけを持つ Meeting インスタンスを生成する。"""

    if agent_names is None:
        agent_names = ["Alice", "Bob"]

    meeting = Meeting.__new__(Meeting)
    meeting.cfg = SimpleNamespace(
        topic="テスト",
        chat_window=2,
        chat_mode=True,
        chat_max_sentences=2,
        chat_max_chars=120,
        chat_context_summary=True,
        think_judge_include_topic=True,
        think_judge_include_recent=True,
        think_judge_include_recent_summary=True,
        think_judge_include_flow_summary=True,
        agents=[SimpleNamespace(name=name, system="", style="") for name in agent_names],
        cooldown=0.0,
        cooldown_span=0,
    )
    meeting.history = []
    meeting.backend = _StubBackend(response)
    meeting._conversation_summary_points = []
    meeting._test_mode = False
    meeting.logger = SimpleNamespace(
        append_warning=lambda *args, **kwargs: None,
        new_span_id=lambda: "span-test",
    )
    meeting._log_metadata = {
        "prompt_version": "test",
        "model_version": "test-model",
        "decode_params": {"temperature": 0.0, "max_tokens": 0},
    }
    meeting._round_span_ids = {}
    meeting._current_round_id = None
    meeting._current_phase_context = {}
    meeting._last_spoke = {}
    meeting._latest_kpi_metrics = {}
    return meeting


def test_judge_thoughts_normalizes_names_and_winner() -> None:
    """winner と scores のキーが正規化されることを検証する。"""

    response = json.dumps(
        {
            "scores": {
                " alice ": {
                    "flow": 0.2,
                    "goal": 0.3,
                    "quality": 0.4,
                    "novelty": 0.5,
                    "action": 0.6,
                    "score": 0.9,
                    "rationale": "  妥当性が高い  ",
                }
            },
            "winner": " ALICE  ",
        },
        ensure_ascii=False,
    )
    meeting = _make_meeting(response)

    flow_summary = meeting._conversation_summary()
    result = meeting._judge_thoughts({"Alice": "案A", "Bob": "案B"}, "", flow_summary)

    assert result["winner"] == "Alice"
    assert pytest.approx(result["scores"]["Alice"]["score"], rel=1e-9) == 0.9
    assert "Bob" in result["scores"]


def test_judge_thoughts_handles_non_numeric_scores() -> None:
    """数値フィールドが文字列や非数値でも 0.0 にフォールバックする。"""

    response = json.dumps(
        {
            "scores": {
                "Alice": {
                    "flow": "fast",
                    "goal": "unknown",
                    "quality": "NaN",
                    "novelty": "?",
                    "action": "-",
                    "score": "bad",
                }
            }
        },
        ensure_ascii=False,
    )
    meeting = _make_meeting(response, ["Alice"])

    flow_summary = meeting._conversation_summary()
    result = meeting._judge_thoughts({"Alice": "案A"}, "", flow_summary)

    alice_scores = result["scores"]["Alice"]
    assert alice_scores["flow"] == 0.0
    assert alice_scores["goal"] == 0.0
    assert alice_scores["quality"] == 0.0
    assert alice_scores["novelty"] == 0.0
    assert alice_scores["action"] == 0.0
    assert alice_scores["score"] == 0.0


def test_judge_thoughts_fallback_uses_random_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """勝者名が特定できない場合にランダム選択が利用されることを検証する。"""

    response = json.dumps(
        {
            "scores": {
                "alice": {"score": 0.8},
                "bob": {"score": 0.8},
            },
            "winner": "??",
        }
    )
    meeting = _make_meeting(response)
    chosen_candidates = []

    def _fake_choice(seq):
        chosen_candidates.append(list(seq))
        return seq[-1]

    monkeypatch.setattr(meeting_module.random, "choice", _fake_choice)

    flow_summary = meeting._conversation_summary()
    result = meeting._judge_thoughts({"Alice": "案A", "Bob": "案B"}, "", flow_summary)

    assert result["winner"] == "Bob"
    assert chosen_candidates and chosen_candidates[0] == ["Alice", "Bob"]


def test_resolve_winner_switches_from_previous_speaker() -> None:
    """前回と同じ勝者候補が返ってきた場合に別エージェントへ切り替える。"""

    meeting = _make_meeting("{}", ["Alice", "Bob", "Carol"])
    verdict = {
        "winner": "Alice",
        "scores": {
            "Alice": {"score": 0.9},
            "Bob": {"score": 0.9},
            "Carol": {"score": 0.9},
        },
    }

    resolved = meeting._resolve_winner(verdict, "Alice", 3)

    assert resolved == "Bob"


def test_resolve_winner_switches_even_without_scores() -> None:
    """score 情報が欠損していても直前と異なるエージェントを選ぶ。"""

    meeting = _make_meeting("{}", ["Alice", "Bob"])
    verdict = {"winner": "Alice", "scores": {}}

    resolved = meeting._resolve_winner(verdict, "Alice", 2)

    assert resolved == "Bob"


def test_resolve_winner_penalizes_recent_speaker() -> None:
    """直前に発言した参加者は cooldown により選ばれにくくなる。"""

    meeting = _make_meeting("{}", ["Alice", "Bob"])
    meeting.cfg.cooldown = 0.3
    meeting.cfg.cooldown_span = 2
    meeting._last_spoke = {"Alice": 9}

    verdict = {
        "scores": {
            "Alice": {"score": 0.9},
            "Bob": {"score": 0.85},
        }
    }

    resolved = meeting._resolve_winner(verdict, None, 10)

    assert resolved == "Bob"
    assert verdict["scores"]["Alice"]["score"] < 0.9


def test_resolve_winner_rewards_novelty_when_diversity_low() -> None:
    """diversity が低い場合は novelty の高い案にボーナスが与えられる。"""

    meeting = _make_meeting("{}", ["Alice", "Bob"])
    meeting._latest_kpi_metrics = {"diversity": 0.2}
    verdict = {
        "scores": {
            "Alice": {"score": 0.5, "novelty": 0.9, "action": 0.3},
            "Bob": {"score": 0.6, "novelty": 0.2, "action": 0.7},
        }
    }

    resolved = meeting._resolve_winner(verdict, None, 5)

    assert resolved == "Alice"
    assert verdict["scores"]["Alice"]["score"] > 0.5


def test_judge_thoughts_prompt_includes_summaries() -> None:
    """審査プロンプトに直近要約と会話サマリーが含まれる。"""

    meeting = _make_meeting("{}", ["Alice"])
    meeting.history = [SimpleNamespace(speaker="Alice", content="こんにちは")]
    meeting._conversation_summary_points = ["Alice: こんにちは"]
    last_summary = "前回のまとめ"
    flow_summary = meeting._conversation_summary()

    meeting._judge_thoughts({"Alice": "案A"}, last_summary, flow_summary)

    assert meeting.backend.requests, "リクエストが記録されていません"
    prompt = meeting.backend.requests[-1].messages[0]["content"]
    assert f"直近要約: {last_summary}" in prompt
    assert "会話の流れサマリー" in prompt
    assert "- Alice: こんにちは" in prompt


def test_judge_thoughts_context_flags_disable() -> None:
    """フラグを無効化すると対応する情報がプロンプトから除外される。"""

    meeting = _make_meeting("{}", ["Alice"])
    meeting.cfg.think_judge_include_topic = False
    meeting.cfg.think_judge_include_recent = False
    meeting.cfg.think_judge_include_recent_summary = False
    meeting.cfg.think_judge_include_flow_summary = False

    last_summary = "前回のまとめ"
    flow_summary = meeting._conversation_summary()

    meeting._judge_thoughts({"Alice": "案A"}, last_summary, flow_summary)

    prompt = meeting.backend.requests[-1].messages[0]["content"]
    assert "Topic:" not in prompt
    assert "直近発言" not in prompt
    assert "直近要約" not in prompt
    assert "会話の流れサマリー" not in prompt
    assert "候補:\nAlice: 案A" in prompt


def test_judge_thoughts_flags_forced_in_test_mode() -> None:
    """テストモードではフラグを無効化しても情報が保持される。"""

    meeting = _make_meeting("{}", ["Alice"])
    meeting._test_mode = True
    meeting.cfg.think_judge_include_topic = False
    meeting.cfg.think_judge_include_recent = False
    meeting.cfg.think_judge_include_recent_summary = False
    meeting.cfg.think_judge_include_flow_summary = False

    last_summary = "前回のまとめ"
    flow_summary = meeting._conversation_summary()

    meeting._judge_thoughts({"Alice": "案A"}, last_summary, flow_summary)

    prompt = meeting.backend.requests[-1].messages[0]["content"]
    assert "Topic:" in prompt
    assert "直近発言" in prompt
    assert "直近要約" in prompt
    assert "会話の流れサマリー" in prompt
