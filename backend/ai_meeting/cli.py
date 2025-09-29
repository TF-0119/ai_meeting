# backend/ai_meeting/cli.py
import argparse
from pathlib import Path
from .config import load_config
from .backends import OpenAIBackend, OllamaBackend
from .runner import Runner
from .utils import default_outdir

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--precision", type=int, default=5)
    ap.add_argument("--backend", choices=["openai","ollama"], default="ollama")
    ap.add_argument("--config", help="JSON config path")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    cfg = load_config(args)
    backend = OllamaBackend(cfg.ollama_model) if cfg.backend_name=="ollama" else OpenAIBackend(cfg.openai_model)
    outdir = Path(args.outdir) if args.outdir else default_outdir(Path("logs"), cfg.topic)

    result = Runner(cfg, backend, outdir).run()
    print("Done:", result)

if __name__ == "__main__":
    main()
