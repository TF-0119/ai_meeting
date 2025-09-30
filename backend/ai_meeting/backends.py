# backend/ai_meeting/backends.py
from typing import Protocol

try:
    import requests
except ModuleNotFoundError:  # requests が未インストールでも --help が動作するように遅延対応
    requests = None  # type: ignore[assignment]

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
        self.model, self.host = model, host  # [file:1]

    def generate(self, req: LLMRequest) -> str:
        import json  # [file:1]

        payload = {
            "model": self.model,
            "messages": req.messages,
            "options": {"temperature": req.temperature},
            "stream": False,  # 単一JSONに固定 [file:1]
        }  # [file:1]

        if requests is None:  # pragma: no cover - 実行時に明示的に通知する
            raise RuntimeError("OllamaBackend を利用するには requests をインストールしてください。")

        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
        r.raise_for_status()  # [file:1]

        try:
            data = r.json()
        except Exception:
            # 念のためストリームで戻った場合に備えてNDJSONを行単位で読む [file:1]
            content = ""
            for line in r.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                content = (
                    obj.get("message", {}).get("content")
                    or obj.get("response")
                    or content
                )
                if obj.get("done"):
                    break
            return content or ""  # [file:1]

        # 非ストリームの代表的な2パターンに対応 [file:1]
        content = (
            data.get("message", {}).get("content")
            or data.get("response")
            or ""
        )
        return content  # [file:1]


class EchoBackend:
    def __init__(self, tag: str = "echo"):
        self.tag = tag

    def generate(self, req: LLMRequest) -> str:
        """渡された会話履歴を単純に整形して返すエコーバックエンド。"""

        parts: list[str] = []

        if req.system:
            parts.append(f"system: {req.system}")

        for message in req.messages:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            parts.append(f"{role}: {content}")

        joined = " | ".join(parts)
        if not joined:
            return f"[{self.tag}]"

        return f"[{self.tag}] {joined}"
