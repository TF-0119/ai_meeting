# backend/ai_meeting/cli.py
import argparse
from pathlib import Path
from .config import load_config
from .backends import OpenAIBackend, OllamaBackend, EchoBackend
from .runner import Runner
from .utils import default_outdir

def main():
    parser = argparse.ArgumentParser(prog="ai_meeting")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--precision", type=int, default=5)
    parser.add_argument("--backend", choices=["openai", "ollama", "echo"], default="echo")
    parser.add_argument("--config", help="JSON config path")
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--agents", nargs="*", help="互換性維持用のダミー引数")
    args = parser.parse_args()

    cfg = load_config(args)
    backend_name = getattr(cfg, "backend_name", args.backend)

    if backend_name == "ollama":
        backend = OllamaBackend(cfg.ollama_model)
    elif backend_name == "openai":
        backend = OpenAIBackend(cfg.openai_model)
    else:
        backend = EchoBackend()

    outdir = Path(args.outdir) if args.outdir else default_outdir(Path("logs"), cfg.topic)
    result = Runner(cfg, backend, outdir).run()
    print("Done:", result)

if __name__ == "__main__":
    main()
