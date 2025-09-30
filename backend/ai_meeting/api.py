# backend/ai_meeting/api.py
from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path

from .models import MeetingConfig
from .runner import Runner
from .backends import OpenAIBackend, OllamaBackend, EchoBackend
from .utils import default_outdir

app = FastAPI(title="ai_meeting API")

class StartReq(BaseModel):
    topic: str
    rounds: int = 3
    precision: int = 5
    backend_name: str = "echo"  # echo を既定に

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/start")
def start(req: StartReq):
    cfg = MeetingConfig(**req.model_dump())
    if cfg.backend_name == "ollama":
        backend = OllamaBackend(cfg.ollama_model)
    elif cfg.backend_name == "openai":
        backend = OpenAIBackend(cfg.openai_model)
    else:
        backend = EchoBackend()
    outdir = default_outdir(Path("logs"), cfg.topic)
    result = Runner(cfg, backend, outdir).run()
    return result