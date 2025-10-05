"""`backend.app.start_meeting` のコマンド構築を検証するテスト。"""

from __future__ import annotations

from pathlib import Path
import itertools
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
    pid_counter = itertools.count(4321)

    def _fake_popen(cmd_list, stdout, stderr, cwd, env, creationflags):  # noqa: ANN001 - テスト用
        pid = next(pid_counter)
        store.setdefault("cmd_list_history", []).append(list(cmd_list))
        store["cmd_list"] = list(cmd_list)
        store["env"] = dict(env)
        store.setdefault("pid_history", []).append(pid)
        return _DummyProcess(pid)

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


def test_start_meeting_cmd_accepts_advanced_options(monkeypatch, tmp_path):
    store: dict = {}
    _setup_popen(monkeypatch, store)
    monkeypatch.setattr(app_module, "_processes", {})

    with TestClient(app_module.app) as client:
        response = client.post(
            "/meetings",
            json={
                "topic": "高度設定",
                "agents": "Alice Bob",
                "outdir": str(tmp_path / "advanced"),
                "options": {
                    "flow": {
                        "phaseTurnLimit": ["discussion=2", "resolution=1"],
                        "maxPhases": 3,
                    },
                    "chat": {
                        "chatMode": False,
                        "chatMaxSentences": 4,
                    },
                    "memory": {
                        "agentMemoryLimit": 9,
                        "agentMemoryWindow": 2,
                    },
                },
            },
        )

    assert response.status_code == 200
    data = response.json()
    cmd = data["cmd"]

    assert "--phase-turn-limit discussion=2" in cmd
    assert "--phase-turn-limit resolution=1" in cmd
    assert "--max-phases 3" in cmd
    assert "--no-chat-mode" in cmd
    assert "--chat-max-sentences 4" in cmd
    assert "--agent-memory-limit 9" in cmd
    assert "--agent-memory-window 2" in cmd

    cmd_list = store.get("cmd_list", [])
    phase_values = [cmd_list[i + 1] for i, token in enumerate(cmd_list) if token == "--phase-turn-limit"]
    assert phase_values == ["discussion=2", "resolution=1"]
    expectations = {
        "--max-phases": "3",
        "--chat-max-sentences": "4",
        "--agent-memory-limit": "9",
        "--agent-memory-window": "2",
    }
    for flag, expected in expectations.items():
        index = cmd_list.index(flag)
        assert cmd_list[index + 1] == expected
    assert "--no-chat-mode" in cmd_list


def test_start_meeting_rejects_empty_agent_name(monkeypatch, tmp_path):
    store: dict = {}
    _setup_popen(monkeypatch, store)
    monkeypatch.setattr(app_module, "_processes", {})

    with TestClient(app_module.app) as client:
        response = client.post(
            "/meetings",
            json={
                "topic": "空の名前",  # noqa: RU002 - テストデータ
                "agents": '"" Bob',
                "outdir": str(tmp_path / "invalid"),
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "agent names must not be empty"
    assert "cmd_list" not in store


def test_start_meeting_creates_unique_outdir(monkeypatch, tmp_path):
    store: dict = {}
    _setup_popen(monkeypatch, store)
    monkeypatch.setattr(app_module, "_processes", {})

    base = tmp_path / "duplicate"

    with TestClient(app_module.app) as client:
        first_response = client.post(
            "/meetings",
            json={
                "topic": "重複回避テスト",  # noqa: RU002 - テストデータ
                "agents": "Alice Bob",
                "outdir": str(base),
            },
        )
        second_response = client.post(
            "/meetings",
            json={
                "topic": "重複回避テスト",  # noqa: RU002 - テストデータ
                "agents": "Alice Bob",
                "outdir": str(base),
            },
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_outdir = Path(first_response.json()["outdir"])
    second_outdir = Path(second_response.json()["outdir"])

    assert first_outdir != second_outdir
    assert first_outdir.parent == second_outdir.parent
    assert first_outdir.exists()
    assert second_outdir.exists()
    assert (first_outdir / "meeting_live.jsonl").exists()
    assert (second_outdir / "meeting_live.jsonl").exists()
    assert (first_outdir / "meeting_result.json").exists()
    assert (second_outdir / "meeting_result.json").exists()

    with app_module._processes_lock:
        recorded_outdirs = {info["outdir"] for info in app_module._processes.values()}

    assert recorded_outdirs == {str(first_outdir), str(second_outdir)}
