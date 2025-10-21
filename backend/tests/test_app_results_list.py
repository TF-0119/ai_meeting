from pathlib import Path
import json
import sys
import types

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if "pydantic_settings" not in sys.modules:
    stub_module = types.ModuleType("pydantic_settings")

    class _BaseSettings:  # noqa: D401 - テスト用の簡易スタブ
        """環境に依存しない簡易 BaseSettings 実装。"""

        def __init__(self, **values):
            for key, value in values.items():
                setattr(self, key, value)

    stub_module.BaseSettings = _BaseSettings
    sys.modules["pydantic_settings"] = stub_module

import backend.app as app_module


def _prepare_logs(tmp_path: Path, monkeypatch) -> Path:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(app_module, "LOGS_DIR", logs_dir)
    return logs_dir


def test_list_results_returns_only_valid_entries(monkeypatch, tmp_path):
    logs_dir = _prepare_logs(tmp_path, monkeypatch)

    valid_dir = logs_dir / "20240105-120000_product_launch"
    valid_dir.mkdir()
    (valid_dir / "meeting_result.json").write_text(
        json.dumps(
            {
                "topic": " 新製品発表の準備 ",
                "started_at": "20240105-120000",
                "final": "合意事項:\n- 発表会の進行表を確定する\n",
            }
        ),
        encoding="utf-8",
    )

    legacy_dir = logs_dir / "20240101-010203_legacy"
    legacy_dir.mkdir()
    (legacy_dir / "meeting_result.json").write_text(
        json.dumps(
            {
                "topic": "過去ログ",
                "turns": [{"speaker": "Alice", "content": "ok"}],
                "final": "  ",
            }
        ),
        encoding="utf-8",
    )

    broken_dir = logs_dir / "20240102-020304_broken"
    broken_dir.mkdir()
    (broken_dir / "meeting_result.json").write_text("{ invalid", encoding="utf-8")

    empty_dir = logs_dir / "20240103-030405_empty"
    empty_dir.mkdir()

    with TestClient(app_module.app) as client:
        response = client.get("/results")

    assert response.status_code == 200
    data = response.json()
    items = data.get("items")
    assert isinstance(items, list)
    assert len(items) == 2

    first = items[0]
    second = items[1]

    assert first["meeting_id"] == "20240105-120000_product_launch"
    assert first["topic"] == "新製品発表の準備"
    assert first["started_at"] == "20240105-120000"
    assert first["final"] == "合意事項:\n- 発表会の進行表を確定する"

    assert second["meeting_id"] == "20240101-010203_legacy"
    assert second["topic"] == "過去ログ"
    assert second["started_at"] == "20240101-010203"
    assert second["final"] == ""


def test_list_results_handles_missing_logs_directory(monkeypatch, tmp_path):
    # LOGS_DIR が存在しない場合でもエラーを返さないことを検証
    nonexistent = tmp_path / "missing"
    monkeypatch.setattr(app_module, "LOGS_DIR", nonexistent)

    with TestClient(app_module.app) as client:
        response = client.get("/results")

    assert response.status_code == 200
    data = response.json()
    items = data.get("items")
    assert isinstance(items, list)
    assert items == []
