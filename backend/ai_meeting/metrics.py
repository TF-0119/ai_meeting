"""システムリソース利用状況を定期的に記録するためのモジュール。"""
from __future__ import annotations

import csv
import math
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil


class MetricsLogger:
    """CPU/GPU のメトリクスを取得して CSV/グラフに保存する。"""

    def __init__(self, outdir: Path, interval: float = 1.0):
        self.outdir = Path(outdir)
        self.interval = max(0.5, float(interval))
        self.csv_path = self.outdir / "metrics.csv"
        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._gpu_backend: Optional[str] = None
        self.nv = None
        self._init_gpu_backend()
        with self.csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "cpu_percent",
                    "ram_percent",
                    "gpu_util",
                    "gpu_mem_used_mb",
                    "gpu_mem_total_mb",
                    "gpu_temp_c",
                    "gpu_power_w",
                ]
            )

    def _init_gpu_backend(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self.nv = pynvml
            self._gpu_backend = "pynvml"
        except Exception:
            try:
                import GPUtil  # noqa: F401

                self._gpu_backend = "gputil"
            except Exception:
                self._gpu_backend = None

    def _poll_gpu(self):
        util = mem_used = mem_total = temp = power = None
        if self._gpu_backend == "pynvml":
            try:
                h = self.nv.nvmlDeviceGetHandleByIndex(0)
                util = float(self.nv.nvmlDeviceGetUtilizationRates(h).gpu)
                mem = self.nv.nvmlDeviceGetMemoryInfo(h)
                mem_used = round(int(mem.used) / (1024 * 1024), 1)
                mem_total = round(int(mem.total) / (1024 * 1024), 1)
                try:
                    temp = float(self.nv.nvmlDeviceGetTemperature(h, self.nv.NVML_TEMPERATURE_GPU))
                except Exception:
                    temp = None
                try:
                    power = round(self.nv.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)
                except Exception:
                    power = None
            except Exception:
                pass
        elif self._gpu_backend == "gputil":
            try:
                import GPUtil

                gpu = GPUtil.getGPUs()[0]
                util = float(gpu.load * 100.0)
                mem_used = round(gpu.memoryUsed, 1)
                mem_total = round(gpu.memoryTotal, 1)
                temp = float(getattr(gpu, "temperature", math.nan))
                if math.isnan(temp):
                    temp = None
                power = None
            except Exception:
                pass
        return util, mem_used, mem_total, temp, power

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cpu = float(psutil.cpu_percent(interval=None))
                ram = float(psutil.virtual_memory().percent)
                gpu_util, gpu_mu, gpu_mt, gpu_temp, gpu_pw = self._poll_gpu()
                with self.csv_path.open("a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([ts, cpu, ram, gpu_util, gpu_mu, gpu_mt, gpu_temp, gpu_pw])
            except Exception:
                traceback.print_exc()
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=5)
        self._make_plots()

    def _make_plots(self) -> None:
        try:
            import matplotlib.pyplot as plt
            import numpy as np

            rows = []
            with self.csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if not rows:
                return
            xs = [i for i in range(len(rows))]
            cpu = [float(r["cpu_percent"]) if r["cpu_percent"] else np.nan for r in rows]
            ram = [float(r["ram_percent"]) if r["ram_percent"] else np.nan for r in rows]
            gpu_util = [float(r["gpu_util"]) if r["gpu_util"] else np.nan for r in rows]
            gpu_mu = [float(r["gpu_mem_used_mb"]) if r["gpu_mem_used_mb"] else np.nan for r in rows]
            gpu_mt = [float(r["gpu_mem_total_mb"]) if r["gpu_mem_total_mb"] else np.nan for r in rows]
            gpu_temp = [float(r["gpu_temp_c"]) if r["gpu_temp_c"] else np.nan for r in rows]
            gpu_pw = [float(r["gpu_power_w"]) if r["gpu_power_w"] else np.nan for r in rows]

            plt.figure()
            plt.plot(xs, cpu, label="CPU %")
            plt.plot(xs, ram, label="RAM %")
            plt.xlabel("samples")
            plt.ylabel("Percent (%)")
            plt.legend()
            plt.title("CPU/RAM usage")
            plt.tight_layout()
            (self.outdir / "metrics_cpu_mem.png").unlink(missing_ok=True)
            plt.savefig(self.outdir / "metrics_cpu_mem.png")
            plt.close()

            plt.figure()
            if any(not np.isnan(v) for v in gpu_util):
                plt.plot(xs, gpu_util, label="GPU %")
            if any(not np.isnan(v) for v in gpu_mu):
                plt.plot(xs, gpu_mu, label="VRAM used (MB)")
            if any(not np.isnan(v) for v in gpu_temp):
                plt.plot(xs, gpu_temp, label="Temp (°C)")
            if any(not np.isnan(v) for v in gpu_pw):
                plt.plot(xs, gpu_pw, label="Power (W)")
            plt.xlabel("samples")
            plt.legend(loc="best")
            plt.title("GPU metrics")
            plt.tight_layout()
            (self.outdir / "metrics_gpu.png").unlink(missing_ok=True)
            plt.savefig(self.outdir / "metrics_gpu.png")
            plt.close()
        except Exception:
            traceback.print_exc()


__all__ = ["MetricsLogger"]
