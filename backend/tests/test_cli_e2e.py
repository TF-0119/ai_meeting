"""`python -m backend.ai_meeting` の主要オプションを網羅するエンドツーエンドテスト。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "docs" / "samples" / "cli_baseline"


def _run_cli(tmp_path: Path, name: str, args: list[str]) -> Path:
    outdir = tmp_path / name
    env = os.environ.copy()
    env["AI_MEETING_TEST_MODE"] = "deterministic"
    cmd = [
        sys.executable,
        "-m",
        "backend.ai_meeting",
        "--outdir",
        str(outdir),
    ] + args
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    return outdir


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
