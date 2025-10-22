"""重要論点や未解決事項を蓄積するセマンティックコア管理。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import time
from typing import Any, Dict, Iterable, List, MutableMapping, Optional


DEFAULT_CATEGORIES: tuple[str, ...] = ("key_points", "open_issues")


def _normalize_text(text: str) -> str:
    """重複判定用にテキストを正規化する。"""

    lowered = text.strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[\u3000\s]+", " ", lowered)
    return lowered


@dataclass
class SemanticCoreItem:
    """セマンティックコア1件分の情報。"""

    text: str
    source: str
    weight: float
    created_at: float
    updated_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    mentions: int = 1

    def touch(self, source: str, weight: float, metadata: Optional[Dict[str, Any]] = None) -> None:
        """既存エントリを最新情報で更新する。"""

        self.updated_at = time.time()
        self.mentions += 1
        if weight > self.weight:
            self.weight = weight
        if source:
            self.source = source
        if metadata:
            if self.metadata:
                merged: Dict[str, Any] = dict(self.metadata)
                merged.update(metadata)
                self.metadata = merged
            else:
                self.metadata = dict(metadata)

    def to_dict(self) -> Dict[str, Any]:
        """JSON シリアライズ可能な辞書へ変換する。"""

        return {
            "text": self.text,
            "source": self.source,
            "weight": round(self.weight, 3),
            "mentions": self.mentions,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.fromtimestamp(self.updated_at).isoformat(),
            "metadata": self.metadata,
        }


class SemanticCoreStore:
    """重要論点や残課題をカテゴリ別に管理するストア。"""

    def __init__(
        self,
        categories: Optional[Iterable[str]] = None,
        *,
        max_items_per_category: Optional[int] = 20,
    ) -> None:
        base_categories = list(categories) if categories else list(DEFAULT_CATEGORIES)
        self._max_items = max_items_per_category if max_items_per_category else None
        self._items: Dict[str, List[SemanticCoreItem]] = {cat: [] for cat in base_categories}
        self._index: Dict[str, str] = {}

    def categories(self) -> List[str]:
        """現在のカテゴリ一覧を返す。"""

        return list(self._items.keys())

    def add(
        self,
        category: str,
        text: str,
        *,
        source: str,
        weight: float = 1.0,
        metadata: Optional[MutableMapping[str, Any]] = None,
    ) -> bool:
        """カテゴリへ要素を追加する。重複する場合は更新のみ行う。"""

        clean = text.strip()
        if not clean:
            return False

        normalized = _normalize_text(clean)
        now = time.time()
        meta: Dict[str, Any] = dict(metadata) if metadata else {}

        if normalized in self._index:
            cat = self._index[normalized]
            bucket = self._items.setdefault(cat, [])
            for item in bucket:
                if _normalize_text(item.text) == normalized:
                    item.touch(source, weight, meta)
                    return False
            # 万一インデックスと実体がずれた場合は fallthrough で追加する

        bucket = self._items.setdefault(category, [])
        item = SemanticCoreItem(
            text=clean,
            source=source,
            weight=weight,
            created_at=now,
            updated_at=now,
            metadata=meta,
        )
        bucket.append(item)
        self._index[normalized] = category
        self._enforce_limit(category)
        return True

    def _enforce_limit(self, category: str) -> None:
        """カテゴリごとの上限を満たすよう調整する。"""

        if not self._max_items or self._max_items <= 0:
            return
        bucket = self._items.get(category)
        if not bucket or len(bucket) <= self._max_items:
            return
        bucket.sort(key=lambda item: (-item.mentions, -item.weight, item.created_at))
        trimmed = bucket[: self._max_items]
        removed = bucket[self._max_items :]
        self._items[category] = trimmed
        for item in removed:
            normalized = _normalize_text(item.text)
            self._index.pop(normalized, None)

    def to_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        """ストア全体をシリアライズ可能な辞書に変換する。"""

        output: Dict[str, List[Dict[str, Any]]] = {}
        for category, items in self._items.items():
            if not items:
                continue
            sorted_items = sorted(
                items,
                key=lambda item: (-item.mentions, -item.weight, item.created_at),
            )
            output[category] = [item.to_dict() for item in sorted_items]
        return output

    def is_empty(self) -> bool:
        """保持しているエントリが存在しないかを返す。"""

        return all(not items for items in self._items.values())

