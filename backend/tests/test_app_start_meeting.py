"""`backend.app.start_meeting` のコマンド構築を検証するテスト。"""

from __future__ import annotations

from pathlib import Path
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


class _DummyProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid


def _setup_popen(monkeypatch, store: dict) -> None:
    def _fake_popen(cmd_list, stdout, stderr, cwd, env, creationflags):  # noqa: ANN001 - テスト用
        store["cmd_list"] = list(cmd_list)
        store["env"] = dict(env)
        return _DummyProcess()

    monkeypatch.setattr(app_module.subprocess, "Popen", _fake_popen)


def test_start_meeting_cmd_uses_defaults(monkeypatch, tmp_path):
    store: dict = {}
    _setup_popen(monkeypatch, store)
    monkeypatch.setattr(app_module, "_processes", {})

    with TestClient(app_module.app) as client:
        response = client.post(
            "/meetings",
            json={
                "topic": "デフォルト検証",
                "agents": "Alice Bob",
                "outdir": str(tmp_path / "default"),
            },
        )
    assert response.status_code == 200
    data = response.json()
    cmd = data["cmd"]

    assert "--backend ollama" in cmd
    assert "--ollama-model" not in cmd
    assert "--openai-model" not in cmd
    assert "--ollama-url http://127.0.0.1:11434" in cmd

    assert "cmd_list" in store
    assert "--backend" in store["cmd_list"]
    assert "--ollama-model" not in store["cmd_list"]
    assert "--openai-model" not in store["cmd_list"]


def test_start_meeting_cmd_accepts_llm_overrides(monkeypatch, tmp_path):
    store: dict = {}
    _setup_popen(monkeypatch, store)
    monkeypatch.setattr(app_module, "_processes", {})

    with TestClient(app_module.app) as client:
        response = client.post(
            "/meetings",
            json={
                "topic": "モデル指定",
                "agents": "Alice Bob",
                "outdir": str(tmp_path / "override"),
                "llm": {
                    "llm_backend": "openai",
                    "ollama_model": "custom-ollama",
                    "openai_model": "gpt-4o-mini",
                },
            },
        )
    assert response.status_code == 200
    data = response.json()
    cmd = data["cmd"]

    assert "--backend openai" in cmd
    assert "--ollama-model custom-ollama" in cmd
    assert "--openai-model gpt-4o-mini" in cmd
    assert "--ollama-url" not in cmd

    assert "cmd_list" in store
    assert store["cmd_list"].count("--backend") == 1
    assert "openai" in store["cmd_list"]
    assert "--ollama-model" in store["cmd_list"]
    assert "--openai-model" in store["cmd_list"]
    assert "--ollama-url" not in store["cmd_list"]
