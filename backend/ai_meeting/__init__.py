"""`backend.ai_meeting` パッケージの暫定エントリーポイント。

旧 `backend/ai_meeting.py` モジュールをそのまま利用しつつ、
段階的にパッケージ構成へ移行できるようにする。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional, TypeVar, cast

__all__ = ["load_legacy_module", "get_main"]

TFunc = TypeVar("TFunc", bound=Callable[..., object])


def load_legacy_module() -> ModuleType:
    """旧 `backend/ai_meeting.py` をモジュールとして読み込む。

    Python の import 解決順はパッケージを優先するため、
    本パッケージ作成後は `import backend.ai_meeting` が
    自身を指してしまう。この関数ではファイルパスを指定して
    旧実装を読み込み、従来の関数を利用できるようにする。
    """

    package_dir = Path(__file__).resolve().parent
    legacy_path = package_dir.parent / f"{package_dir.name}.py"

    spec = importlib.util.spec_from_file_location(
        "backend.ai_meeting_legacy", legacy_path
    )
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
