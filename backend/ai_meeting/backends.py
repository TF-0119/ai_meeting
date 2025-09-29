# backend/ai_meeting/backends.py
from typing import Protocol
import requests
from .models import LLMRequest

class LLMBackend(Protocol):
    def generate(self, req: LLMRequest) -> str: ...

class OpenAIBackend:
    def __init__(self, model: str):
        self.model = model
    def generate(self, req: LLMRequest) -> str:
        # TODO: openai>=1.x の Chat Completions に置き換え
        # ここではモック的に返す
        return f"[openai:{self.model}] {req.messages[-1]['content'] if req.messages else req.system}"

class OllamaBackend:
    def __init__(self, model: str, host: str = "http://localhost:11434"):
        self.model, self.host = model, host
    def generate(self, req: LLMRequest) -> str:
        # 最小実装（ストリーム無視の簡易版）
        r = requests.post(f"{self.host}/api/chat", json={
            "model": self.model,
            "messages": req.messages,
            "options": {"temperature": req.temperature}
        }, timeout=60)
        r.raise_for_status()
        data = r.json()
        # 返却形式はOllamaの応答に合わせて要調整
        return data.get("message", {}).get("content", "")
