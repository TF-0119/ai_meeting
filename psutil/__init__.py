"""psutil の簡易スタブ。テスト環境で必要な最小限のAPIのみ実装する。"""

import os
import random
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Optional


def _import_real_psutil() -> Optional[ModuleType]:
    """可能であれば本物の psutil を読み込み、失敗時は ``None`` を返す。"""

    if os.environ.get("PSUTIL_FORCE_STUB") == "1":
        return None

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    original_module = sys.modules.get(__name__)
    original_path = list(sys.path)

    sanitized_path = []
    for entry in original_path:
        entry_abs = os.path.abspath(entry or ".")
        if entry_abs.startswith(repo_root):
            continue
        sanitized_path.append(entry)

    sys.modules.pop(__name__, None)

    try:
        sys.path = sanitized_path
        import importlib

        real_module = importlib.import_module(__name__)
    except Exception:
        real_module = None
    finally:
        sys.path = original_path
        if original_module is not None:
            sys.modules[__name__] = original_module
        elif __name__ in sys.modules:
            # 実モジュールが sys.modules に登録されている場合は除外する。
            sys.modules.pop(__name__, None)

    # 取り込めた場合は、そのまま返す。
    if real_module is None:
        return None

    # 念のため、取り込んだモジュールがこのファイル自身でないことを確認する。
    real_path = getattr(real_module, "__file__", None)
    if real_path and os.path.abspath(real_path) == os.path.abspath(__file__):
        return None

    return real_module


_REAL_PSUTIL = _import_real_psutil()

if _REAL_PSUTIL is not None:
    # 本物が存在する場合はそれをそのまま再エクスポートする。
    cpu_percent = _REAL_PSUTIL.cpu_percent
    virtual_memory = _REAL_PSUTIL.virtual_memory
    pid_exists = _REAL_PSUTIL.pid_exists
    __all__ = getattr(_REAL_PSUTIL, "__all__", [name for name in dir(_REAL_PSUTIL) if not name.startswith("_")])
else:

    def cpu_percent(interval=None):
        """ダミーのCPU使用率（0-10%程度）を返す。"""
        return round(5 + random.random() * 3, 2)


    @dataclass
    class _VirtualMemory:
        percent: float


    def virtual_memory():
        """固定値に近いRAM使用率を返す。"""
        return _VirtualMemory(percent=round(40 + random.random() * 5, 2))


    def pid_exists(pid: int) -> bool:
        """``os.kill(pid, 0)`` を使ってプロセスの生存確認を行う。"""

        if pid <= 0:
            return False

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # シグナル送信が許可されていなくてもプロセスは存在するとみなす。
            return True
        except OSError:
            return False
        else:
            return True


    __all__ = ["cpu_percent", "virtual_memory", "pid_exists"]
