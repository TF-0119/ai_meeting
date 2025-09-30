#!/usr/bin/env python3
"""`python -m backend.ai_meeting` のリグレッションを検知する比較スクリプト。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = ROOT / "docs" / "samples" / "cli_baseline"


CASES = [
    {
        "name": "chat_mode",
        "args": [
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
    },
    {
        "name": "legacy_flow",
        "args": [
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
    },
]


def _load_baseline(name: str) -> dict:
    path = BASELINE_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        rec.pop("ts", None)
        out.append(rec)
    return out


def _compare(label: str, actual, expected) -> None:
    if actual == expected:
        return
    actual_str = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)
    expected_str = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True)
    diff = ["差分:"]
    diff.append("--- expected")
    diff.append("+++ actual")
    for line in _diff_lines(expected_str.splitlines(), actual_str.splitlines()):
        diff.append(line)
    raise AssertionError(f"{label} がベースラインと一致しません\n" + "\n".join(diff))


def _diff_lines(expected: Iterable[str], actual: Iterable[str]) -> Iterable[str]:
    import difflib

    return difflib.unified_diff(list(expected), list(actual), lineterm="")


def main() -> int:
    baseline_names = {case["name"] for case in CASES}
    missing = [name for name in baseline_names if not (BASELINE_DIR / f"{name}.json").exists()]
    if missing:
        raise FileNotFoundError(f"ベースラインファイルが見つかりません: {missing}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for case in CASES:
            outdir = tmp_dir / case["name"]
            env = os.environ.copy()
            env["AI_MEETING_TEST_MODE"] = "deterministic"
            cmd = [
                sys.executable,
                "-m",
                "backend.ai_meeting",
                "--outdir",
                str(outdir),
            ] + case["args"]
            subprocess.run(cmd, check=True, cwd=ROOT, env=env)

            baseline = _load_baseline(case["name"])
            actual_log = _read_jsonl(outdir / "meeting_live.jsonl")
            _compare(f"{case['name']} meeting_live", actual_log, baseline["meeting_live"])

            actual_result = json.loads((outdir / "meeting_result.json").read_text(encoding="utf-8"))
            _compare(f"{case['name']} meeting_result", actual_result, baseline["meeting_result"])

            actual_kpi = json.loads((outdir / "kpi.json").read_text(encoding="utf-8"))
            _compare(f"{case['name']} kpi", actual_kpi, baseline["kpi"])

    print("CLI ベースライン比較: すべて一致しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
