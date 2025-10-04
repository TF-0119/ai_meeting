"""会議設定やエージェント設定に関するデータモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .utils import clamp


class AgentConfig(BaseModel):
    """各会議参加エージェントの設定。"""

    name: str
    system: str
    style: str = ""  # 口調など任意
    reveal_think: bool = False  # trueだと“思考ログ”も表示（研修用）
    memory: List[str] = Field(default_factory=list, description="エージェント固有の覚書リスト")


@dataclass
class Turn:
    """会議内の1発言を表すデータ構造。"""

    speaker: str
    content: str
    meta: Dict = field(default_factory=dict)


class MeetingConfig(BaseModel):
    """会議全体に関する設定値。"""

    topic: str = Field(..., description="会議テーマ（1文）")
    precision: int = Field(5, ge=1, le=10, description="精密性(1=発散, 10=厳密)")
    max_phases: Optional[int] = Field(
        None,
        ge=1,
        description="全体で許容するフェーズ数の上限。Noneなら制限なし",
    )
    phase_turn_limit: Optional[Union[int, Dict[str, int]]] = Field(
        None,
        description="各フェーズのターン数上限（intで共通・dictで種類別、未設定なら自動導出）",
    )
    phase_goal: Optional[Union[str, Dict[str, str]]] = Field(
        None, description="フェーズごとの目的（'discussion=議題整理' のように指定）"
    )
    agents: List[AgentConfig]
    backend_name: Literal["openai", "ollama"] = "ollama"
    openai_model: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_url: Optional[str] = None
    max_tokens: int = 800
    resolve_phase: bool = True  # 最後に「残課題消化フェーズ」を自動挿入
    # --- 短文チャット（既定ON） ---
    chat_mode: bool = True
    chat_max_sentences: int = 2
    chat_max_chars: int = 120
    chat_window: int = 2  # 直近何発言を見せるか
    chat_context_summary: bool = True  # サマリーをチャット文脈に注入するか
    # --- 以降のステップ用プレースホルダ（Step 0では未使用） ---
    equilibrium: bool = False  # 均衡AI（メタ評価）
    monitor: bool = False  # 監視AI（フェーズ検知）
    shock: Literal["off", "random", "explore", "exploit"] = "off"  # ショック注入モード
    shock_ttl: int = 2  # ショックを維持するターン数（フェーズ確定後の有効ターン）
    # --- Step 1: UI最小化（台本感を消す表示） ---
    ui_minimal: bool = True  # 役職やRound見出しを出さない
    log_markdown_enabled: bool = True  # meeting_live.md を生成するかどうか
    log_jsonl_enabled: bool = True  # meeting_live.jsonl を生成するかどうか
    # --- Step 3: 多様性＆独占ガード ---
    cooldown: float = 0.10  # 直近発言者への減点（0.0-1.0）
    cooldown_span: int = 1  # 何ターン遡ってクールダウンを適用するか
    topk: int = 3  # 上位Kから抽選
    select_temp: float = 0.7  # ソフトマックス温度（小さいほど貪欲）
    sim_window: int = 6  # 類似度の参照ターン数（直近W）
    sim_penalty: float = 0.25  # 類似度ペナルティの係数（0.0-1.0）
    # --- Step 4: 監視AI + フェーズ自動判定（裏方のみ） ---
    phase_window: int = 8  # 直近W発言でまとまり度を判定
    phase_cohesion_min: float = 0.70  # フェーズ確定に必要な“まとまり度”下限（0-1）
    phase_unresolved_drop: float = 0.25  # 未解決が W 内でこの割合以上減ったらOK
    phase_loop_threshold: int = 3  # 高類似ループK回でフェーズ確定
    # ---- Step8前: 思考→審査→発言（T3→T1）MVP ----
    think_mode: bool = True  # 全員が非公開の「思考」を出してから発言者を決める
    think_debug: bool = True  # thoughts.jsonl に全思考・採点を保存（本文には出さない）
    think_judge_include_topic: bool = True  # 審査プロンプトにトピックを含めるか
    think_judge_include_recent: bool = True  # 審査プロンプトに直近発言の抜粋を含めるか
    think_judge_include_recent_summary: bool = True  # 審査プロンプトに直近要約を含めるか
    think_judge_include_flow_summary: bool = True  # 審査プロンプトに流れ要約を含めるか
    summary_probe_enabled: bool = False  # 要約プローブ（暫定）を有効化するかどうか
    summary_probe_log_enabled: bool = False  # 要約プローブ結果をログ保存するかどうか
    summary_probe_filename: str = "summary_probe.json"  # 要約プローブの出力ファイル名
    summary_probe_temperature: float = Field(
        0.4,
        ge=0.0,
        le=2.0,
        description="要約プローブ時に利用するLLM温度。",
    )
    summary_probe_max_tokens: int = Field(
        300,
        ge=32,
        le=2000,
        description="要約プローブに割り当てる最大トークン数。",
    )
    agent_memory_limit: int = Field(
        24,
        ge=0,
        description="各エージェントが保持できる覚書の上限数（0で無制限）",
    )
    agent_memory_window: int = Field(
        6,
        ge=0,
        description="プロンプトに注入する直近覚書の件数",
    )
    personality_seed: Optional[int] = Field(
        default=None,
        description="個性テンプレートの抽選に用いる乱数シード。指定がない場合は環境値やシステム既定を利用する。",
    )
    # --- Step 7: KPIフィードバック制御 ---
    kpi_window: int = 6  # 直近W発言でミニKPIを算出
    kpi_auto_prompt: bool = True  # 閾値割れで隠しプロンプトを注入
    kpi_auto_tune: bool = True  # 閾値割れでパラメータ自動調整
    th_diversity_min: float = 0.55  # 多様性の下限（下回ると発散要求）
    th_decision_min: float = 0.40  # 決定密度の下限（下回ると担当/期限を強制）
    th_progress_stall: int = 3  # 未解決がW中ずっと横ばい/悪化なら収束促進

    outdir: Optional[str] = None  # ログ出力先。未指定なら自動で logs/<日時_トピック> を作成

    model_config = {
        "validate_assignment": True,
    }

    def model_post_init(self, __context: Any) -> None:  # noqa: D401 - BaseModel規約
        """Pydantic初期化後にフェーズ関連の未設定値を補完する。"""

        # phase_turn_limit が未指定または0以下ならエージェント数から自動導出
        if self.phase_turn_limit in (None, 0):
            auto_limit = len(self.agents)
            self.phase_turn_limit = auto_limit if auto_limit > 0 else None
        elif isinstance(self.phase_turn_limit, int) and self.phase_turn_limit < 0:
            self.phase_turn_limit = None

        # dict指定時も負数が混ざっていれば除去
        if isinstance(self.phase_turn_limit, dict):
            normalized: Dict[str, int] = {}
            for key, value in self.phase_turn_limit.items():
                if isinstance(value, int) and value > 0:
                    normalized[key] = value
            self.phase_turn_limit = normalized or None

    def runtime_params(self) -> Dict[str, Union[float, int]]:
        """precision に応じた温度やクリティーク回数を算出する。"""

        p = self.precision
        temperature = clamp(1.1 - (p / 10) * 0.8, 0.2, 1.0)  # p↑で温度↓
        critique_passes = clamp(int(round((p / 10) * 2)), 0, 2)  # 0~2回
        return {"temperature": temperature, "critique_passes": critique_passes}

    def get_phase_turn_limit(self, kind: str = "discussion") -> Optional[int]:
        """フェーズ種別に応じてターン上限を決定する。"""

        value = self.phase_turn_limit
        if isinstance(value, dict):
            candidate = value.get(kind)
            if candidate is None:
                candidate = value.get("default")
            if candidate is None:
                candidate = value.get("discussion")
            if isinstance(candidate, int) and candidate > 0:
                return candidate
        elif isinstance(value, int) and value > 0:
            return value
        auto_limit = len(self.agents)
        if auto_limit > 0:
            return auto_limit
        return None

    @property
    def rounds(self) -> Optional[int]:
        """互換用途: 廃止予定のラウンド数アクセサ。"""

        return self.get_phase_turn_limit()

    def get_phase_goal(self, kind: str = "discussion") -> Optional[str]:
        """フェーズ種別に紐づく目標テキストを返す。"""

        goal = self.phase_goal
        if isinstance(goal, dict):
            text = goal.get(kind)
            if text is None:
                text = goal.get("default")
            if text is None:
                text = goal.get("discussion")
            return text
        if isinstance(goal, str):
            return goal
        return None
