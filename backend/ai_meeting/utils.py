# backend/ai_meeting/utils.py
from pathlib import Path
import re

def safe_dirname(topic: str) -> str:
    name = re.sub(r"[^\w\-一-龠ぁ-んァ-ヴー]", "_", topic.strip())
    return name[:60] or "run"

def default_outdir(base: Path, topic: str) -> Path:
    return base / safe_dirname(topic)
