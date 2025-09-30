from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal

class LLMRequest(BaseModel):
    system: str
    messages: List[Dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 800

class AgentConfig(BaseModel):
    name: str
    system: str
    style: Optional[str] = None
    reveal_thoughts: bool = False

class MeetingConfig(BaseModel):
    topic: str
    rounds: int = 3
    precision: int = 5
    backend_name: Literal["openai", "ollama", "echo"] = "echo"
    openai_model: str = "gpt-4o-mini"
    ollama_model: str = "qwen2.5:7b"
    stop_diversity: float = 0.15

    def runtime_params(self) -> dict:
        # 例: precisionが高いほど温度を下げる
        t = max(0.0, min(1.0, (10 - self.precision) / 10))
        return {"temperature": t, "self_check_passes": max(1, self.precision // 3)}
