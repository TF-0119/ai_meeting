"""`python -m backend.ai_meeting` の主要オプションを網羅するエンドツーエンドテスト。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "docs" / "samples" / "cli_baseline"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.ai_meeting.llm import LLMRequest, OllamaBackend


def _run_cli(tmp_path: Path, name: str, args: list[str], extra_env: dict[str, str] | None = None) -> Path:
    outdir = tmp_path / name
    env = os.environ.copy()
    env["AI_MEETING_TEST_MODE"] = "deterministic"
    if extra_env:
        env.update(extra_env)
    cmd = [
        sys.executable,
        "-m",
        "backend.ai_meeting",
        "--outdir",
        str(outdir),
    ] + args
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    return outdir


class _MockOllamaHandler(BaseHTTPRequestHandler):
    response_text = "モック応答"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length)
        payload = json.dumps({"message": {"content": self.response_text}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args):  # noqa: A003 - BaseHTTPRequestHandler API
        return


def _start_mock_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    server = ThreadingHTTPServer(("127.0.0.1", port), _MockOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        rec.pop("ts", None)
        records.append(rec)
    return records


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_baseline(name: str) -> dict:
    return json.loads((BASELINE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_cli_chat_mode_default(tmp_path: Path) -> None:
    """既定の短文チャットフローでログと KPI をスナップショット比較する。"""

    outdir = _run_cli(
        tmp_path,
        "chat_mode",
        [
            "--topic",
            "テストE2E",
            "--agents",
            "Alice",
            "Bob",
            "--rounds",
            "2",
            "--precision",
            "6",
            "--backend",
            "ollama",
            "--no-kpi-auto-prompt",
            "--no-kpi-auto-tune",
        ],
    )

    baseline = _load_baseline("chat_mode")

    log_records = _read_jsonl(outdir / "meeting_live.jsonl")
    assert log_records == baseline["meeting_live"]

    kpi = _read_json(outdir / "kpi.json")
    assert kpi == baseline["kpi"]

    result = _read_json(outdir / "meeting_result.json")
    assert result == baseline["meeting_result"]


def test_cli_legacy_flow_no_chat(tmp_path: Path) -> None:
    """旧来フロー（think 無効・チャット無効）のログと KPI を検証する。"""

    outdir = _run_cli(
        tmp_path,
        "legacy_flow",
        [
            "--topic",
            "E2E旧フロー",
            "--agents",
            "Alice",
            "Bob",
            "--rounds",
            "2",
            "--precision",
            "4",
            "--backend",
            "ollama",
            "--no-think-mode",
            "--no-chat-mode",
            "--no-kpi-auto-prompt",
            "--no-kpi-auto-tune",
            "--no-resolve-round",
        ],
    )

    baseline = _load_baseline("legacy_flow")

    log_records = _read_jsonl(outdir / "meeting_live.jsonl")
    assert log_records == baseline["meeting_live"]

    kpi = _read_json(outdir / "kpi.json")
    assert kpi == baseline["kpi"]

    result = _read_json(outdir / "meeting_result.json")
    assert result == baseline["meeting_result"]


def test_cli_accepts_custom_ollama_url(tmp_path: Path) -> None:
    """CLI でカスタムURLを指定してもテストモードで完走できることを確認。"""

    custom_url = "http://127.0.0.1:15432"
    outdir = _run_cli(
        tmp_path,
        "custom_ollama_url",
        [
            "--topic",
            "URLテスト",
            "--agents",
            "Alice",
            "Bob",
            "--rounds",
            "1",
            "--backend",
            "ollama",
            "--ollama-url",
            custom_url,
            "--no-kpi-auto-prompt",
            "--no-kpi-auto-tune",
        ],
        extra_env={"OLLAMA_URL": custom_url},
    )

    assert (outdir / "meeting_live.jsonl").exists()
    assert (outdir / "meeting_result.json").exists()


def test_ollama_backend_custom_port_roundtrip() -> None:
    """モックサーバーに対してカスタムポートで問い合わせできることを検証。"""

    pytest.importorskip("requests")
    server, thread = _start_mock_server()
    try:
        port = server.server_port
        backend = OllamaBackend(model="mock", host=f"http://127.0.0.1:{port}")
        req = LLMRequest(system="test", messages=[{"role": "user", "content": "ping"}])
        text = backend.generate(req)
        assert text == _MockOllamaHandler.response_text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
