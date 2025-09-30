"""テスト向けのユーティリティ（決定論的な LLM スタブなど）。"""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Iterable, List

from .llm import LLMBackend, LLMRequest


class DeterministicLLMBackend(LLMBackend):
    """LLM 呼び出しを完全に決定論的に再現するテスト用バックエンド。"""

    def __init__(self, agent_names: Iterable[str]):
        self.agent_names: List[str] = list(agent_names)
        self._think_calls = 0
        self._judge_calls = 0

    # 正規表現を毎回コンパイルしないように先に用意
    _THOUGHT_RE = re.compile(r"\[自分の思考\]\s*(.+?)(?:\n|$)")

    def generate(self, req: LLMRequest) -> str:  # noqa: D401 - 親クラスの docstring を利用
        system = req.system
        last_msg = req.messages[-1]["content"] if req.messages else ""

        if "内面の思考" in system:
            name = self.agent_names[self._think_calls % len(self.agent_names)]
            base = ["空間を活かす", "用具を工夫する", "得点方法を明確化する"]
            idea = base[self._think_calls % len(base)]
            self._think_calls += 1
            return f"{name}視点: {idea}案を検証する"

        if "中立の審査員" in system:
            names = [
                token.split(":", 1)[0].strip()
                for token in last_msg.splitlines()
                if ":" in token
            ]
            filtered = [n for n in names if n in self.agent_names]
            if not filtered:
                filtered = self.agent_names[:]
            winner = filtered[self._judge_calls % len(filtered)]
            self._judge_calls += 1
            scores = {
                n: {
                    "flow": 0.6,
                    "goal": 0.6,
                    "quality": 0.6,
                    "novelty": 0.6,
                    "action": 0.6,
                    "score": 0.8 if n == winner else 0.6,
                    "rationale": f"{n}案が最も流れに合致",  # 簡潔な理由
                }
                for n in filtered
            }
            return json.dumps({"scores": scores, "winner": winner}, ensure_ascii=False)

        if "非公開メモ" in system:
            match = self._THOUGHT_RE.search(last_msg)
            thought = match.group(1).strip() if match else "要点を整理"
            agent_hint = self.agent_names[(self._judge_calls - 1) % len(self.agent_names)]
            return (
                f"{agent_hint}が決定事項を共有。{thought}。"
                f"担当:{agent_hint} 期限:今週末"
            )

        if "議事要約アシスタント" in system:
            cleaned = last_msg.replace("\n", " / ")
            return f"- 差分: {cleaned}"

        if "自己検証アシスタント" in system:
            return "懸念: 実施手順の具体性を補う"

        if "上記の指摘を反映" in system:
            return "改善案: 手順・安全・得点方法を明記"

        if "モデレーター" in system:
            scores = {n: 0.7 for n in self.agent_names}
            return json.dumps({"scores": scores, "rationale": "全員バランス良好"}, ensure_ascii=False)

        if "議論の編集者" in system:
            return (
                "合意事項:\n"
                "- 空間を活かす新スポーツを実証する\n"
                "- 用具の安全確保と得点管理を両立\n"
                "残課題:\n"
                "- 動作手順の動画化で理解を補強\n"
                "直近アクション:\n"
                "- 担当:Alice が安全テストを実施 (期限:来週)\n"
                "- 担当:Bob がKPI測定を設計 (期限:来月)"
            )

        # 旧フローや残課題フェーズ等の一般プロンプト
        if "会話ルール" in system or "会議ルール" in system:
            name = self._extract_name_from_system(system)
            focus = "安全" if name.endswith("e") else "手順"
            return f"{name}提案: {focus}を決定。担当:{name} 期限:今週"

        # デフォルトのフォールバック
        return "補足案: KPI を継続確認"

    @staticmethod
    def _extract_name_from_system(system: str) -> str:
        for line in system.splitlines():
            if line.strip().startswith("- 名前:"):
                return line.split(":", 1)[1].strip()
        return "Agent"


class NullMetricsLogger:
    """計測をスキップして最小限のダミーファイルを生成するロガー。"""

    def __init__(self, outdir: Path):
        self.outdir = Path(outdir)
        self.csv_path = self.outdir / "metrics.csv"
        if not self.csv_path.exists():
            self.csv_path.write_text(
                "timestamp,cpu_percent,ram_percent,gpu_util,gpu_mem_used_mb,gpu_mem_total_mb,gpu_temp_c,gpu_power_w\n",
                encoding="utf-8",
            )

    def start(self) -> None:
        """本番の MetricsLogger と同じ API を満たすためのダミー実装。"""

    def stop(self) -> None:
        for name in ("metrics_cpu_mem.png", "metrics_gpu.png"):
            path = self.outdir / name
            if not path.exists():
                path.write_bytes(b"")


def is_test_mode() -> bool:
    """環境変数からテストモードかどうかを判定する。"""

    return os.getenv("AI_MEETING_TEST_MODE", "").lower() in {"1", "true", "deterministic"}


def setup_test_environment(agent_names: Iterable[str]):
    """テストモード時に利用するコンポーネント群を返す。"""

    backend = DeterministicLLMBackend(agent_names)
    random.seed(0)
    return backend


__all__ = [
    "DeterministicLLMBackend",
    "NullMetricsLogger",
    "is_test_mode",
    "setup_test_environment",
]

