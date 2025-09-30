# backend/ai_meeting/runner.py
from pathlib import Path
from typing import List, Dict
from .models import MeetingConfig, LLMRequest
from .live_log import LiveLog
from . import kpi
from importlib.resources import files
try:
    BASE_PROMPT = (files("backend.ai_meeting.prompts") / "base.md").read_text(encoding="utf-8")
except Exception:
    BASE_PROMPT = "You are a helpful meeting agent for: {topic}"


class Runner:
    def __init__(self, cfg: MeetingConfig, backend, outdir: Path):
        self.cfg, self.backend = cfg, backend
        self.log = LiveLog(outdir)

    def run(self) -> Dict:
        params = self.cfg.runtime_params()
        # 最初に user の“種”を入れて会議を始める
        history: List[Dict[str, str]] = [
            {"role": "user", "content": f"議題: {self.cfg.topic}。まず要点を一言でまとめて。"}
        ]
        self.log.event({"type": "start", "topic": self.cfg.topic, "params": params})

        for r in range(self.cfg.rounds):
            # 1) プロンプト（最低限）
            system = BASE_PROMPT.format(topic=self.cfg.topic)
            req = LLMRequest(system=system, messages=history, temperature=params["temperature"])
            # 2) 生成
            reply = self.backend.generate(req)
            history.append({"role": "assistant", "content": reply})
            self.log.event({"type": "round", "round": r+1, "reply": reply})
            # 次ラウンド用の user 追い投げ（単純な継続プロンプト）
            history.append({"role": "user", "content": "続けて、具体策を1つだけ追加して。"})

            # 3) KPIで早期停止
            texts = [m["content"] for m in history if m["role"] == "assistant"]
            diversity = kpi.evaluate_diversity(texts)
            self.log.event({"type": "kpi", "round": r+1, "diversity": diversity}, "kpi.jsonl")
            if diversity < self.cfg.stop_diversity:
                self.log.event({"type": "stop", "reason": "low_diversity", "value": diversity})
                break

        result = {"rounds_executed": len([m for m in history if m["role"]=="assistant"]),
                  "last_reply": history[-1]["content"] if history else ""}
        self.log.event({"type": "done", **result})
        return result
