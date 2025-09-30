"""旧 `backend.ai_meeting` モジュールを読み込むための補助。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional, TypeVar, cast

TFunc = TypeVar("TFunc", bound=Callable[..., object])


def load_legacy_module() -> ModuleType:
    """旧 `backend/ai_meeting.py` をモジュールとして読み込む。"""

    package_dir = Path(__file__).resolve().parent
    legacy_path = package_dir.parent / f"{package_dir.name}.py"

    spec = importlib.util.spec_from_file_location("backend.ai_meeting_legacy", legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"旧モジュールを読み込めませんでした: {legacy_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_main() -> Callable[..., object]:
    """旧モジュールの `main()` を取得する。"""

    module = load_legacy_module()
    main_attr: Optional[object] = getattr(module, "main", None)
    if not callable(main_attr):
        raise AttributeError("旧モジュールに main() が見つかりません。")
    return cast(TFunc, main_attr)
