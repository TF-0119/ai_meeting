# backend/ai_meeting/live_log.py
from pathlib import Path
import json, datetime as dt

class LiveLog:
    def __init__(self, outdir: Path):
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "meeting_live.jsonl").touch(exist_ok=True)

    def event(self, payload: dict, fname="meeting_live.jsonl"):
        rec = {"ts": dt.datetime.utcnow().isoformat()+"Z", **payload}
        with (self.outdir / fname).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
