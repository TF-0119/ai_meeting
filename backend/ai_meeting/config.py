"""会議設定やエージェント設定に関するデータモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


def clamp(value: float, lower: float, upper: float) -> float:
    """値を下限・上限で挟み込む。"""

    return max(lower, min(upper, value))


class AgentConfig(BaseModel):
    """各会議参加エージェントの設定。"""

    name: str
    system: str
    style: str = ""  # 口調など任意
    reveal_think: bool = False  # trueだと“思考ログ”も表示（研修用）


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
    rounds: int = 4
    agents: List[AgentConfig]
    backend_name: Literal["openai", "ollama"] = "ollama"
    openai_model: Optional[str] = None
    ollama_model: Optional[str] = None
    max_tokens: int = 800
    resolve_round: bool = True  # 最後に「残課題消化ラウンド」を自動挿入
    # --- 短文チャット（既定ON） ---
    chat_mode: bool = True
    chat_max_sentences: int = 2
    chat_max_chars: int = 120
    chat_window: int = 2  # 直近何発言を見せるか
    # --- 以降のステップ用プレースホルダ（Step 0では未使用） ---
    equilibrium: bool = False  # 均衡AI（メタ評価）
    monitor: bool = False  # 監視AI（フェーズ検知）
    shock: Literal["off", "random", "explore", "exploit"] = "off"  # ショック注入モード
    shock_ttl: int = 2  # ショックを維持するターン数（フェーズ確定後の有効ターン）
    # --- Step 1: UI最小化（台本感を消す表示） ---
    ui_minimal: bool = True  # 役職やRound見出しを出さない
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
    # --- Step 7: KPIフィードバック制御 ---
    kpi_window: int = 6  # 直近W発言でミニKPIを算出
    kpi_auto_prompt: bool = True  # 閾値割れで隠しプロンプトを注入
    kpi_auto_tune: bool = True  # 閾値割れでパラメータ自動調整
    th_diversity_min: float = 0.55  # 多様性の下限（下回ると発散要求）
    th_decision_min: float = 0.40  # 決定密度の下限（下回ると担当/期限を強制）
    th_progress_stall: int = 3  # 未解決がW中ずっと横ばい/悪化なら収束促進

    outdir: Optional[str] = None  # ログ出力先。未指定なら自動で logs/<日時_トピック> を作成

    def runtime_params(self) -> Dict[str, Union[float, int]]:
        """precision に応じた温度やクリティーク回数を算出する。"""

        p = self.precision
        temperature = clamp(1.1 - (p / 10) * 0.8, 0.2, 1.0)  # p↑で温度↓
        critique_passes = clamp(int(round((p / 10) * 2)), 0, 2)  # 0~2回
        return {"temperature": temperature, "critique_passes": critique_passes}
