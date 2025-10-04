"""`Meeting` クラスの本実装。"""
from __future__ import annotations

import json
import math
import os
import random
import re
import textwrap
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .config import AgentConfig, MeetingConfig, Turn
from .controllers import KPIFeedback, Monitor, PendingTracker, PhaseEvent, ShockEngine
from .evaluation import KPIEvaluator
from .llm import LLMRequest, OllamaBackend, OpenAIBackend
from .logging import LiveLogWriter
from .metrics import MetricsLogger
from .summary_probe import SummaryProbe
from .testing import NullMetricsLogger, is_test_mode, setup_test_environment
from .utils import banner, clamp, safe_console_print
from .phase import PhaseState


@dataclass(frozen=True)
class PersonalityTemplate:
    """エージェントの個性テンプレートを表現するデータ構造。"""

    name: str
    description: str
    thinking_guidance: str
    speaking_guidance: str

    def to_memory_entry(self) -> str:
        """プロンプト用の覚書形式に整えたテキストを返す。"""

        return f"個性プロファイル({self.name}): {self.description}"


PERSONALITY_LIBRARY: Tuple[PersonalityTemplate, ...] = (
    PersonalityTemplate(
        name="ASSERTIVE",
        description="意思決定を急ぎ、明確な行動を求める推進役。",
        thinking_guidance="思考では結論から逆算し、次に押し切るべき論点を即断で整理すること。",
        speaking_guidance="発言では断定調でリーダーシップを示し、行動と担当を端的に指示すること。",
    ),
    PersonalityTemplate(
        name="ANALYTICAL",
        description="データと根拠を重視し、比較検証で合意を導く分析役。",
        thinking_guidance="思考では選択肢を比較し、欠けている根拠や検証手段を必ず洗い出すこと。",
        speaking_guidance="発言では根拠→含意→提案の順で整理し、仮説や指標を具体的に示すこと。",
    ),
    PersonalityTemplate(
        name="EMPATHIC",
        description="相手の感情と懸念をすくい上げ、協調的な合意形成を促す支援役。",
        thinking_guidance="思考では関係者の感情や懸念を推測し、安心感を与える応答を準備すること。",
        speaking_guidance="発言では共感を一言添えた上で、負担を分散する具体的な支援策を提案すること。",
    ),
)

PERSONALITY_TEMPLATES: Dict[str, PersonalityTemplate] = {
    template.name: template for template in PERSONALITY_LIBRARY
}


@dataclass(frozen=True)
class MemoryEntry:
    """エージェントが保持する覚書1件分の構造。"""

    text: str
    category: str
    priority: float
    created_at: float


# 覚書の分類ラベルを判別するためのエイリアス定義
MEMORY_CATEGORY_ALIASES: Dict[str, str] = {
    "決定": "decision",
    "決定事項": "decision",
    "合意事項": "decision",
    "todo": "todo",
    "to-do": "todo",
    "次": "todo",
    "アクション": "todo",
    "対応": "todo",
    "残課題": "unresolved",
    "課題": "unresolved",
    "未解決": "unresolved",
    "懸念": "risk",
    "リスク": "risk",
    "注意": "risk",
    "警戒": "risk",
    "進捗": "progress",
    "情報": "info",
    "メモ": "note",
    "memo": "note",
}


# 覚書カテゴリーごとの既定優先度
MEMORY_CATEGORY_PRIORITY: Dict[str, float] = {
    "decision": 1.0,
    "unresolved": 0.9,
    "todo": 0.88,
    "risk": 0.85,
    "progress": 0.75,
    "info": 0.6,
    "note": 0.5,
}


def _resolve_personality_seed(cfg: MeetingConfig, test_mode: bool) -> Optional[int]:
    """個性テンプレート抽選用の乱数シードを決定する。"""

    if isinstance(getattr(cfg, "personality_seed", None), int):
        return cfg.personality_seed  # type: ignore[attr-defined]

    env_value = os.getenv("AI_MEETING_TEST_MODE", "").strip()
    if not env_value:
        return None

    normalized = env_value.lower()
    if normalized in {"1", "true", "deterministic"}:
        return 0

    match = re.search(r"(-?\d+)", normalized)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return 0 if test_mode else None


def _select_personality_templates(
    agent_count: int, rng: random.Random
) -> List[PersonalityTemplate]:
    """必要な人数分の個性テンプレートを乱択で取得する。"""

    if agent_count <= 0 or not PERSONALITY_LIBRARY:
        return []

    pool = list(PERSONALITY_LIBRARY)
    rng.shuffle(pool)
    selected: List[PersonalityTemplate] = []

    while len(selected) < agent_count:
        remaining = agent_count - len(selected)
        if remaining >= len(pool):
            selected.extend(pool)
            pool = list(PERSONALITY_LIBRARY)
            rng.shuffle(pool)
        else:
            selected.extend(pool[:remaining])

    return selected


