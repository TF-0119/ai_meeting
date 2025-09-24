from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
from settings import settings

app = FastAPI(title="Local LLM Gateway")

# ローカルのフロントエンドだけ許可（公開しない前提）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatIn(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str | None = None
    system: str | None = None
    temperature: float | None = None
    top_p: float | None = None

class ChatOut(BaseModel):
    response: str
    model: str

@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{settings.OLLAMA_URL}/api/tags")
        r.raise_for_status()
    return {"ok": True}

@app.get("/models")
async def models():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{settings.OLLAMA_URL}/api/tags")
        r.raise_for_status()
        return r.json()

@app.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn):
    payload = {
        "model": body.model or settings.DEFAULT_MODEL,
        "prompt": body.prompt,
        "stream": False,
    }
    if body.system is not None:
        payload["system"] = body.system
    if body.temperature is not None:
        payload.setdefault("options", {})["temperature"] = body.temperature
    if body.top_p is not None:
        payload.setdefault("options", {})["top_p"] = body.top_p

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{settings.OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    return ChatOut(response=data.get("response", ""), model=payload["model"])
