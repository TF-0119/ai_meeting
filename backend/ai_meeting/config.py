# backend/ai_meeting/config.py
import os, json
from argparse import Namespace
from .models import MeetingConfig

def load_config(args: Namespace) -> MeetingConfig:
    cfg = {}
    if getattr(args, "config", None) and os.path.exists(args.config):
        cfg.update(json.load(open(args.config, encoding="utf-8")))
    # 環境変数の例
    if m := os.getenv("OPENAI_MODEL"): cfg["openai_model"] = m
    # CLI引数で上書き
    for k in ["topic", "rounds", "precision", "backend"]:
        v = getattr(args, k, None)
        if v is not None:
            if k == "backend": cfg["backend_name"] = v
            else: cfg[k] = v
    return MeetingConfig(**cfg)
