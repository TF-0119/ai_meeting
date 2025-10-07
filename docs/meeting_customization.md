# 会議カスタマイズガイド

本ドキュメントでは、`backend/ai_meeting/cli.py` が公開している CLI 引数を整理し、利用者向けのカテゴリ分け・依存関係・既定値・想定 UI をまとめる。また、新しい会議起動リクエスト形式の案と `backend/app.py` の `StartMeetingIn` への反映方法についても提案する。

## CLI 引数の分類一覧

### 基本
| 引数 | 説明 | 既定値 | 備考 / 依存関係 |
| --- | --- | --- | --- |
| `--topic` | 会議テーマ。必須。 | なし | 未入力不可。UI ではテキストボックスで入力。 |
| `--precision` | 思考の厳密度 (1=発散寄り, 10=厳密寄り)。 | `5` | スライダーまたはステッパーで 1-10 を選択。 |
| `--agents` | 参加者名および任意の system プロンプト。 | 既定参加者 (`backend.defaults.DEFAULT_AGENT_NAMES`) | マルチセレクト＋追加入力欄。空集合はエラー。 |
| `--backend` | 利用する LLM バックエンド。 | `ollama` | ラジオボタン。`openai` を選んだ場合は追加設定が必要。 |
| `--rounds` | (非推奨) 会議全体のターン上限。 | `None` | 指定時は `phase_turn_limit` に読み替え。UI では非推奨表示。 |
| `--outdir` | ログ出力先ディレクトリ。 | 自動生成 | ファイルパス指定。未指定時はタイムスタンプ付きフォルダ。 |

### 上級
| 引数 | 説明 | 既定値 | 備考 / 依存関係 |
| --- | --- | --- | --- |
| `--max-phases` | フェーズ総数の上限。 | `None` | 数値入力。未指定で無制限。 |
| `--phase-turn-limit` | フェーズごとのターン上限。 | 参加者数×2 と `phase_window` (初期値8) の大きい方 | 複数指定可。UI ではリスト入力＋フェーズ種別タグ。 |
| `--phase-goal` | フェーズ目標文。 | `None` | `kind=説明` 形式または単一文字列。UI はタグ付きテキスト。 |
| `--openai-model` | OpenAI バックエンド使用時のモデル名。 | 環境変数 `OPENAI_MODEL` | `--backend openai` 時のみ有効。 |
| `--ollama-model` | Ollama バックエンド使用時のモデル名。 | 環境変数 `OLLAMA_MODEL` | `--backend ollama` 時のみ有効。 |
| `--ollama-url` | Ollama のベース URL。 | 環境変数 `OLLAMA_URL` | UI では接続設定画面に配置。 |
| `--resolve-round` / `--no-resolve-round` | 残課題消化ラウンドの有効/無効。 | `True` | トグルスイッチ。 |
| `--chat-mode` / `--no-chat-mode` | 短文チャットモード。 | `True` | トグル。無効化時は詳細設定も無効に。 |
| `--chat-max-sentences` | チャット発言の最大文数。 | `2` | `chat_mode=True` のときのみ編集可能。 |
| `--chat-max-chars` | チャット発言の最大文字数。 | `120` | 同上。 |
| `--chat-window` | チャット履歴の参照件数。 | `2` | 同上。 |
| `--agent-memory-limit` | 覚書保持の上限件数。 | `MeetingConfig` の既定値 | 数値入力。`None` で既定値。 |
| `--agent-memory-window` | プロンプトに含める覚書数。 | `MeetingConfig` の既定値 | 数値入力。 |
| `--shock` | ショック注入モード。 | `off` | セレクトボックス。 | 
| `--shock-ttl` | ショック効果の持続ターン。 | `2` | `shock != off` の場合のみ編集。 |
| `--cooldown` | 評価クールダウン係数。 | `0.10` | 数値入力 (0 以上)。 |
| `--cooldown-span` | クールダウンを維持するターン数。 | `1` | 整数入力 (0 以上)。 |
| `--topk` | 思考候補の採用数。 | `3` | 整数入力 (1 以上)。 |
| `--select-temp` | 候補選択の温度。 | `0.7` | 0.05 以上。 |
| `--sim-window` | 類似度評価対象のターン幅。 | `6` | 整数入力 (0 以上)。 |
| `--sim-penalty` | 類似度ペナルティ係数。 | `0.25` | 数値入力 (0 以上)。 |
| `--phase-window` | フェーズ監視の参照幅。 | `8` | 整数入力 (1 以上)。 |
| `--phase-cohesion-min` | フェーズ結束度の下限。 | `0.70` | 0-1 の範囲。スライダー。 |
| `--phase-unresolved-drop` | 未解決課題率の許容低下。 | `0.25` | 0-1 の範囲。 |
| `--phase-loop-threshold` | フェーズループ検知閾値。 | `3` | 整数入力 (1 以上)。 |
| `--think-mode` / `--no-think-mode` | 思考ステップの有効/無効。 | `True` | トグル。無効化で自動評価が変化。 |
| `--think-debug` / `--no-think-debug` | 思考ログの詳細出力。 | `True` | トグル。 |
| `--ui-full` / `--ui-minimal` | UI 表示モード。 | `ui_minimal=True` | フロントエンドのレイアウト切替。 |
| `--kpi-window` | KPI 算出の参照幅。 | `6` | 整数入力 (1 以上)。 |
| `--kpi-auto-prompt` / `--no-kpi-auto-prompt` | KPI に基づくプロンプト改善。 | `True` | トグル。 |
| `--kpi-auto-tune` / `--no-kpi-auto-tune` | KPI に基づく自動調整。 | `True` | トグル。 |
| `--th-diversity-min` | 多様性評価の下限。 | `0.55` | 0 以上。 |
| `--th-decision-min` | 意思決定評価の下限。 | `0.40` | 0 以上。 |
| `--th-progress-stall` | 進捗停滞とみなすターン数。 | `3` | 整数入力 (1 以上)。 |

