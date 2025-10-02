"""LLM バックエンドの実装。"""
from __future__ import annotations

import os
import typing
from typing import Iterable, Optional
from urllib.parse import urlparse
import ipaddress

from pydantic import BaseModel


class LLMRequest(BaseModel):
    """LLM バックエンドへ渡す共通リクエスト。"""

    system: str
    messages: list[dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 800


class LLMBackend:
    """LLM バックエンドのインターフェース。"""

    def generate(self, req: LLMRequest) -> str:
        raise NotImplementedError


class OpenAIBackend(LLMBackend):
    """OpenAI API を利用するバックエンド。"""

    def __init__(self, model: Optional[str] = None):
        try:
            from openai import OpenAI

            self.client = OpenAI()
        except ImportError as e:  # pragma: no cover - 実行時依存
            raise RuntimeError(
                "OpenAI backend requires 'openai' package. Please `pip install openai` or use `--backend ollama`."
            ) from e
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def generate(self, req: LLMRequest) -> str:
        """Chat Completions API を利用して応答を生成する。"""

        messages: list[dict[str, str]] = [{"role": "system", "content": req.system}] + req.messages

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=typing.cast(Iterable[typing.Any], messages),
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()


class OllamaBackend(LLMBackend):
    """ローカルの Ollama API を利用するバックエンド。"""

    def __init__(self, model: str = "gpt-oss:20b", host: str = "http://127.0.0.1:11434"):
        import requests

        self.requests = requests
        self.model = model
        parsed = urlparse(host)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("Ollama host must be HTTP/HTTPS URL.")
        if not parsed.hostname:
            raise RuntimeError("Ollama host must include hostname.")

        hostname = parsed.hostname
        if not self._is_local_hostname(hostname):
            raise RuntimeError("Ollama host must point to a local address.")

        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80

        self.host = f"{parsed.scheme}://{hostname}:{port}"

    @staticmethod
    def _is_local_hostname(hostname: str) -> bool:
        """ローカルアドレスかどうかを判定する。"""

        if hostname == "localhost":
            return True
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return ip.is_loopback or ip.is_private

    def generate(self, req: LLMRequest) -> str:
        """Ollama のチャット API を利用して応答を生成する。"""

        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": req.system}] + req.messages,
            "options": {"temperature": req.temperature},
            "stream": False,
        }
        r = self.requests.post(url, json=payload, timeout=600)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "").strip()


__all__ = [
    "LLMBackend",
    "LLMRequest",
    "OllamaBackend",
    "OpenAIBackend",
]
