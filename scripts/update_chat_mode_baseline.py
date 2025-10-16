#!/usr/bin/env python3
from pathlib import Path
import json
import sys

OUTDIR = Path("out_chat_mode")
OUT_JSONL = OUTDIR / "meeting_live.jsonl"
OUT_KPI = OUTDIR / "kpi.json"
OUT_RESULT = OUTDIR / "meeting_result.json"
BASELINE = Path("docs/samples/cli_baseline/chat_mode.json")

def read_jsonl_without_ts(p: Path):
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        obj.pop("ts", None)  # テストと同じ前処理
        records.append(obj)
    return records

def main():
    missing = [str(p) for p in [OUT_JSONL, OUT_KPI, OUT_RESULT] if not p.exists()]
    if missing:
        print("Error: missing outputs:", ", ".join(missing), file=sys.stderr)
        sys.exit(2)
    if not BASELINE.exists():
        print(f"Error: baseline {BASELINE} not found", file=sys.stderr)
        sys.exit(2)

    meeting_live = read_jsonl_without_ts(OUT_JSONL)
    kpi = json.loads(OUT_KPI.read_text(encoding="utf-8"))
    meeting_result = json.loads(OUT_RESULT.read_text(encoding="utf-8"))

    # 必要ならここで meeting_result の非決定なフィールドを正規化するが、
    # 現状はそのまま採用する
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline["meeting_live"] = meeting_live
    baseline["kpi"] = kpi
    baseline["meeting_result"] = meeting_result

    BASELINE.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Baseline updated:", BASELINE)

if __name__ == "__main__":
    main()
