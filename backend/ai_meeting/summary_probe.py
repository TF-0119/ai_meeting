"""要約プローブ用のシンプルなラッパー。"""
from __future__ import annotations

from typing import Any, Dict, Sequence

from .config import MeetingConfig, Turn
from .cycle_template import extract_cycle_text
from .llm import LLMBackend, LLMRequest


class SummaryProbe:
    """会議中の発言を即席で要約するユーティリティ。"""

    def __init__(self, backend: LLMBackend, config: MeetingConfig):
        self._backend = backend
        self._config = config

    def generate_summary(self, turn: Turn, history: Sequence[Turn]) -> Dict[str, Any]:
        """与えられたターンを要約し、JSON向きの辞書で返す。"""

        turn_number = len(history)
        for idx, item in enumerate(history, start=1):
            if item is turn:
                turn_number = idx
                break

        input_text = extract_cycle_text(turn.content)
        req = LLMRequest(
            system=(
                "あなたは議事要約アシスタント。新しい発言を日本語で要点化し、"
                "意思決定に重要な差分だけを3〜6点で箇条書きに。"
            ),
            messages=[{"role": "user", "content": input_text}],
            temperature=self._config.summary_probe_temperature,
            max_tokens=self._config.summary_probe_max_tokens,
        )
        summary = self._backend.generate(req).strip()

        return {
            "turn_index": turn_number,
            "speaker": turn.speaker,
            "input_text": input_text,
            "summary": summary,
            "parameters": {
                "temperature": self._config.summary_probe_temperature,
                "max_tokens": self._config.summary_probe_max_tokens,
            },
            "meta": dict(turn.meta) if isinstance(turn.meta, dict) else turn.meta,
        }
