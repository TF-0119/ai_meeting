"""`Meeting._judge_thoughts` に関する回帰テスト群。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _make_meeting(response: str) -> Meeting:
    """テスト用に必要最低限の属性だけを持つ Meeting インスタンスを生成する。"""

    meeting = Meeting.__new__(Meeting)
    meeting.cfg = SimpleNamespace(topic="テスト", chat_window=2)
    meeting.history = []
    meeting.backend = _StubBackend(response)
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

    result = meeting._judge_thoughts({"Alice": "案A", "Bob": "案B"})

    assert result["winner"] == "Alice"
    assert pytest.approx(result["scores"]["Alice"]["score"], rel=1e-9) == 0.9
    assert "Bob" in result["scores"]


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

    result = meeting._judge_thoughts({"Alice": "案A", "Bob": "案B"})

    assert result["winner"] == "Bob"
    assert chosen_candidates and chosen_candidates[0] == ["Alice", "Bob"]
