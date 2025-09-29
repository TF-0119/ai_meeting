# backend/ai_meeting/api.py
from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path
from .models import MeetingConfig
from .runner import Runner
from .backends import OpenAIBackend, OllamaBackend
from .utils import default_outdir

app = FastAPI()

class StartReq(BaseModel):
    topic: str
    rounds: int = 3
    precision: int = 5
    backend_name: str = "ollama"

@app.post("/start")
def start(req: StartReq):
    cfg = MeetingConfig(**req.model_dump())
    backend = OllamaBackend(cfg.ollama_model) if cfg.backend_name=="ollama" else OpenAIBackend(cfg.openai_model)
    outdir = default_outdir(Path("logs"), cfg.topic)
    result = Runner(cfg, backend, outdir).run()
    return result
