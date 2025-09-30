"""psutil の簡易スタブ。テスト環境で必要な最小限のAPIのみ実装する。"""
import random
from dataclasses import dataclass


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
    """最小限の互換性を保つため常にFalseを返す。"""
    return False