class Meeting:
    """会議の進行を管理するメインクラス。"""

    def __init__(self, cfg: MeetingConfig):
        self.cfg = cfg
        self.history: List[Turn] = []
        self._conversation_summary_points: List[str] = []
        self._memory_clock: float = 0.0
        self._agent_memory: Dict[str, List[MemoryEntry]] = {}
        for agent in self.cfg.agents:
            entries: List[MemoryEntry] = []
            for memo in agent.memory:
                if not isinstance(memo, str):
                    continue
                clean = memo.strip()
                if not clean:
                    continue
                category = self._infer_memory_category(clean)
                entries.append(self._create_memory_entry(clean, category=category))
            self._agent_memory[agent.name] = entries
        self._agent_personality_memory: Dict[str, str] = {}
        self._personality_profiles: Dict[str, PersonalityTemplate] = {}
        # backend
        self._test_mode = is_test_mode()
        if self._test_mode:
            self.backend = setup_test_environment([a.name for a in self.cfg.agents])
        elif cfg.backend_name == "openai":
            self.backend = OpenAIBackend(model=cfg.openai_model)
        else:
            model = cfg.ollama_model or os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
            host = cfg.ollama_url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
            self.backend = OllamaBackend(model=model, host=host)
        rp = self.cfg.runtime_params()
        self.temperature = rp["temperature"]
        self.critique_passes = rp["critique_passes"]
        self._summary_probe = SummaryProbe(self.backend, self.cfg)
        self._pending = PendingTracker()  # 残課題トラッカー
        self.logger = LiveLogWriter(
            self.cfg.topic,
            outdir=self.cfg.outdir,
            ui_minimal=self.cfg.ui_minimal,
            summary_probe_filename=self.cfg.summary_probe_filename,
            enable_markdown=self.cfg.log_markdown_enabled,
            enable_jsonl=self.cfg.log_jsonl_enabled,
        )
        self.equilibrium_enabled = self.cfg.equilibrium
        self._monitor = Monitor(self.cfg) if self.cfg.monitor else None
        self._phase_id = 0
        self._unresolved_history: List[int] = []
        self._phases: List[PhaseState] = []
        self._legacy_round_offset: int = 0
        self._phase_state: Optional[PhaseState] = None
        self._phase_state = self._begin_phase(
            PhaseEvent(
                phase_id=0,
                start_turn=1,
                end_turn=0,
                status="confirmed",
                confidence=1.0,
                summary="フェーズ0（初期化）",
                kind="discussion",
            )
        )
        # Step5: ショック管理を有効化
        self._shock_engine = ShockEngine(self.cfg) if self.cfg.shock != "off" else None
        self._shock_hint: Optional[str] = None
        self._shock_ttl: int = 0
        # Step7: KPIフィードバック
        self._ctrl = KPIFeedback(self.cfg)
        self._ctrl_hint: Optional[str] = None
        self._ctrl_ttl: int = 0

        # メトリクスロガー開始
        self._last_spoke: Dict[str, int] = {}  # speaker_name -> last turn index (global)
        if self._test_mode:
            self.metrics = NullMetricsLogger(self.logger.dir)
        else:
            self.metrics = MetricsLogger(self.logger.dir, interval=1.0)
        self.metrics.start()

    def _begin_phase(self, event: PhaseEvent) -> PhaseState:
        """フェーズを開始し、現在の状態として保持する。"""

        phase_id = event.phase_id if event.phase_id is not None else self._phase_id
        current = getattr(self, "_phase_state", None)
        kind = event.kind or (current.kind if current else "discussion")
        state = PhaseState(
            id=phase_id,
            start_turn=event.start_turn,
            status=event.status,
            kind=kind,
            turn_limit=self.cfg.get_phase_turn_limit(kind),
            legacy_round_base=self._legacy_round_offset,
        )
        self._phase_state = state
        self._phase_id = phase_id
        return state

    def _end_phase(self, event: PhaseEvent) -> PhaseState:
        """現在のフェーズを終了し、履歴へ格納する。"""

        if not self._phase_state:
            raise RuntimeError("フェーズ状態が初期化されていません。")
        phase_id = event.phase_id if event.phase_id is not None else self._phase_state.id
        closed_state = PhaseState(
            id=phase_id,
            start_turn=self._phase_state.start_turn,
            turn_indices=list(self._phase_state.turn_indices),
            unresolved_counts=list(self._phase_state.unresolved_counts),
            status=event.status,
            turn_limit=self._phase_state.turn_limit,
            turn_count=self._phase_state.turn_count,
            kind=self._phase_state.kind,
            legacy_round_base=self._phase_state.legacy_round_base,
        )
        self._phase_state = None
        self._phase_id = phase_id
        self._phases.append(closed_state)
        self._legacy_round_offset = closed_state.legacy_round_base + closed_state.turn_count
        return closed_state

    def _phase_payload(self, event: PhaseEvent, state: Optional[PhaseState]) -> Dict:
        """フェーズイベントのログ用ペイロードを生成する。"""

        payload: Dict = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": asdict(event),
        }
        if state:
            payload["phase"] = self._phase_state_to_dict(state)
        return payload

    def _phase_round_index(self, state: PhaseState, phase_turn: int) -> int:
        """フェーズ情報から互換ラウンド番号を算出する。"""

        return state.legacy_round_base + phase_turn

    def _phase_state_to_dict(self, state: PhaseState) -> Dict[str, Any]:
        """PhaseState を辞書化し、目標情報を付加する。"""

        data = asdict(state)
        goal = self.cfg.get_phase_goal(state.kind)
        if goal:
            data["goal"] = goal
        return data

    def _serialize_phases(self) -> List[Dict[str, Any]]:
        """meeting_result.json 用にフェーズ進行のスナップショットを整形する。"""

        records = [self._phase_state_to_dict(p) for p in self._phases]
        if self._phase_state:
            records.append(self._phase_state_to_dict(self._phase_state))
        return records

    def _reset_phase_controls(self) -> None:
        """フェーズ切り替え時にショック/KPI制御をリセットする。"""

        if self._shock_engine:
            self._shock_hint = None
            self._shock_ttl = 0
        self._ctrl_hint = None
        self._ctrl_ttl = 0
        self._ctrl.reset()

    def _handle_phase_event(self, event: PhaseEvent) -> None:
        """監視AIのフェーズイベントを処理する。"""

        state = self._phase_state
        if state:
            if event.phase_id is None:
                event.phase_id = state.id
            if event.kind is None:
                event.kind = state.kind
            state.start_turn = min(state.start_turn, event.start_turn)
        if event.status == "candidate":
            if state:
                state.status = "candidate"
            self.logger.append_phase(self._phase_payload(event, state))
            return
        if event.status == "confirmed":
            if state:
                state.status = "confirmed"
            if self._shock_engine:
                if self._shock_engine.mode == "explore":
                    self.cfg.select_temp = clamp(self.cfg.select_temp + 0.2, 0.7, 1.5)
                    self.cfg.sim_penalty = clamp(self.cfg.sim_penalty - 0.1, 0.0, 0.6)
                    self.cfg.cooldown = clamp(self.cfg.cooldown - 0.05, 0.0, 0.35)
                elif self._shock_engine.mode == "exploit":
                    self.cfg.select_temp = clamp(self.cfg.select_temp - 0.2, 0.5, 1.5)
                    self.cfg.sim_penalty = clamp(self.cfg.sim_penalty + 0.1, 0.0, 0.6)
                    self.cfg.cooldown = clamp(self.cfg.cooldown + 0.05, 0.0, 0.35)
                event.shock_used = self._shock_engine.mode
            self.logger.append_phase(self._phase_payload(event, state))
            return
        if event.status == "closed":
            closed_state = self._end_phase(event)
            self.logger.append_phase(self._phase_payload(event, closed_state))
            if self.cfg.max_phases and len(self._phases) >= self.cfg.max_phases:
                return
            next_kind = event.kind or (closed_state.kind if closed_state else "discussion")
            next_event = PhaseEvent(
                phase_id=(closed_state.id + 1) if closed_state else (self._phase_id + 1),
                start_turn=len(self.history) + 1,
                end_turn=len(self.history),
                status="open",
                confidence=0.0,
                summary="",
                kind=next_kind,
            )
            new_state = self._begin_phase(next_event)
            self._reset_phase_controls()
            self.logger.append_phase(self._phase_payload(next_event, new_state))

    # === 思考→審査→当選発言 用の補助 ===
    def _recent_context(self, n: int) -> str:
        if not self.history:
            return ""
        tail = self.history[-max(1, n):]
        return " / ".join(f"{t.speaker}:{t.content}" for t in tail)

    def _next_memory_timestamp(self) -> float:
        """覚書の生成順序を追跡するための単調増加タイムスタンプを返す。"""

        self._memory_clock += 1.0
        return self._memory_clock

    def _infer_memory_category(self, text: str) -> str:
        """覚書テキストから分類ラベルを推定する。"""

        token = ""
        match = re.match(r"^[\[{(\s]*([^:：\]\)}]+)", text)
        if match:
            token = match.group(1)
        if not token:
            parts = re.split(r"[:：]", text, maxsplit=1)
            if len(parts) > 1:
                token = parts[0]
        normalized = token.strip().strip("[]{}()\u3000 ").lower()
        if not normalized:
            return "note"
        return MEMORY_CATEGORY_ALIASES.get(normalized, "note")

    def _score_memory_priority(self, category: str, text: str) -> float:
        """覚書の優先度スコアを算出する。"""

        base = MEMORY_CATEGORY_PRIORITY.get(category, MEMORY_CATEGORY_PRIORITY["note"])
        urgent_keywords = ("期限", "締切", "緊急", "critical", "重要")
        if any(keyword in text for keyword in urgent_keywords):
            base += 0.05
        return clamp(base, 0.0, 1.0)

    def _create_memory_entry(
        self, text: str, *, category: Optional[str] = None, priority: Optional[float] = None
    ) -> MemoryEntry:
        """覚書テキストから `MemoryEntry` を生成する。"""

        normalized = text.strip()
        inferred_category = category or self._infer_memory_category(normalized)
        score = priority if priority is not None else self._score_memory_priority(inferred_category, normalized)
        return MemoryEntry(text=normalized, category=inferred_category, priority=score, created_at=self._next_memory_timestamp())

    def _agent_memory_snapshot(self, agent_name: str) -> List[str]:
        """エージェントの覚書から直近分を取得する。"""

        entries: List[str] = []
        personality_note = self._agent_personality_memory.get(agent_name)
        if personality_note:
            entries.append(personality_note)
        memory_entries = list(self._agent_memory.get(agent_name, []))
        window = getattr(self.cfg, "agent_memory_window", 0)
        if isinstance(window, int) and window > 0:
            memory_entries = memory_entries[-window:]
        entries.extend(entry.text for entry in memory_entries)
        return entries

    def _format_agent_memory(self, agent_name: str) -> Optional[str]:
        """プロンプトへ挿入する覚書テキストを生成する。"""

        memory = self._agent_memory_snapshot(agent_name)
        if not memory:
            return None
        bullets = "\n".join(f"- {item}" for item in memory)
        return f"最近の覚書:\n{bullets}"

    def _record_agent_memory(
        self,
        agent_names: Any,
        summary_payload: Dict[str, Any],
        *,
        speaker_name: Optional[str] = None,
    ) -> None:
        """ターン要約からエージェントの覚書を更新する。"""

        if not self.history:
            return

        if isinstance(agent_names, str):
            targets = [agent_names]
        else:
            try:
                targets = [name for name in agent_names]
            except TypeError:
                targets = [agent_names]

        if not targets:
            return

        turn = self.history[-1]
        base_entries: List[str] = []
        summary_text = ""
        if isinstance(summary_payload, dict):
            raw_summary = summary_payload.get("summary")
            if raw_summary is None or isinstance(raw_summary, str):
                summary_text = raw_summary or ""
            else:
                self.logger.append_warning(
                    "agent_memory_invalid_summary_text",
                    context={
                        "speaker": getattr(turn, "speaker", ""),
                        "received_type": type(raw_summary).__name__,
                    },
                )
        elif summary_payload is not None:
            self.logger.append_warning(
                "agent_memory_invalid_summary_payload",
                context={
                    "speaker": getattr(turn, "speaker", ""),
                    "received_type": type(summary_payload).__name__,
                },
            )
        if summary_text:
            seen_base: set[str] = set()
            for line in summary_text.splitlines():
                clean = re.sub(r"^[\s\-\*\u30fb・•\d\.\)]{0,3}", "", line).strip()
                if not clean or clean in seen_base:
                    continue
                base_entries.append(clean)
                seen_base.add(clean)
        fallback = ""
        if isinstance(turn.content, str):
            fallback = turn.content.strip()
        elif turn.content is not None:
            self.logger.append_warning(
                "agent_memory_invalid_turn_content",
                context={
                    "speaker": getattr(turn, "speaker", ""),
                    "received_type": type(turn.content).__name__,
                },
            )
        if not base_entries and fallback:
            base_entries.append(fallback)

        if not base_entries:
            return

        limit = getattr(self.cfg, "agent_memory_limit", 0)
        for name in targets:
            if not isinstance(name, str):
                continue
            existing = self._agent_memory.setdefault(name, [])
            seen_texts = {entry.text for entry in existing}
            appended = False
            for entry in base_entries:
                category = self._infer_memory_category(entry)
                if speaker_name and name != speaker_name:
                    item = f"{speaker_name}の発言: {entry}"
                else:
                    item = entry
                if item in seen_texts:
                    continue
                new_entry = self._create_memory_entry(item, category=category)
                existing.append(new_entry)
                seen_texts.add(item)
                appended = True
            if not appended:
                continue
            if isinstance(limit, int) and limit > 0 and len(existing) > limit:
                overflow = len(existing) - limit
                removal_order = sorted(
                    range(len(existing)),
                    key=lambda idx: (existing[idx].priority, existing[idx].created_at),
                )
                remove_indices = set(removal_order[:overflow])
                trimmed = [
                    entry for idx, entry in enumerate(existing) if idx not in remove_indices
                ]
                existing = trimmed
            self._agent_memory[name] = list(existing)

    def _assign_personalities(self) -> None:
        """各エージェントへ個性テンプレートを割り当てる。"""

        if self._personality_profiles:
            return
        if not PERSONALITY_LIBRARY:
            return

        rng = random.Random()
        seed = _resolve_personality_seed(self.cfg, self._test_mode)
        if seed is not None:
            rng.seed(seed)
        else:
            rng.seed()

        templates = _select_personality_templates(len(self.cfg.agents), rng)

        for agent, template in zip(self.cfg.agents, templates):
            self._personality_profiles[agent.name] = template
            profile_text = template.to_memory_entry()
            self._agent_personality_memory[agent.name] = profile_text

    def _think(self, agent: AgentConfig, last_summary: str) -> str:
        sys = (
            "あなたは会議参加者です。これは『内面の思考』であり出力は他者に公開されません。"
            "短く（1〜2文、日本語）、次の一手として有効な案だけを書いてください。"
            "見出し・箇条書き・メタ言及は禁止。"
        )
        profile = self._personality_profiles.get(agent.name)
        if profile:
            sys += (
                f" あなたの個性は『{profile.name}』。{profile.thinking_guidance}"
            )
        last_turn = self.history[-1] if self.history else None
        if last_turn:
            # 直前発言の要点を1行にまとめる（思考を相手指向に寄せるため）。
            normalized = " ".join(last_turn.content.strip().split())
            if len(normalized) > 80:
                normalized = normalized[:80] + "…"
            last_turn_detail = (
                f"{last_turn.speaker}: {normalized}"
                if normalized
                else f"{last_turn.speaker}: (内容なし)"
            )
        else:
            last_turn_detail = "直前発言なし"
        recent = self._recent_context(self.cfg.chat_window)
        user_lines = [
            f"Topic: {self.cfg.topic}",
            f"last_turn_detail: {last_turn_detail}",
            f"直近: {recent}" if recent else "直近: (発言なし)",
            f"要約: {last_summary}" if last_summary else "要約: (未設定)",
            "",
            "前回の発言者（名前）への応答方針を1文でまとめ、必要なら次の質問を用意する。",
            "次の一手（思考のみ）:",
        ]
        if profile:
            user_lines.insert(1, f"個性プロファイル: {profile.description}")
        memory_text = self._format_agent_memory(agent.name)
        if memory_text:
            user_lines.insert(1, memory_text)
        user = "\n".join(user_lines)
        req = LLMRequest(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=min(0.9, self.temperature + 0.1),
            max_tokens=120,
        )
        return self._enforce_chat_constraints(self.backend.generate(req)).strip()


    def _judge_thoughts(
        self,
        bundle: Dict[str, str],
        last_summary: str,
        flow_summary: str,
    ) -> Dict:
        names = list(bundle.keys())
        if not names:
            return {"scores": {}, "winner": ""}

        include_topic = bool(getattr(self.cfg, "think_judge_include_topic", True))
        include_recent = bool(getattr(self.cfg, "think_judge_include_recent", True))
        include_recent_summary = bool(
            getattr(self.cfg, "think_judge_include_recent_summary", True)
        )
        include_flow_summary = bool(
            getattr(self.cfg, "think_judge_include_flow_summary", True)
        )

        if getattr(self, "_test_mode", False):
            include_topic = include_recent = include_recent_summary = include_flow_summary = True

        recent_text = ""
        if include_recent:
            recent = self._recent_context(self.cfg.chat_window)
            recent_text = recent if recent else "(発言なし)"

        last_summary_text = ""
        if include_recent_summary:
            last_summary_text = last_summary if last_summary else "(未設定)"

        flow_summary_text = ""
        if include_flow_summary:
            flow_summary_text = flow_summary.strip() if flow_summary else "(未設定)"

        example_candidates = names[:2] if names else ["NAME"]
        example_lines = []
        for candidate in example_candidates:
            example_lines.append(
                f'"{candidate}": {{"flow": 0.0, "goal": 0.0, "quality": 0.0, '
                f'"novelty": 0.0, "action": 0.0, "score": 0.0, "rationale": "短文"}}'
            )
        example_scores_block = ",\n                ".join(example_lines)
        example_json = textwrap.dedent(
            f"""
            出力JSON例:
            {{
              "scores": {{
                {example_scores_block}
              }},
              "winner": "{names[0]}"
            }}
            """
        ).strip()
        sys = "\n".join(
            [
                "あなたは中立の審査員です。各候補の『流れ適合/目的適合/質/新規性/実行性』を0〜1で採点し、総合scoreを算出して勝者を1名だけ選びます。",
                "scores にはすべての候補名を含め、flow/goal/quality/novelty/action/score は 0〜1 の数値、rationale は60文字以内の短文にしてください。",
                "出力はJSONのみとし、勝者は1名です。",
                "",
                example_json,
            ]
        )



        sections = []
        context_lines = []
        if include_topic:
            context_lines.append(f"Topic: {self.cfg.topic}")
        if include_recent and recent_text:
            context_lines.append(f"直近発言: {recent_text}")
        if include_recent_summary and last_summary_text:
            context_lines.append(f"直近要約: {last_summary_text}")
        if include_flow_summary and flow_summary_text:
            context_lines.append("会話の流れサマリー:")
            context_lines.append(flow_summary_text)
        if context_lines:
            sections.append("\n".join(context_lines))

        candidate_lines = ["候補:"]
        candidate_lines.extend(f"{name}: {txt}" for name, txt in bundle.items())
        sections.append("\n".join(candidate_lines))

        user = "\n\n".join(sections)
        req = LLMRequest(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=0.15,
            max_tokens=600,
        )
        raw = self.backend.generate(req).strip()
        j = self._try_parse_json(raw)
        # フォールバック：最低限 score だけ用意
        if not isinstance(j, dict):
            j = {}
        scores = j.get("scores")
        if not isinstance(scores, dict):
            scores = {}

        def _normalize_name(value: object) -> str:
            return str(value).strip().casefold() if value is not None else ""

        name_lookup = {_normalize_name(n): n for n in names}

        normalized_scores = {}
        for key, rec in scores.items():
            canonical = name_lookup.get(_normalize_name(key))
            if canonical and canonical not in normalized_scores:
                normalized_scores[canonical] = rec

        # 欠損を埋める＆scoreを正規化
        out_scores = {}
        for n in names:
            rec = normalized_scores.get(n, {})
            sc = float(rec.get("score", 0.0)) if isinstance(rec, dict) else 0.0
            out_scores[n] = {
                "flow": float(rec.get("flow", 0.0)) if isinstance(rec, dict) else 0.0,
                "goal": float(rec.get("goal", 0.0)) if isinstance(rec, dict) else 0.0,
                "quality": float(rec.get("quality", 0.0)) if isinstance(rec, dict) else 0.0,
                "novelty": float(rec.get("novelty", 0.0)) if isinstance(rec, dict) else 0.0,
                "action": float(rec.get("action", 0.0)) if isinstance(rec, dict) else 0.0,
                "score": max(0.0, min(1.0, sc)),
                "rationale": (rec.get("rationale") or "" if isinstance(rec, dict) else "")[:60],
            }
        win_raw = j.get("winner")
        win_norm = _normalize_name(win_raw)
        requested_winner = name_lookup.get(win_norm)
        if requested_winner:
            win = requested_winner
        elif out_scores:
            top_score = max(v["score"] for v in out_scores.values())
            top_candidates = [
                name
                for name, record in out_scores.items()
                if math.isclose(record["score"], top_score, rel_tol=1e-9, abs_tol=1e-9)
            ]
            win = random.choice(top_candidates if top_candidates else names)
        else:
            win = random.choice(names)
        result = {"scores": out_scores, "winner": win}
        if requested_winner or isinstance(win_raw, str):
            raw_text = requested_winner or str(win_raw).strip()
            result["raw_winner"] = raw_text
        return result

    def _resolve_winner(self, verdict: Dict, previous_name: Optional[str]) -> str:
        """直前の発言者を考慮しつつ最終的な勝者を決定する。"""

        agent_names = [agent.name for agent in self.cfg.agents]
        if not agent_names:
            raise ValueError("エージェントが1人も設定されていません。")

        requested = verdict.get("winner") if isinstance(verdict, dict) else None
        previous = previous_name if previous_name in agent_names else None

        if isinstance(requested, str) and requested in agent_names and requested != previous:
            return requested

        raw_scores = verdict.get("scores") if isinstance(verdict, dict) else {}
        scores: Dict[str, Dict[str, float]] = raw_scores if isinstance(raw_scores, dict) else {}
        candidates: List[Tuple[str, float]] = []
        for name in agent_names:
            if name == previous:
                continue
            score = 0.0
            if isinstance(scores, dict):
                record = scores.get(name)
                if isinstance(record, dict):
                    raw_score = record.get("score")
                    try:
                        score = float(raw_score) if raw_score is not None else 0.0
                    except (TypeError, ValueError):
                        score = 0.0
                    else:
                        if math.isnan(score):
                            score = 0.0
            candidates.append((name, score))

        if not candidates:
            if isinstance(requested, str) and requested in agent_names:
                return requested
            return previous or agent_names[0]

        top_score = max(score for _, score in candidates)
        top_candidates = [
            name
            for name, score in candidates
            if math.isclose(score, top_score, rel_tol=1e-9, abs_tol=1e-9)
        ]
        if not top_candidates:
            top_candidates = [candidates[0][0]]
        return top_candidates[0]

    def _try_parse_json(self, raw: str):
        # ```json ... ``` または テキスト中の最外郭JSON を頑丈に抽出
        try:
            m = re.findall(r"\{[\s\S]*\}", raw)
            for s in reversed(m):  # 最後のブロックがJSONであることが多い
                try:
                    return json.loads(s)
                except Exception:
                    continue
            return json.loads(raw)  # そのままJSONの可能性
        except Exception:
            return None

    def _speak_from_thought(self, agent: AgentConfig, thought: str) -> str:
        sys = (
            agent.system
            + "\n※以下はあなた自身の非公開メモです。要点だけを1〜2文の発言にし、"
            + "『メモ/思考/ヒント』等の語は本文に含めないこと。"
        )
        user = f"[自分の思考] {thought}\n\nこの要点を1〜2文の発言として述べてください。"
        req = LLMRequest(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=160,
        )
        return self._enforce_chat_constraints(self.backend.generate(req)).strip()

    def _conversation_summary(
        self,
        *,
        new_turn: Optional[Turn] = None,
        round_summary: Optional[str] = None,
    ) -> str:
        """会話全体の要点を蓄積・取得する。"""

        if not hasattr(self, "_conversation_summary_points"):
            self._conversation_summary_points = []

        points: List[str] = self._conversation_summary_points
        if new_turn is None and not round_summary:
            return self._format_conversation_summary(points)

        candidate_lines: List[str] = []
        if round_summary:
            if isinstance(round_summary, str):
                candidate_lines.extend(round_summary.splitlines())
            else:
                self.logger.append_warning(
                    "conversation_summary_invalid_round_summary",
                    context={"received_type": type(round_summary).__name__},
                )
        if not candidate_lines and new_turn is not None:
            content_value = getattr(new_turn, "content", "")
            if isinstance(content_value, str):
                content = content_value.strip()
            else:
                content = ""
                self.logger.append_warning(
                    "conversation_summary_invalid_turn_content",
                    context={
                        "speaker": getattr(new_turn, "speaker", ""),
                        "received_type": type(content_value).__name__,
                    },
                )
            if content:
                speaker_name = new_turn.speaker if isinstance(new_turn.speaker, str) else str(new_turn.speaker)
                candidate_lines.append(f"{speaker_name}: {content}")

        if not candidate_lines:
            return self._format_conversation_summary(points)

        seen = {line for line in points}
        for raw in candidate_lines:
            clean = re.sub(r"^[\s\-\*\u30fb・•\d\.\)]{0,3}", "", raw).strip()
            if not clean or clean in seen:
                continue
            points.append(clean)
            seen.add(clean)

        window = getattr(self.cfg, "chat_window", 2)
        try:
            max_points = max(4, int(window) * 3)
        except (TypeError, ValueError):  # window が数値でない場合のフォールバック
            max_points = 8
        if max_points > 0 and len(points) > max_points:
            del points[:-max_points]

        return self._format_conversation_summary(points)

    @staticmethod
    def _format_conversation_summary(points: List[str]) -> str:
        """会話サマリーの箇条書き文字列を生成する。"""

        if not points:
            return ""
        return "\n".join(f"- {line}" for line in points)

    def _agent_prompt(self, agent: AgentConfig, last_summary: str) -> LLMRequest:
        # ベースとなる役割プロンプト
        sys_prompt = agent.system
        last_turn = self.history[-1] if self.history else None
        last_speaker = last_turn.speaker if last_turn else ""
        last_content = last_turn.content if last_turn else ""
        profile = self._personality_profiles.get(agent.name)

        if not self.cfg.chat_mode:
            # 既存の“発表型”ルール
            sys_prompt += textwrap.dedent(
                f"""
                \n--- 会議ルール ---
- テーマ: {self.cfg.topic}
- 名前: {agent.name}
- 出力は必ず日本語。簡潔、箇条書き主体。過度な前置きは省略。
- 先の発言・要約を踏まえ、話を前に進める。
- 直前の発言（発言者名と要約）に対して具体的に応答する。
- 最後に「次に誰が何をするべきか」を1行で明示。
                """
            )
        else:
            # 短文チャット用の厳格ルール
            sys_prompt += textwrap.dedent(
                f"""
                \n--- 会話ルール（短文チャット）---
- テーマ: {self.cfg.topic}
- 名前: {agent.name}
- 出力は必ず日本語。絵文字・見出し・箇条書き・コードブロックは禁止。
- {self.cfg.chat_max_sentences}文以内、1文{self.cfg.chat_max_chars}文字以内。冗長な前き禁止。
- 直前の発言に一言で応答し、具体的な次の一歩を短く示す。
                """
            )
        if profile:
            sys_prompt += textwrap.dedent(
                f"""
                \n--- 個性指針 ---
- タイプ: {profile.name}
- 特徴: {profile.description}
- 発話トーン: {profile.speaking_guidance}
                """
            )
        # 直近コンテキスト
        prior_msgs: List[Dict[str, str]] = []
        if self.cfg.chat_mode:
            # 直近チャット窓だけを見せる（台本化防止）
            if getattr(self.cfg, "chat_context_summary", True):
                summary_text = self._conversation_summary()
                if summary_text:
                    prior_msgs.append({"role": "user", "content": f"会話サマリー:\n{summary_text}"})
            for t in self.history[-self.cfg.chat_window :]:
                prior_msgs.append({"role": "user", "content": f"{t.speaker}: {t.content}"})
        else:
            if last_turn:
                prior_msgs.append(
                    {
                        "role": "user",
                        "content": f"前回の発言者: {last_speaker}\n発言要約: {last_content}",
                    }
                )
            if last_summary:
                prior_msgs.append({"role": "user", "content": f"前ラウンド要約:\n{last_summary}"})
        prior_msgs.append({"role": "user", "content": f"テーマ再掲: {self.cfg.topic}"})
        if agent.style:
            prior_msgs.append({"role": "user", "content": f"話し方のトーン: {agent.style}"})
        memory_text = self._format_agent_memory(agent.name)
        if memory_text:
            prior_msgs.append({"role": "user", "content": memory_text})
        # Step5/7: 非公開ヒント（ショック/コントローラ）。本文に「ヒント」等は書かない。
        # 何も入れない（パラメータ側で制御）
        return LLMRequest(
            system=sys_prompt,
            messages=prior_msgs,
            temperature=self.temperature,
            max_tokens=(180 if self.cfg.chat_mode else self.cfg.max_tokens),
        )

    def _summarize_round(self, new_turn: Turn) -> Dict[str, Any]:
        """SummaryProbe のペイロードを生成し返す。"""

        try:
            result = self._summary_probe.generate_summary(new_turn, self.history)
        except Exception as exc:  # noqa: BLE001 - LLM呼び出し失敗時は握りつぶす
            self.logger.append_warning(
                "summary_probe_failed",
                context={
                    "error": str(exc),
                    "turn_index": len(self.history),
                    "speaker": getattr(new_turn, "speaker", ""),
                },
            )
            return {"summary": ""}
        return result

    def _log_summary_probe(
        self,
        *,
        turn: Turn,
        round_idx: int,
        phase_id: Optional[int],
        phase_turn: Optional[int],
        phase_kind: Optional[str],
        phase_base: Optional[int],
        payload: Dict[str, Any],
    ) -> None:
        """要約プローブ結果をログへ安全に書き出す。"""

        if not self.cfg.summary_probe_log_enabled:
            return
        try:
            record: Dict[str, Any] = dict(payload)
            record["round"] = round_idx
            if phase_id is not None and phase_turn is not None:
                phase_payload: Dict[str, Any] = {"id": phase_id, "turn": phase_turn}
                if phase_kind:
                    phase_payload["kind"] = phase_kind
                if phase_base is not None:
                    phase_payload["base"] = phase_base
                record["phase"] = phase_payload
            self.logger.append_summary_probe(record)
        except Exception as exc:  # noqa: BLE001 - ログ記録では失敗を握りつぶす
            self.logger.append_warning(
                "summary_probe_logging_failed",
                context={
                    "error": str(exc),
                    "round": round_idx,
                    "turn_index": len(self.history),
                    "speaker": turn.speaker,
                },
            )

    def _critic_pass(self, text: str) -> str:
        # 簡易ファクトチェック／自省（外部Webアクセスなし）
        req = LLMRequest(
            system="あなたは自己検証アシスタント。論点の穴、前提の曖昧さ、検証手段を列挙し、修正提案を日本語で箇条書きに。",
            messages=[{"role": "user", "content": text}],
            temperature=0.3,
            max_tokens=300,
        )
        critique = self.backend.generate(req)
        # 反映案の再生成（短く）
        req2 = LLMRequest(
            system="あなたは編集者。上記の指摘を反映して、元テキストを簡潔に改善し直す。",
            messages=[{"role": "user", "content": f"元:\n{text}\n\n指摘:\n{critique}"}],
            temperature=0.5,
            max_tokens=400,
        )
        improved = self.backend.generate(req2)
        return improved

    def _enforce_chat_constraints(self, text: str) -> str:
        """短文チャットの制約: 箇条書き/見出し除去、文数と長さを強制。"""
        if not self.cfg.chat_mode:
            return text.strip()
        s = text.replace("\r", "").strip()
        s = re.sub(r"^\s*[#>\-\*\u30fb・]+", "", s, flags=re.MULTILINE)
        parts = re.split(r"(?<=[。！？])\s+", s)
        trimmed = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(p) > self.cfg.chat_max_chars:
                p = p[: self.cfg.chat_max_chars] + "…"
            trimmed.append(p)
            if len(trimmed) >= self.cfg.chat_max_sentences:
                break
        return "\n".join(trimmed) if trimmed else s[: self.cfg.chat_max_chars]

    def _dedupe_bullets(self, text: str) -> str:
        """重複行を取り除いてスッキリさせる（先頭の・-数字. を無視して比較）"""
        seen = set()
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            norm = re.sub(r"^[\s\-\*\u30fb・\d\.\)]{0,3}", "", line)
            if norm in seen:
                continue
            seen.add(norm)
            out.append(raw)
        return "\n".join(out)

    def run(self) -> None:
        banner("AI Meeting Start")
        safe_console_print(f"Topic: {self.cfg.topic}")
        safe_console_print(f"Agents: {[a.name for a in self.cfg.agents]}")
        safe_console_print(
            f"Precision: {self.cfg.precision} (Temp={self.temperature:.2f}, CritiquePasses={self.critique_passes})"
        )
        safe_console_print(f"Rounds (互換用): {self.cfg.rounds}")
        phase_limit = self.cfg.get_phase_turn_limit()
        if phase_limit is not None:
            safe_console_print(f"Phase Turn Limit: {phase_limit}")
        if isinstance(self.cfg.phase_turn_limit, dict):
            safe_console_print(f"Phase Turn Map: {self.cfg.phase_turn_limit}")
        if self.cfg.max_phases:
            safe_console_print(f"Max Phases: {self.cfg.max_phases}")
        goal_default = self.cfg.get_phase_goal()
        if goal_default:
            safe_console_print(f"Phase Goal (default): {goal_default}")
        safe_console_print("")

        self._assign_personalities()

        last_summary = ""
        order = self.cfg.agents[:]  # 発言順
        global_turn = 0
        if phase_limit is not None and phase_limit <= 0:
            safe_console_print("Phase Turn Limit が0以下のため、会議を開始せず終了します。")
            self.metrics.stop()
            return
        if phase_limit is None:
            safe_console_print("Phase Turn Limit が設定されていないため、会議を開始せず終了します。")
            self.metrics.stop()
            return
        while self._phase_state and not self._phase_state.is_completed():
            current_phase = self._phase_state
            phase_turn = current_phase.turn_count + 1
            round_idx = self._phase_round_index(current_phase, phase_turn)

            if not self.cfg.ui_minimal:
                banner(f"Round {round_idx}")

            flow_summary = self._conversation_summary()
            if self.cfg.think_mode:
                thoughts: Dict[str, str] = {ag.name: self._think(ag, last_summary) for ag in self.cfg.agents}
                verdict = self._judge_thoughts(thoughts, last_summary, flow_summary)
                previous_speaker = self.history[-1].speaker if self.history else None
                winner_name = self._resolve_winner(verdict, previous_speaker)
                verdict["resolved_winner"] = winner_name
                winner = next((a for a in self.cfg.agents if a.name == winner_name), self.cfg.agents[0])
                content = self._speak_from_thought(winner, thoughts.get(winner.name, ""))
                if self.cfg.think_debug:
                    self.logger.append_thoughts(
                        {
                            "round": round_idx,
                            "turn": len(self.history) + 1,
                            "phase": {"id": current_phase.id, "turn": phase_turn},
                            "thoughts": thoughts,
                            "verdict": verdict,
                            "winner": winner.name,
                        }
                    )
                self.history.append(Turn(speaker=winner.name, content=content))
                safe_console_print(
                    f"{winner.name}: {content}\n"
                    if self.cfg.ui_minimal
                    else f"{winner.name}:\n{content}\n"
                )
                self.logger.append_turn(
                    round_idx,
                    len(self.history),
                    winner.name,
                    content,
                    phase_id=current_phase.id,
                    phase_turn=phase_turn,
                    phase_kind=current_phase.kind,
                    phase_base=current_phase.legacy_round_base,
                )
                current_speaker = winner
                self._last_spoke[current_speaker.name] = global_turn
            else:
                speaker = order[0]
                req = self._agent_prompt(speaker, last_summary)
                content = self.backend.generate(req)
                content = self._enforce_chat_constraints(content)
                if self.critique_passes > 0:
                    tmp = content
                    for _ in range(int(self.critique_passes)):
                        tmp = self._critic_pass(tmp)
                    content = tmp
                self.history.append(Turn(speaker=speaker.name, content=content))
                safe_console_print(f"{speaker.name}: {content}\n")
                self.logger.append_turn(
                    round_idx,
                    len(self.history),
                    speaker.name,
                    content,
                    phase_id=current_phase.id,
                    phase_turn=phase_turn,
                    phase_kind=current_phase.kind,
                    phase_base=current_phase.legacy_round_base,
                )
                current_speaker = speaker
                self._last_spoke[current_speaker.name] = global_turn

            global_turn += 1

            if self.equilibrium_enabled:
                recent = self._recent_context(self.cfg.chat_window)
                roster = "\n".join([f"- {a.name}: {a.system[:120]}" for a in self.cfg.agents])
                recent_text = recent if recent else "(発言なし)"
                last_summary_text = last_summary if last_summary else "(未設定)"
                flow_summary_text = flow_summary.strip() if flow_summary else "(未設定)"
                sys_eq = (
                    "あなたはモデレーターです。直近の流れに対して、各参加者が次の1手で"
                    "どれだけ有益な発言をできるかを0〜1で採点します。出力はJSONのみ。"
                )
                schema = (
                    "{ \"scores\": { \"NAME\": 0-1, ... }, \"rationale\": \"短文\", "
                    "\"context\": {\"recent_summary\": \"...\", \"flow_summary\": \"...\"} }"
                )
                user_eq = (
                    f"Topic: {self.cfg.topic}\n"
                    f"直近: {recent_text}\n"
                    f"直近要約: {last_summary_text}\n"
                    f"会話の流れサマリー:\n{flow_summary_text}\n\n"
                    f"直前の発言:\n{content}\n\n"
                    f"参加者と視点:\n{roster}\n\nJSON形式で厳密に出力:\n{schema}"
                )
                req2 = LLMRequest(
                    system=sys_eq,
                    messages=[{"role": "user", "content": user_eq}],
                    temperature=0.2,
                    max_tokens=600,
                )
                raw2 = self.backend.generate(req2).strip()
                j2 = self._try_parse_json(raw2) if hasattr(self, "_try_parse_json") else None
                base_scores: Dict[str, float] = {}
                if isinstance(j2, dict) and isinstance(j2.get("scores"), dict):
                    for a in self.cfg.agents:
                        v = j2["scores"].get(a.name)
                        try:
                            base_scores[a.name] = float(v)
                        except Exception:
                            base_scores[a.name] = 0.0
                else:
                    base_scores = {a.name: 0.5 for a in self.cfg.agents}
                adj: Dict[str, float] = {}
                sim_recent_text = self._concat_recent_text(self.cfg.sim_window)
                sim_tokens_recent = self._token_set(sim_recent_text) if sim_recent_text else set()
                for ag in self.cfg.agents:
                    s = base_scores.get(ag.name, 0.0)
                    if ag.name in self._last_spoke:
                        ago = global_turn - self._last_spoke[ag.name]
                        if 0 <= ago <= self.cfg.cooldown_span:
                            s -= self.cfg.cooldown
                    if sim_tokens_recent:
                        sim = self._similarity_tokens(self._token_set(content), sim_tokens_recent)
                        s -= self.cfg.sim_penalty * sim
                    adj[ag.name] = s
                top = sorted(adj.items(), key=lambda kv: kv[1], reverse=True)[: max(1, self.cfg.topk)]
                winner = self._softmax_pick(top, self.cfg.select_temp)
                order.sort(key=lambda a: 0 if a.name == winner else 1)
            else:
                order = order[1:] + order[:1]

            summary_payload = self._summarize_round(self.history[-1])
            last_summary = self._dedupe_bullets(summary_payload.get("summary", ""))
            summary_payload["summary"] = last_summary
            self._record_agent_memory(
                [ag.name for ag in self.cfg.agents],
                summary_payload,
                speaker_name=current_speaker.name,
            )
            self._conversation_summary(
                new_turn=self.history[-1],
                round_summary=last_summary or None,
            )
            self.logger.append_summary(
                round_idx,
                last_summary,
                phase_id=current_phase.id,
                phase_turn=phase_turn,
                phase_kind=current_phase.kind,
                phase_base=current_phase.legacy_round_base,
            )
            self._log_summary_probe(
                turn=self.history[-1],
                round_idx=round_idx,
                phase_id=current_phase.id,
                phase_turn=phase_turn,
                phase_kind=current_phase.kind,
                phase_base=current_phase.legacy_round_base,
                payload=summary_payload,
            )
            self._pending.add_from_text(last_summary)
            unresolved_count = len(self._pending.items)
            self._unresolved_history.append(unresolved_count)
            if len(self._unresolved_history) > max(4, self.cfg.phase_window):
                self._unresolved_history = self._unresolved_history[-self.cfg.phase_window :]
            current_phase.register_turn(len(self.history), unresolved_count)

            if self._monitor:
                event = self._monitor.observe(self.history, self._unresolved_history, self.cfg.phase_window)
                if event:
                    self._handle_phase_event(event)

            if getattr(current_speaker, "reveal_think", False):
                safe_console_print(
                    textwrap.indent(
                        f"(思考ログ/自己検証)\n{last_summary}", prefix="    "
                    )
                )  # 簡易版
            # ショックの寿命（ターン末にデクリメント）
            if getattr(self, "_shock_ttl", 0) > 0:
                self._shock_ttl -= 1
                if self._shock_ttl == 0:
                    self._shock_hint = None
            # Step7: KPIフィードバック（直近ウィンドウ）
            try:
                fb = self._ctrl.assess(self.history, self._unresolved_history)
                if fb and (self.cfg.kpi_auto_prompt or self.cfg.kpi_auto_tune):
                    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "type": "kpi_control"}
                    rec.update(fb)
                    self.logger.append_control(rec)
                    # 1) 隠しプロンプト
                    if self.cfg.kpi_auto_prompt and fb.get("hint"):
                        self._ctrl_hint = fb["hint"]
                        self._ctrl_ttl = 1  # 次ターンだけ
                    # 2) 自動チューニング
                    if self.cfg.kpi_auto_tune and "tune" in fb:
                        for key, val in fb["tune"].items():
                            if key == "shock_mode" and self._shock_engine:
                                self._shock_engine.mode = val
                            elif key == "sim_penalty":
                                self.cfg.sim_penalty = clamp(self.cfg.sim_penalty + val[1], val[2], val[3])
                            elif key == "select_temp":
                                self.cfg.select_temp = clamp(self.cfg.select_temp + val[1], val[2], val[3])
                            elif key == "cooldown":
                                self.cfg.cooldown = clamp(self.cfg.cooldown + val[1], val[2], val[3])
            except Exception:
                traceback.print_exc()

            # ヒントの寿命（ターンの最後にデクリメント）
            if self._ctrl_ttl > 0:
                self._ctrl_ttl -= 1
                if self._ctrl_ttl == 0:
                    self._ctrl_hint = None

            if not self._test_mode:
                time.sleep(0.2)

        if self._phase_state and self._phase_state.status != "closed":
            closing_event = PhaseEvent(
                phase_id=self._phase_state.id,
                start_turn=self._phase_state.start_turn,
                end_turn=len(self.history),
                status="closed",
                confidence=1.0,
                summary="フェーズ終了（ターン上限）",
                kind=self._phase_state.kind,
            )
            closed_state = self._end_phase(closing_event)
            self.logger.append_phase(self._phase_payload(closing_event, closed_state))

        # --- 残課題消化ラウンド（任意） ---
        if self.cfg.resolve_round and self._pending.items:
            banner("Resolution Round / 残課題の消化")
            last_summary, global_turn = self._run_resolution_phase(order, last_summary, global_turn)

        # 最終統合（Finisherがいない場合は内蔵フィニッシャ）
        final_req_system = (
            "あなたは議論の編集者です。これまでの発言を統合し、"
            "『合意事項』『残課題』『直近アクション』の3項目で日本語要約してください。"
        )
        final_messages = [
            {
                "role": "user",
                "content": "これまでの全発言:\n"
                + "\n\n".join([f"{t.speaker}:\n{t.content}" for t in self.history]),
            }
        ]
        final = self.backend.generate(
            LLMRequest(
                system=final_req_system,
                messages=final_messages,
                temperature=clamp(self.temperature, 0.2, 0.6),
                max_tokens=800,
            )
        )
        banner("Final Decision / 合意案")
        safe_console_print(final)
        self.logger.append_final(final)

        # Step6: KPI 評価と保存（最後の Meeting クラスにも入れる）
        kpi_result: Optional[Dict] = None
        try:
            evaluator = KPIEvaluator(self.cfg)
            pending = getattr(self, "_pending", None)
            kpi_result = evaluator.evaluate(self.history, pending, final)
            self.logger.append_kpi(kpi_result)
            safe_console_print(
                "\n=== KPI ===\n" + json.dumps(kpi_result, ensure_ascii=False, indent=2)
            )
        except Exception as e:
            safe_console_print(f"[KPI] 評価で例外: {e}")

        live_paths = []
        if self.logger.md:
            live_paths.append(str(self.logger.md))
        if self.logger.jsonl:
            live_paths.append(str(self.logger.jsonl))
        if live_paths:
            safe_console_print(f"\n（ライブログ: {' / '.join(live_paths)}）")
        result_path = self.logger.dir / "meeting_result.json"
        safe_console_print(f"\n（保存: {result_path}）")
        base_dir = self.logger.dir

        def _relative(path: Path) -> str:
            """成果物を meeting_result.json からの相対パスで表現する。"""

            try:
                return str(path.relative_to(base_dir))
            except ValueError:
                return path.name

        artifact_candidates: Dict[str, Path] = {}
        if self.logger.md:
            artifact_candidates["meeting_live_md"] = self.logger.md
        if self.logger.jsonl:
            artifact_candidates["meeting_live_jsonl"] = self.logger.jsonl
        artifact_candidates.update(
            {
                "meeting_live_html": self.logger.html,
                "phases_jsonl": self.logger.phase_log,
                "thoughts_jsonl": self.logger.thoughts_log,
                "control_jsonl": base_dir / "control.jsonl",
                "kpi_json": base_dir / "kpi.json",
                "metrics_csv": base_dir / "metrics.csv",
                "metrics_cpu_mem_png": base_dir / "metrics_cpu_mem.png",
                "metrics_gpu_png": base_dir / "metrics_gpu.png",
            }
        )
        if self.cfg.summary_probe_log_enabled:
            artifact_candidates["summary_probe_json"] = base_dir / self.cfg.summary_probe_filename
        files = {key: _relative(path) for key, path in artifact_candidates.items()}
        with result_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "topic": self.cfg.topic,
                    "precision": self.cfg.precision,
                    "rounds": self.cfg.rounds,
                    "phase_turn_limit": self.cfg.phase_turn_limit,
                    "max_phases": self.cfg.max_phases,
                    "phase_goal": self.cfg.phase_goal,
                    "resolve_round": self.cfg.resolve_round,
                    "agents": [a.model_dump() for a in self.cfg.agents],
                    "turns": [t.__dict__ for t in self.history],
                    "phases": self._serialize_phases(),
                    "final": final,
                    "kpi": kpi_result or {},
                    "files": files,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        # メトリクス停止＆グラフ作成
        try:
            self.metrics.stop()
            safe_console_print(
                f"（メトリクス: {self.logger.dir / 'metrics.csv'}, {self.logger.dir / 'metrics_cpu_mem.png'}, {self.logger.dir / 'metrics_gpu.png'}）"
            )
        except Exception:
            traceback.print_exc()

    # ---- Step3 helpers ----
    def _run_resolution_phase(
        self,
        order: List[AgentConfig],
        last_summary: str,
        global_turn: int,
    ) -> Tuple[str, int]:
        """残課題消化フェーズを進行させる。"""

        event = PhaseEvent(
            phase_id=self._phase_id + 1,
            start_turn=len(self.history) + 1,
            end_turn=len(self.history),
            status="open",
            confidence=1.0,
            summary="残課題消化フェーズ開始",
            kind="resolution",
        )
        state = self._begin_phase(event)
        self._reset_phase_controls()
        self.logger.append_phase(self._phase_payload(event, state))

        pending_text = "- " + "\n- ".join(sorted(self._pending.items))
        for agent in order:
            extra = (
                f"\n\n【残課題（要解消）】\n{pending_text}\n\n"
                f"あなたの視点で、上記の残課題を具体的に解消してください。必ず日本語で、実行可能な手順・責任分担・期限を含めてください。"
            )
            req = self._agent_prompt(agent, last_summary)
            req.messages.append({"role": "user", "content": extra})
            content = self.backend.generate(req)
            content = self._enforce_chat_constraints(content)
            if self.critique_passes > 0:
                content = self._critic_pass(content)
            self.history.append(Turn(speaker=agent.name, content=content))
            safe_console_print(f"{agent.name}:\n{content}\n")

            phase_turn = state.turn_count + 1
            round_idx = self._phase_round_index(state, phase_turn)
            self.logger.append_turn(
                round_idx,
                len(self.history),
                agent.name,
                content,
                phase_id=state.id,
                phase_turn=phase_turn,
                phase_kind=state.kind,
                phase_base=state.legacy_round_base,
            )
            summary_payload = self._summarize_round(self.history[-1])
            last_summary = self._dedupe_bullets(summary_payload.get("summary", ""))
            summary_payload["summary"] = last_summary
            self._record_agent_memory(
                [ag.name for ag in self.cfg.agents],
                summary_payload,
                speaker_name=agent.name,
            )
            self._conversation_summary(
                new_turn=self.history[-1],
                round_summary=last_summary or None,
            )
            self.logger.append_summary(
                round_idx,
                last_summary,
                phase_id=state.id,
                phase_turn=phase_turn,
                phase_kind=state.kind,
                phase_base=state.legacy_round_base,
            )
            self._log_summary_probe(
                turn=self.history[-1],
                round_idx=round_idx,
                phase_id=state.id,
                phase_turn=phase_turn,
                phase_kind=state.kind,
                phase_base=state.legacy_round_base,
                payload=summary_payload,
            )
            unresolved_count = len(self._pending.items)
            self._unresolved_history.append(unresolved_count)
            if len(self._unresolved_history) > max(4, self.cfg.phase_window):
                self._unresolved_history = self._unresolved_history[-self.cfg.phase_window :]
            state.register_turn(len(self.history), unresolved_count)
            self._last_spoke[agent.name] = global_turn
            global_turn += 1

        self._pending.clear()
        self._unresolved_history.append(len(self._pending.items))
        if len(self._unresolved_history) > max(4, self.cfg.phase_window):
            self._unresolved_history = self._unresolved_history[-self.cfg.phase_window :]

        closing_event = PhaseEvent(
            phase_id=state.id,
            start_turn=state.start_turn,
            end_turn=len(self.history),
            status="closed",
            confidence=1.0,
            summary="残課題消化フェーズ終了",
            kind=state.kind,
        )
        closed_state = self._end_phase(closing_event)
        self.logger.append_phase(self._phase_payload(closing_event, closed_state))
        return last_summary, global_turn

    def _concat_recent_text(self, window: int) -> str:
        if window <= 0 or not self.history:
            return ""
        lines = [t.content for t in self.history[-window:]]
        return "\n".join(lines)

    def _token_set(self, text: str) -> set:
        # 記号・数字を落として簡易トークン集合に（日本語/英語混在でもそこそこ効く）
        t = re.sub(r"[0-9]+", " ", text)
        t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", t, flags=re.UNICODE)
        toks = [w for w in t.lower().split() if len(w) > 1]
        return set(toks)

    def _similarity_tokens(self, a: set, b: set) -> float:
        # Jaccard 類似（0〜1）
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union

    def _softmax_pick(self, pairs: List[Tuple[str, float]], temp: float) -> str:
        # pairs: [(name, score), ...] -> name をソフトマックス抽選
        vals = [p[1] for p in pairs]
        m = max(vals)
        exps = [math.exp((v - m) / max(1e-6, temp)) for v in vals]
        s = sum(exps)
        probs = [e / s for e in exps]
        r = random.random()
        acc = 0.0
        for (name, _), p in zip(pairs, probs):
            acc += p
            if r <= acc:
                return name
        return pairs[0][0]  # フォールバック