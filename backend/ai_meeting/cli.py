"""CLI 用ユーティリティ。"""
from __future__ import annotations

import argparse
import os
import warnings
from typing import Dict, List, Optional, Union

from backend.defaults import DEFAULT_AGENT_NAMES

from .config import AgentConfig, MeetingConfig
from .utils import clamp
from .meeting import Meeting


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析して `argparse.Namespace` を返す。"""

    ap = argparse.ArgumentParser(description="CLI AI Meeting (multi-agent)")
    ap.add_argument("--topic", required=True, help="会議テーマ（日本語OK）")
    ap.add_argument("--precision", type=int, default=5, help="1=発散寄り, 10=厳密寄り")
    ap.add_argument(
        "--agents",
        nargs="+",
        default=list(DEFAULT_AGENT_NAMES),
        help="参加者を列挙。'名前=systemプロンプト' 形式もOK（例: Alice='仕様を詰める' Bob='実装に落とす'）",
    )
    ap.add_argument(
        "--rounds",
        type=int,
        default=None,
        help="非推奨: phase_turn_limit の全体値として解釈されます",
    )
    ap.add_argument("--max-phases", type=int, default=None, help="フェーズ総数の上限")
    ap.add_argument(
        "--phase-turn-limit",
        action="append",
        default=[],
        metavar="VALUE",
        help="フェーズターン上限。整数または kind=数値 形式を複数指定",
    )
    ap.add_argument(
        "--phase-goal",
        action="append",
        default=[],
        metavar="TEXT",
        help="フェーズ目標。'kind=説明' 形式または単一文字列で共通設定",
    )
    ap.add_argument("--backend", choices=["openai", "ollama"], default="ollama")
    ap.add_argument("--openai-model", default=None)
    ap.add_argument("--ollama-model", default=None)
    ap.add_argument("--ollama-url", default=None, help="Ollama のベースURL（例: http://127.0.0.1:11434）")
    ap.add_argument(
        "--no-resolve-round",
        dest="resolve_round",
        action="store_false",
        help="最後の“残課題消化ラウンド”を無効化する",
    )
    # 短文チャット（既定ON。OFFにしたいときだけ指定）
    ap.add_argument(
        "--no-chat-mode",
        dest="chat_mode",
        action="store_false",
        help="短文チャットモードを無効化する",
    )
    ap.add_argument("--chat-max-sentences", type=int, default=2)
    ap.add_argument("--chat-max-chars", type=int, default=120)
    ap.add_argument("--chat-window", type=int, default=2)
    ap.add_argument("--outdir", default=None, help="ログ出力先ディレクトリ（未指定なら自動生成）")
    ap.add_argument(
        "--summary-probe",
        dest="summary_probe_enabled",
        action="store_true",
        help="要約プローブを有効化して補助JSONを保存（暫定機能）",
    )
    ap.add_argument(
        "--summary-probe-log",
        dest="summary_probe_log_enabled",
        action="store_true",
        help="要約プローブ結果を毎ターンJSONLへ保存（暫定）",
    )
    ap.add_argument(
        "--summary-probe-filename",
        default="summary_probe.json",
        help="要約プローブの出力ファイル名（暫定）",
    )
    # 以降のステップ用（Step 0では未使用。フラグだけ受ける）
    ap.add_argument(
        "--equilibrium",
        action="store_true",
        help="均衡AI（メタ評価）を有効化（Step 0では未使用）",
    )
    ap.add_argument(
        "--shock",
        choices=["off", "random", "explore", "exploit"],
        default="off",
        help="ショック注入モード（Step 0では未使用）",
    )
    ap.add_argument("--shock-ttl", type=int, default=2, help="ショック効果を維持するターン数")
    # Step 3
    ap.add_argument("--cooldown", type=float, default=0.10)
    ap.add_argument("--cooldown-span", type=int, default=1)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--select-temp", type=float, default=0.7)
    ap.add_argument("--sim-window", type=int, default=6)
    ap.add_argument("--sim-penalty", type=float, default=0.25)
    # Step 4
    ap.add_argument(
        "--monitor",
        action="store_true",
        help="監視AI（フェーズ自動判定）を有効化（裏方のみ）",
    )
    ap.add_argument("--phase-window", type=int, default=8)
    ap.add_argument("--phase-cohesion-min", type=float, default=0.70)
    ap.add_argument("--phase-unresolved-drop", type=float, default=0.25)
    ap.add_argument("--phase-loop-threshold", type=int, default=3)
    # 思考→審査→発言
    ap.add_argument("--no-think-mode", dest="think_mode", action="store_false")
    ap.add_argument("--no-think-debug", dest="think_debug", action="store_false")
    # Step 7
    ap.add_argument("--kpi-window", type=int, default=6)
    ap.add_argument("--no-kpi-auto-prompt", dest="kpi_auto_prompt", action="store_false")
    ap.add_argument("--no-kpi-auto-tune", dest="kpi_auto_tune", action="store_false")
    ap.add_argument("--th-diversity-min", type=float, default=0.55)
    ap.add_argument("--th-decision-min", type=float, default=0.40)
    ap.add_argument("--th-progress-stall", type=int, default=3)
    ap.add_argument(
        "--ui-full",
        dest="ui_minimal",
        action="store_false",
        help="従来の見出し・役職ラベルを表示（台本風UIに戻す）",
    )
    return ap.parse_args()


def build_agents(tokens: List[str]) -> List[AgentConfig]:
    """エージェント設定を CLI 引数から構築する。"""

    agents: List[AgentConfig] = []
    default_system = (
        "あなたは会議参加者です。日本語で短く発言し、直前の内容に具体的に応答し、"
        "次の一手を提示してください。見出し/箇条書き/長い前置きは禁止"
    )
    for raw_token in tokens:
        raw = raw_token.strip()
        if "=" in raw:
            name, system = raw.split("=", 1)
            agents.append(AgentConfig(name=name.strip(), system=system.strip()))
        else:
            agents.append(AgentConfig(name=raw, system=default_system))
    return agents


def _parse_phase_turn_limit(tokens: List[str]) -> Optional[Union[int, Dict[str, int]]]:
    """フェーズ上限の指定文字列を解析する。"""

    if not tokens:
        return None
    scalar: Optional[int] = None
    mapping: Dict[str, int] = {}
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            key = key.strip()
            try:
                mapping[key] = max(0, int(value.strip()))
            except ValueError as exc:  # noqa: PERF203 - わかりやすいエラーメッセージ優先
                raise ValueError(f"phase-turn-limit の値が数値ではありません: {token}") from exc
        else:
            try:
                scalar = max(0, int(token))
            except ValueError as exc:  # noqa: PERF203
                raise ValueError(f"phase-turn-limit の値が数値ではありません: {token}") from exc
    if mapping:
        if scalar is not None:
            mapping.setdefault("default", scalar)
        return mapping
    return scalar


def _parse_phase_goal(tokens: List[str]) -> Optional[Union[str, Dict[str, str]]]:
    """フェーズ目標を解析し、文字列または辞書へ変換する。"""

    if not tokens:
        return None
    mapping: Dict[str, str] = {}
    default_text: Optional[str] = None
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            mapping[key.strip()] = value.strip()
        else:
            default_text = token
    if mapping:
        if default_text:
            mapping.setdefault("default", default_text)
        return mapping
    return default_text


def main() -> None:
    """CLI エントリーポイント。"""

    args = parse_args()
    agents = build_agents(args.agents)
    try:
        phase_limit = _parse_phase_turn_limit(getattr(args, "phase_turn_limit", []))
    except ValueError as exc:
        raise SystemExit(str(exc))
    phase_goal = _parse_phase_goal(getattr(args, "phase_goal", []))

    rounds_value = getattr(args, "rounds", None)
    if rounds_value is not None:
        warnings.warn("--rounds は非推奨です。phase_turn_limit に読み替えます。", DeprecationWarning)
        if phase_limit is None:
            phase_limit = max(0, int(rounds_value))

    cfg = MeetingConfig(
        topic=args.topic,
        precision=clamp(args.precision, 1, 10),
        rounds=rounds_value,
        max_phases=args.max_phases,
        phase_turn_limit=phase_limit,
        phase_goal=phase_goal,
        agents=agents,
        backend_name=args.backend,
        openai_model=args.openai_model or os.getenv("OPENAI_MODEL"),
        ollama_model=args.ollama_model or os.getenv("OLLAMA_MODEL"),
        ollama_url=args.ollama_url or os.getenv("OLLAMA_URL"),
        resolve_round=getattr(args, "resolve_round", True),
        chat_mode=getattr(args, "chat_mode", True),
        chat_max_sentences=args.chat_max_sentences,
        chat_max_chars=args.chat_max_chars,
        chat_window=args.chat_window,
        outdir=getattr(args, "outdir", None),
        equilibrium=getattr(args, "equilibrium", False),
        monitor=getattr(args, "monitor", False),
        shock=getattr(args, "shock", "off"),
        shock_ttl=max(1, int(getattr(args, "shock_ttl", 2))),
        ui_minimal=getattr(args, "ui_minimal", True),
        cooldown=max(0.0, float(getattr(args, "cooldown", 0.10))),
        cooldown_span=max(0, int(getattr(args, "cooldown_span", 1))),
        topk=max(1, int(getattr(args, "topk", 3))),
        select_temp=max(0.05, float(getattr(args, "select_temp", 0.7))),
        sim_window=max(0, int(getattr(args, "sim_window", 6))),
        sim_penalty=max(0.0, float(getattr(args, "sim_penalty", 0.25))),
        phase_window=max(1, int(getattr(args, "phase_window", 8))),
        phase_cohesion_min=min(1.0, max(0.0, float(getattr(args, "phase_cohesion_min", 0.70)))),
        phase_unresolved_drop=min(1.0, max(0.0, float(getattr(args, "phase_unresolved_drop", 0.25)))),
        phase_loop_threshold=max(1, int(getattr(args, "phase_loop_threshold", 3))),
        think_mode=getattr(args, "think_mode", True),
        think_debug=getattr(args, "think_debug", True),
        summary_probe_enabled=getattr(args, "summary_probe_enabled", False),
        summary_probe_log_enabled=getattr(args, "summary_probe_log_enabled", False),
        summary_probe_filename=getattr(args, "summary_probe_filename", "summary_probe.json"),
    )
    cfg.kpi_window = max(1, int(getattr(args, "kpi_window", 6)))
    cfg.kpi_auto_prompt = getattr(args, "kpi_auto_prompt", True)
    cfg.kpi_auto_tune = getattr(args, "kpi_auto_tune", True)
    cfg.th_diversity_min = max(0.0, float(getattr(args, "th_diversity_min", 0.55)))
    cfg.th_decision_min = max(0.0, float(getattr(args, "th_decision_min", 0.40)))
    cfg.th_progress_stall = max(1, int(getattr(args, "th_progress_stall", 3)))

    Meeting(cfg).run()
