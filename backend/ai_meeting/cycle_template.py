"""サイクル出力テンプレートの生成と解析ユーティリティ。"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

# 会議ルールで禁止されている語句。必要に応じてここで拡張する。
_FORBIDDEN_TERMS: Tuple[str, ...] = (
    "見出し",
    "箇条書き",
    "コードブロック",
    "絵文字",
    "メタ言及",
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
    diverge = _sanitize_text(diverge_source, terms)
    learn = _sanitize_text(learn_source, terms)
    converge = _sanitize_text(converge_commit, terms)
    goal = _sanitize_text(next_goal, terms)

    payload: Dict[str, Any] = {
        "cycle": int(cycle_no),
        "diverge": diverge,
        "learn": learn,
        "converge": converge,
        "next_goal": goal,
        "assumptions": [],
        "links": [],
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
        return content.strip()
    return ""


__all__ = [
    "build_cycle_payload",
    "parse_cycle_content",
    "extract_cycle_text",
]