### 要検証 / 実験的
| 引数 | 説明 | 既定値 | 備考 / 依存関係 |
| --- | --- | --- | --- |
| `--summary-probe` | 要約プローブを有効化。 | `False` | 補助 JSON を出力。実験機能。 |
| `--summary-probe-log` | 要約プローブのターンごとの JSONL 出力。 | `False` | `summary_probe_enabled` と併用推奨。 |
| `--summary-probe-filename` | 要約プローブ出力ファイル名。 | `summary_probe.json` | `summary_probe_enabled` 時のみ利用。 |
| `--equilibrium` | 均衡 AI (メタ評価) を有効化。 | `False` | Step 0 では未使用。将来機能。 |
| `--monitor` / `--no-monitor` | フェーズ自動判定 AI。 | `True` | 既定で有効。`--no-monitor` で無効化。背景処理のみ。UI では「実験的」ラベル。 |

## 各設定項目の詳細

- **フェーズ関連 (`--max-phases`, `--phase-turn-limit`, `--phase-goal`)**
  - フェーズ種別ごとのターン上限や目標文を設定できる。`kind=` プレフィックス付きで複数指定した場合は辞書に展開される。未指定時は参加者数×2 と `phase_window` (初期値8) の大きい方（最低6）に自動設定される。
  - 想定 UI: 「フェーズ種別」タグとターン/目標のペアを追加するフォーム。

- **チャットモード (`--chat-mode` 系)**
  - `--no-chat-mode` を指定しない限り短文チャットで進行する。チャット関連の細かい閾値は `chat_mode=True` の場合のみ有効。
  - 想定 UI: トグルスイッチと連動して関連スライダーや入力欄を活性/非活性化。

- **LLM バックエンド (`--backend`, `--openai-model`, `--ollama-model`, `--ollama-url`)**
  - バックエンドに応じたモデル名と URL を指定する。未指定時は環境変数 (`OPENAI_MODEL`, `OLLAMA_MODEL`, `OLLAMA_URL`) を利用。
  - 想定 UI: 「接続設定」セクションにバックエンド固有のフィールドを表示。

- **評価パラメータ (`--cooldown` 系, `--topk`, `--select-temp`, `--sim-window`, `--sim-penalty`)**
  - 思考候補の評価や選定に関わる調整値。数値範囲は `MeetingConfig` 作成時にクリップされる。
  - 想定 UI: スライダーや数値入力に加え、ツールチップで推奨範囲を案内。

