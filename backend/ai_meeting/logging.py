"""会議ログをリアルタイムに書き出すためのユーティリティ。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
from uuid import uuid4


class LiveLogWriter:
    """Markdown/JSONL ログを逐次追記するライター。"""

    def __init__(
        self,
        topic: str,
        outdir: Optional[str] = None,
        ui_minimal: bool = True,
        summary_probe_filename: str = "summary_probe.json",
        *,
        enable_markdown: bool = True,
        enable_jsonl: bool = True,
        run_id: Optional[str] = None,
    ):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c if c.isalnum() or c in "-_（）()[]" else "_" for c in topic)[:80]
        base_dir = Path(outdir or f"logs/{ts}_{safe_topic}")
        base_dir.mkdir(parents=True, exist_ok=True)
        self.dir = base_dir
        self.enable_markdown = enable_markdown
        self.enable_jsonl = enable_jsonl
        self.md: Optional[Path] = base_dir / "meeting_live.md" if enable_markdown else None
        self.jsonl: Optional[Path] = base_dir / "meeting_live.jsonl" if enable_jsonl else None
        self.html = base_dir / "meeting_live.html"
        self.ui_minimal = ui_minimal
        self.phase_log = base_dir / "phases.jsonl"
        # ★ 思考ログ（デバッグ用・本文には出さない）
        self.thoughts_log = base_dir / "thoughts.jsonl"
        self.summary_probe_log = base_dir / summary_probe_filename
        self.run_id = run_id or uuid4().hex
        self._span_counter = 0

        # ヘッダを書いておく
        if self.md:
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
        if self.jsonl:
            self.jsonl.touch()
        self.thoughts_log.touch()
        self.summary_probe_log.touch()

    def append_turn(
        self,
        round_id: int,
        turn_idx: int,
        speaker: str,
        content: str,
        *,
        phase_id: Optional[int] = None,
        phase_turn: Optional[int] = None,
        phase_kind: Optional[str] = None,
        phase_base: Optional[int] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_version: Optional[str] = None,
        decode_params: Optional[Dict[str, Any]] = None,
    ):
        """1発言分のログを追記する。"""

        line = content.strip()
        line = re.sub(r"^\s*[#>\-\*\u30fb・]+", "", line, flags=re.MULTILINE)
        if self.md:
            with self.md.open("a", encoding="utf-8", newline="\n") as f:
                f.write(f"{speaker}: {line}\n\n")
                f.flush()
        record = self._create_record(
            "turn",
            {
                "round": round_id,
                "turn": turn_idx,
                "speaker": speaker,
                "content": content,
            },
            round_id=round_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_id=agent_id,
            prompt_version=prompt_version,
            model_version=model_version,
            decode_params=decode_params,
            phase_id=phase_id,
            phase_turn=phase_turn,
            phase_kind=phase_kind,
            phase_base=phase_base,
        )
        self._append_jsonl(record)

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

    def append_summary(
        self,
        round_id: int,
        summary: str,
        *,
        phase_id: Optional[int] = None,
        phase_turn: Optional[int] = None,
        phase_kind: Optional[str] = None,
        phase_base: Optional[int] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_version: Optional[str] = None,
        decode_params: Optional[Dict[str, Any]] = None,
    ):
        """ラウンド要約を追記する。"""

        text = summary.strip()
        if self.md:
            if self.ui_minimal:
                tag = "要約"
                with self.md.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(f"（{tag}）{text}\n\n")
                    f.flush()
            else:
                with self.md.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(f"### Round {round_idx} 要約\n\n{text}\n\n")
                    f.flush()
        record = self._create_record(
            "summary",
            {
                "round": round_id,
                "summary": text,
            },
            round_id=round_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_id=agent_id,
            prompt_version=prompt_version,
            model_version=model_version,
            decode_params=decode_params,
            phase_id=phase_id,
            phase_turn=phase_turn,
            phase_kind=phase_kind,
            phase_base=phase_base,
        )
        self._append_jsonl(record)

    def append_summary_probe(self, payload: Dict[str, Any]) -> None:
        """要約プローブの結果を JSONL 形式で追記する。"""

        with self.summary_probe_log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            f.flush()

    def iter_summary_probe(self) -> Iterator[Dict[str, Any]]:
        """要約プローブログから JSON レコードを順に取得する。"""

        with self.summary_probe_log.open("r", encoding="utf-8") as f:
            for line in f:
                entry = line.strip()
                if not entry:
                    continue
                try:
                    yield json.loads(entry)
                except json.JSONDecodeError as exc:  # pragma: no cover - 想定外のログ破損
                    raise ValueError("summary_probe ログの形式が不正です。") from exc

    def append_final(
        self,
        final_text: str,
        *,
        round_id: Optional[int] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_version: Optional[str] = None,
        decode_params: Optional[Dict[str, Any]] = None,
    ):
        """最終合意内容を追記する。"""

        text = final_text.strip()
        if self.md:
            with self.md.open("a", encoding="utf-8", newline="\n") as f:
                if self.ui_minimal:
                    f.write("【Final】\n" + text + "\n")
                else:
                    f.write("## Final Decision / 合意案\n\n" + text + "\n")
                f.flush()
        record = self._create_record(
            "final",
            {"final": final_text},
            round_id=round_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_id=agent_id,
            prompt_version=prompt_version,
            model_version=model_version,
            decode_params=decode_params,
        )
        self._append_jsonl(record)

    def append_kpi(self, kpi: Dict):
        """KPI 情報を Markdown と JSON に保存する。"""

        if self.md:
            with self.md.open("a", encoding="utf-8", newline="\n") as f:
                f.write("\n=== KPI ===\n")
                for key, value in kpi.items():
                    f.write(f"- {key}: {value}\n")
                f.flush()
        (self.dir / "kpi.json").write_text(
            json.dumps(kpi, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_warning(
        self,
        message: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        round_id: Optional[int] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_version: Optional[str] = None,
        decode_params: Optional[Dict[str, Any]] = None,
        phase_id: Optional[int] = None,
        phase_turn: Optional[int] = None,
        phase_kind: Optional[str] = None,
        phase_base: Optional[int] = None,
    ) -> None:
        """警告情報を JSONL ログへ追記する。"""

        record = self._create_record(
            "warning",
            {"message": message},
            round_id=round_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_id=agent_id,
            prompt_version=prompt_version,
            model_version=model_version,
            decode_params=decode_params,
            phase_id=phase_id,
            phase_turn=phase_turn,
            phase_kind=phase_kind,
            phase_base=phase_base,
        )
        if context:
            record["context"] = context
        self._append_jsonl(record)

    def _append_jsonl(self, record: Dict[str, Any]) -> None:
        """JSONL ログへの追記を共通化する。"""

        if not self.jsonl or not self.enable_jsonl:
            return
        with self.jsonl.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def _create_record(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        round_id: Optional[int] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_version: Optional[str] = None,
        decode_params: Optional[Dict[str, Any]] = None,
        phase_id: Optional[int] = None,
        phase_turn: Optional[int] = None,
        phase_kind: Optional[str] = None,
        phase_base: Optional[int] = None,
    ) -> Dict[str, Any]:
        """JSONL レコードを共通形式で生成する。"""

        record: Dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "run_id": self.run_id,
            "round_id": round_id,
            "span_id": span_id or self.new_span_id(),
            "parent_span_id": parent_span_id,
            "agent_id": agent_id,
            "prompt_version": prompt_version,
            "model_version": model_version,
            "decode_params": dict(decode_params) if isinstance(decode_params, dict) else {},
            "phase_id": phase_id,
            "phase_turn": phase_turn,
            "phase_kind": phase_kind,
            "phase_base": phase_base,
        }
        record.update(payload)
        return record

    def new_span_id(self) -> str:
        """連番付きのスパンIDを採番する。"""

        self._span_counter += 1
        return f"span-{self._span_counter:06d}"


__all__ = ["LiveLogWriter"]
