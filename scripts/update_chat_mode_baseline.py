#!/usr/bin/env python3
from pathlib import Path
import json, sys

OUT_JSONL = Path("out_chat_mode/meeting_live.jsonl")
BASELINE = Path("docs/samples/cli_baseline/chat_mode.json")

if not OUT_JSONL.exists():
    print(f"Error: {OUT_JSONL} not found. Run the CLI first.", file=sys.stderr)
    sys.exit(2)
if not BASELINE.exists():
    print(f"Error: baseline {BASELINE} not found", file=sys.stderr)
    sys.exit(2)

records = []
for line in OUT_JSONL.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    obj = json.loads(line)
    obj.pop("ts", None)   # ここで時刻を捨てる
    records.append(obj)

baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
baseline["meeting_live"] = records
BASELINE.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
print("Baseline updated:", BASELINE)
