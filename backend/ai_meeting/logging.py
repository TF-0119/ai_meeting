"""会議ログをリアルタイムに書き出すためのユーティリティ。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class LiveLogWriter:
    """Markdown/JSONL ログを逐次追記するライター。"""

    def __init__(self, topic: str, outdir: Optional[str] = None, ui_minimal: bool = True):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c if c.isalnum() or c in "-_（）()[]" else "_" for c in topic)[:80]
        base_dir = Path(outdir or f"logs/{ts}_{safe_topic}")
        base_dir.mkdir(parents=True, exist_ok=True)
        self.dir = base_dir
        self.md = base_dir / "meeting_live.md"
        self.jsonl = base_dir / "meeting_live.jsonl"
        self.html = base_dir / "meeting_live.html"
        self.ui_minimal = ui_minimal
        self.phase_log = base_dir / "phases.jsonl"
        # ★ 思考ログ（デバッグ用・本文には出さない）
        self.thoughts_log = base_dir / "thoughts.jsonl"

        # ヘッダを書いておく
        with self.md.open("w", encoding="utf-8", newline="\n") as f:
            if self.ui_minimal:
                f.write(f"【Topic】{topic}（開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）\n\n")
            else:
                f.write(
                    (
                        f"# Topic: {topic}\n\n"
                        f"- 開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        "- ログ形式: ラウンドごとに追記\n\n"
                    )
                )
            f.flush()
        # JSONLは空ファイル作成のみ
        self.jsonl.touch()
        self.thoughts_log.touch()

    def append_turn(self, round_idx: int, turn_idx: int, speaker: str, content: str):
        """1発言分のログを追記する。"""

        line = content.strip()
        line = re.sub(r"^\s*[#>\-\*\u30fb・]+", "", line, flags=re.MULTILINE)
        with self.md.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"{speaker}: {line}\n\n")
            f.flush()
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": "turn",
            "round": round_idx,
            "turn": turn_idx,
            "speaker": speaker,
            "content": content,
        }
        with self.jsonl.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def append_phase(self, payload):
        """フェーズ検知の結果を JSONL に追記する。"""

        if is_dataclass(payload):
            record = asdict(payload)
        else:
            record = dict(payload)
        with self.phase_log.open("a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def append_thoughts(self, payload: Dict):
        """思考ログを JSONL に追記する（UI には表示しない）。"""

        with self.thoughts_log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            f.flush()

    def append_control(self, payload: Dict):
        """KPI コントローラの状態を記録する。"""

        with (self.dir / "control.jsonl").open("a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            f.flush()

    def append_summary(self, round_idx: int, summary: str):
        """ラウンド要約を追記する。"""

        text = summary.strip()
        if self.ui_minimal:
            tag = "要約"
            with self.md.open("a", encoding="utf-8", newline="\n") as f:
                f.write(f"（{tag}）{text}\n\n")
                f.flush()
        else:
            with self.md.open("a", encoding="utf-8", newline="\n") as f:
                f.write(f"### Round {round_idx} 要約\n\n{text}\n\n")
                f.flush()
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": "summary",
            "round": round_idx,
            "summary": text,
        }
        with self.jsonl.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def append_final(self, final_text: str):
        """最終合意内容を追記する。"""

        text = final_text.strip()
        with self.md.open("a", encoding="utf-8", newline="\n") as f:
            if self.ui_minimal:
                f.write("【Final】\n" + text + "\n")
            else:
                f.write("## Final Decision / 合意案\n\n" + text + "\n")
            f.flush()
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": "final",
            "final": final_text,
        }
        with self.jsonl.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def append_kpi(self, kpi: Dict):
        """KPI 情報を Markdown と JSON に保存する。"""

        with self.md.open("a", encoding="utf-8", newline="\n") as f:
            f.write("\n=== KPI ===\n")
            for key, value in kpi.items():
                f.write(f"- {key}: {value}\n")
            f.flush()
        (self.dir / "kpi.json").write_text(
            json.dumps(kpi, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


__all__ = ["LiveLogWriter"]