- **KPI および進捗監視 (`--kpi-window` 以降)**
  - KPI に基づく自動改善や閾値が含まれる。`--no-kpi-auto-*` で無効化可能。
  - 想定 UI: 「進捗モニタリング」セクション。トグルと数値入力を用意。

- **実験機能 (`--summary-probe*`, `--equilibrium`, `--monitor`)**
  - 現行実装ではログ出力やフラグの受付のみ。UI では「ベータ版」「実験的」と明示する。

## 新しいリクエストフォーマット案

既存の `/meetings` エンドポイントは `StartMeetingIn` に合わせた平坦な JSON を受け付ける。将来的に CLI オプションを網羅的に指定できるよう、以下の階層化されたリクエストフォーマットを提案する。

```json
{
  "topic": "AI アプリ構成のレビュー",
  "options": {
    "llm": {
      "backend": "ollama",
      "openai": { "model": "gpt-4o-mini" },
      "ollama": { "model": "llama3", "url": "http://127.0.0.1:11434" }
    },
    "flow": {
      "precision": 5,
      "rounds": 4,
      "maxPhases": null,
      "phaseTurnLimit": { "default": 6, "design": 4 },
      "phaseGoal": { "default": "成果の整理" }
    },
    "interaction": {
      "chat": {
        "enabled": true,
        "maxSentences": 2,
        "maxChars": 120,
        "window": 2
      },
      "agents": [
        "Alice=仕様を詰める",
        "Bob=実装に落とす"
      ]
    },
    "monitoring": {
      "resolveRound": true,
      "summaryProbe": {
        "enabled": false,
        "log": false,
        "filename": "summary_probe.json"
      },
      "kpi": {
        "window": 6,
        "autoPrompt": true,
        "autoTune": true,
        "threshold": {
          "diversityMin": 0.55,
          "decisionMin": 0.40,
          "progressStall": 3
        }
      }
    }
  }
}
```

- `topic` は従来通り必須のトップレベル項目とし、UI の「会議テーマ」入力に対応する。
- `options.llm.backend` の値に応じて `options.llm.openai` または `options.llm.ollama` サブツリーを参照する。
- CLI で複数指定を受け付けるパラメータ（例: `phaseTurnLimit`, `phaseGoal`, `agents`）は、配列または辞書形式で表現する。

## `StartMeetingIn` への反映方針

`backend/app.py` の `StartMeetingIn` は現在、CLI ラッパーを呼び出すための最小限のフィールドのみを持つ。上記フォーマットへ対応させるには、次のステップを推奨する。

1. **Pydantic モデルの階層化**
   - `StartMeetingIn` に代わり、`MeetingOptions` のようなサブモデル (`LLMOptions`, `FlowOptions`, `InteractionOptions`, `MonitoringOptions`) を定義する。
   - 既存フィールド (`topic`, `precision`, `rounds`, `agents`, `backend`, `outdir`) は後方互換のためトップレベルでも受け付け、`options` が存在する場合は `options` を優先して統合する。

2. **正規化関数の追加**
   - `StartMeetingIn` の `model_post_init` もしくは `@root_validator`（Pydantic v2 の `model_validator`）で、階層化された値を CLI 引数に変換する辞書 (`flattened_options`) を生成する。
   - 例: `options.llm.backend` → `backend`, `options.flow.phaseTurnLimit` → `phase_turn_limit`（辞書は CLI 想定のトークン列に変換）。

3. **CLI 呼び出し部の調整**
   - `cmd_list` の生成において、旧フィールドが存在すれば従来通り追加し、`options` からの派生値も同様に追加する。競合時は `options` を優先。
   - 配列・辞書項目は `--phase-turn-limit kind=value` の形式へエンコードするユーティリティ関数を用意する。

4. **後方互換性テスト**
   - 既存の単純リクエスト (`StartMeetingIn` の旧 JSON) が引き続き動作するかをテスト。
   - 新フォーマットを用いたテストケースを追加し、CLI 呼び出しに期待通り変換されることを検証する。

これらの変更により、フロントエンドは `options.*` の構造化された設定画面をそのままバックエンドへ送信でき、将来的なパラメータ追加にも柔軟に対応できる。
