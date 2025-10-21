import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if "pydantic_settings" not in sys.modules:
    stub_module = types.ModuleType("pydantic_settings")

    class _BaseSettings:  # noqa: D401 - テスト用の簡易スタブ
        """テストで最低限必要な BaseSettings 互換クラス。"""

        def __init__(self, **values):
            for key, value in values.items():
                setattr(self, key, value)

    stub_module.BaseSettings = _BaseSettings
    sys.modules["pydantic_settings"] = stub_module

from backend.app import _has_valid_meeting_result


def test_has_valid_meeting_result_returns_false_for_empty_file(tmp_path: Path) -> None:
    """空ファイルの場合は False が返ることを確認する。"""

    target = tmp_path / "meeting_result.json"
    target.touch()

    assert _has_valid_meeting_result(target) is False


def test_has_valid_meeting_result_returns_false_for_invalid_json(tmp_path: Path) -> None:
    """壊れた JSON の場合も False になることを確認する。"""

    target = tmp_path / "meeting_result.json"
    target.write_text("{invalid", encoding="utf-8")

    assert _has_valid_meeting_result(target) is False


def test_has_valid_meeting_result_returns_true_for_valid_payload(tmp_path: Path) -> None:
    """最終結果が格納されている場合は True が返ることを確認する。"""

    target = tmp_path / "meeting_result.json"
    payload = {
        "final": "合意事項: テストを完了する",  # final が空でないことを明示する
        "turns": [{"speaker": "Alice", "content": "こんにちは"}],
        "kpi": {"progress": 100},
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert _has_valid_meeting_result(target) is True
