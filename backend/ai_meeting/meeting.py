"""会議制御用の新しいラッパークラス。"""
from __future__ import annotations

from typing import Any

from ._legacy import load_legacy_module
from .config import MeetingConfig


class Meeting:
    """旧実装を内部で利用するラッパー。"""

    def __init__(self, cfg: MeetingConfig):
        legacy_module = load_legacy_module()
        legacy_cls = getattr(legacy_module, "Meeting", None)
        if legacy_cls is None:
            raise AttributeError("旧実装に Meeting クラスが見つかりません。")
        self._impl = legacy_cls(cfg)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """旧 Meeting#run を呼び出す。"""

        return self._impl.run(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)
