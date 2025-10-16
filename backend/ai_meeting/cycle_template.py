"""サイクル出力テンプレートの生成と解析ユーティリティ。"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# 会議ルールで禁止されている語句。必要に応じてここで拡張する。
_FORBIDDEN_TERMS: Tuple[str, ...] = (
    "見出し",
    "箇条書き",
    "コードブロック",
    "絵文字",
    "メタ言及",
    "担当",
    "期限",
    "締切",
)


def _sanitize_text(text: Optional[str], forbidden_terms: Sequence[str]) -> str:
    """禁止語を除去し、周囲の空白を整えて返す。"""

    if text is None:
        return ""
    value = str(text)
    for term in forbidden_terms:
        if term:
            value = value.replace(term, "")
    return value.strip()


def _build_diverge_entries(
    base_text: str, candidate: Any, terms: Tuple[str, ...]
) -> List[Dict[str, Any]]:
    """Diverge ブロックを正規化して返す。"""

    entries: List[Dict[str, Any]] = []
    if isinstance(candidate, list):
        for item in candidate:
            if isinstance(item, dict):
                hypothesis = _sanitize_text(item.get("hypothesis"), terms)
                assumptions_raw = item.get("assumptions")
                assumptions: List[str] = []
                if isinstance(assumptions_raw, (list, tuple)):
                    assumptions = [
                        _sanitize_text(val, terms)
                        for val in assumptions_raw
                        if _sanitize_text(val, terms)
                    ]
                if hypothesis or assumptions:
                    entries.append({
                        "hypothesis": hypothesis,
                        "assumptions": assumptions,
                    })
            elif isinstance(item, str):
                hypothesis = _sanitize_text(item, terms)
                if hypothesis:
                    entries.append({"hypothesis": hypothesis, "assumptions": []})

    if not entries:
        hypothesis = _sanitize_text(base_text, terms)
        if hypothesis:
            entries.append({"hypothesis": hypothesis, "assumptions": []})

    return entries


def _build_learn_entries(
    base_text: str, candidate: Any, terms: Tuple[str, ...]
) -> List[Dict[str, Any]]:
    """Learn ブロックを正規化して返す。"""

    entries: List[Dict[str, Any]] = []
    if isinstance(candidate, list):
        for item in candidate:
            if isinstance(item, dict):
                insight = _sanitize_text(item.get("insight"), terms)
                why = _sanitize_text(item.get("why"), terms)
                links_raw = item.get("links")
                links: List[str] = []
                if isinstance(links_raw, (list, tuple)):
                    links = [
                        _sanitize_text(val, terms)
                        for val in links_raw
                        if _sanitize_text(val, terms)
                    ]
                if insight or why or links:
                    entries.append({
                        "insight": insight,
                        "why": why,
                        "links": links,
                    })
            elif isinstance(item, str):
                insight = _sanitize_text(item, terms)
                if insight:
                    entries.append({"insight": insight, "why": "", "links": []})

    if not entries:
        clean = _sanitize_text(base_text, terms)
        if clean:
            lines = [
                line.strip("-・* \t")
                for line in clean.splitlines()
                if line.strip("-・* \t")
            ]
            if not lines:
                lines = [clean]
            for line in lines:
                entries.append({"insight": line, "why": "", "links": []})

    return entries


def _build_converge_entries(
    base_text: str, candidate: Any, terms: Tuple[str, ...]
) -> List[Dict[str, Any]]:
    """Converge ブロックを正規化して返す。"""

    entries: List[Dict[str, Any]] = []
    if isinstance(candidate, list):
        for item in candidate:
            if isinstance(item, dict):
                commit = _sanitize_text(item.get("commit"), terms)
                reason = _sanitize_text(item.get("reason"), terms)
                if commit or reason:
                    entries.append({"commit": commit, "reason": reason})
            elif isinstance(item, str):
                commit = _sanitize_text(item, terms)
                if commit:
                    entries.append({"commit": commit, "reason": ""})

    if not entries:
        commit = _sanitize_text(base_text, terms)
        if commit:
            entries.append({"commit": commit, "reason": ""})

    return entries


def build_cycle_payload(
    cycle_no: int,
    diverge_source: Optional[str],
    learn_source: Optional[str],
    converge_commit: Optional[str],
    next_goal: Optional[str],
    *,
    forbidden_terms: Iterable[str] = _FORBIDDEN_TERMS,
) -> str:
    """サイクル情報を JSON 文字列として構築する。"""

    terms = tuple(str(term) for term in forbidden_terms if term)
    diverge_text = _sanitize_text(diverge_source, terms)
    learn_text = _sanitize_text(learn_source, terms)
    converge_text = _sanitize_text(converge_commit, terms)
    goal_text = _sanitize_text(next_goal, terms)

    agent_payload: Dict[str, Any] = {}
    if converge_commit:
        parsed = parse_cycle_content(converge_commit)
        if isinstance(parsed, dict):
            agent_payload = parsed

    diverge_entries = _build_diverge_entries(
        diverge_text,
        agent_payload.get("diverge"),
        terms,
    )
    learn_entries = _build_learn_entries(
        learn_text,
        agent_payload.get("learn"),
        terms,
    )
    converge_entries = _build_converge_entries(
        converge_text,
        agent_payload.get("converge"),
        terms,
    )

    next_goal_text = goal_text
    if not next_goal_text:
        next_goal_text = _sanitize_text(agent_payload.get("next_goal"), terms)

    payload: Dict[str, Any] = {
        "cycle": int(cycle_no),
        "diverge": diverge_entries,
        "learn": learn_entries,
        "converge": converge_entries,
        "next_goal": next_goal_text,
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_cycle_content(content: Any) -> Optional[Dict[str, Any]]:
    """サイクル JSON 文字列を辞書へ変換する。失敗時は None。"""

    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def extract_cycle_text(content: Any, field: str = "converge") -> str:
    """サイクル JSON から指定フィールドの文字列を抽出する。"""

    if isinstance(content, str):
        data = parse_cycle_content(content)
        if data is not None:
            value = data.get(field)
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                parts: List[str] = []
                for item in value:
                    if isinstance(item, dict):
                        for key in ("commit", "hypothesis", "insight", "reason", "why"):
                            text = item.get(key)
                            if isinstance(text, str) and text.strip():
                                parts.append(text.strip())
                                break
                    elif isinstance(item, str) and item.strip():
                        parts.append(item.strip())
                if parts:
                    return " / ".join(parts)
        return content.strip()
    return ""


__all__ = [
    "build_cycle_payload",
    "parse_cycle_content",
    "extract_cycle_text",
]
