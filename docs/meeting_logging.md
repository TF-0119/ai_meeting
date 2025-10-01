# Meeting ログと検証用サンプル

## LiveLogWriter が生成するファイル
- `meeting_live.md`: UI最小化モードでは「Topic」「Final」などの見出しのみを付けて逐次の発言・要約・最終結論を書き込むMarkdownログ。各ラウンド要約は `（要約）...` 形式、最終セクションは `【Final】` 見出しで追記される。【F:backend/ai_meeting/logging.py†L14-L139】
- `meeting_live.jsonl`: 各発言・要約・最終決定を `ts/type/round/turn/speaker/content` などのキーで1行JSONとして蓄積するライブログ。`type` は `"turn"`/`"summary"`/`"final"` をとる。【F:backend/ai_meeting/logging.py†L14-L139】
- `phases.jsonl`: 監視AI（Monitor）がフェーズ確定時に書き出すメタ情報。本文には挿入せず、`cohesion` や `phase_id` などの裏方データのみをJSONLで保持する。【F:backend/ai_meeting/logging.py†L23-L70】【F:backend/ai_meeting/meeting.py†L420-L437】
- `thoughts.jsonl`: 思考→審査フローを有効化した場合に、各ラウンドの全エージェント思考と審査結果を格納するデバッグ用ログ。【F:backend/ai_meeting/logging.py†L24-L77】【F:backend/ai_meeting/meeting.py†L297-L320】
- `control.jsonl`: KPIフィードバックが閾値を下回った際に自動生成される制御ログ。`type="kpi_control"` に各種指標とヒントを付与して保存する。【F:backend/ai_meeting/logging.py†L79-L84】【F:backend/ai_meeting/meeting.py†L448-L468】
- `kpi.json`: 会議終了時のKPI指標（progress/diversity/decision_density/spec_coverage）をJSONで保存し、同時にMarkdownにも反映する。【F:backend/ai_meeting/logging.py†L128-L139】【F:backend/ai_meeting/meeting.py†L531-L537】
- `meeting_live.html`: 将来のHTMLビューア用にパスだけ予約されているが、現状は未書き込み。`LiveLogWriter` 初期化時にファイルパスが確保される。【F:backend/ai_meeting/logging.py†L14-L43】

## MetricsLogger が生成するファイル
- `metrics.csv`: サンプリング時刻・CPU/RAM・GPU各種指標（利用率、VRAM使用量、温度、電力）を列として追記するCSV。`stop()` 時にこの内容を参照してグラフ生成を試みる。【F:backend/ai_meeting/metrics.py†L17-L93】【F:backend/ai_meeting/meeting.py†L559-L564】
- `metrics_cpu_mem.png` / `metrics_gpu.png`: `metrics.csv` を読み取り `matplotlib` でCPU/RAM曲線、GPU関連曲線を描画したPNG。ライブラリが無い環境では例外が握りつぶされるため未生成の場合もある。【F:backend/ai_meeting/metrics.py†L94-L148】

## Meeting.run の最終成果物
- `meeting_result.json`: 会議設定（topic/precision/rounds/agents）と全ターンの発言、最終結論をまとめたJSON。CLI実行時の成果物として `logs/<タイムスタンプ_トピック>/` 直下に保存される。【F:backend/ai_meeting/meeting.py†L542-L564】
- 上記以外にもCLI標準出力ではライブログの保存先とメトリクスファイル名が案内される。【F:backend/ai_meeting/meeting.py†L541-L564】

## 代表的なCLI実行例とサンプル
以下のコマンドを実行すると、スタブOpenAIバックエンドを利用した2ラウンドの会議が `logs/sample_cli_run/` に出力される。

```bash
python -m backend.ai_meeting \
  --topic "社内ハッカソンの準備" \
  --rounds 2 \
  --precision 5 \
  --agents Alice Bob Carol \
  --backend openai \
  --outdir logs/sample_cli_run
```

生成された成果物は回帰用サンプルとして `docs/samples/basic_cli_run/` にコピーしている。各ファイルの冒頭は以下のとおり:

- `meeting_live.md`: 会議トピック、各発言、最終セクションをMarkdownで記録。【F:docs/samples/basic_cli_run/meeting_live.md†L1-L40】
- `meeting_live.jsonl`: 発言 (`type="turn"`)、要約 (`type="summary"`)、最終決定 (`type="final"`) のイベントログ。【F:docs/samples/basic_cli_run/meeting_live.jsonl†L1-L6】
- `meeting_result.json`: 設定・履歴・最終合意の全体スナップショット。【F:docs/samples/basic_cli_run/meeting_result.json†L1-L48】
- `kpi.json`: KPI指標の数値例。【F:docs/samples/basic_cli_run/kpi.json†L1-L6】
- `metrics.csv`: スタブpsutilによるCPU/RAMサンプル値のスナップショット。【F:docs/samples/basic_cli_run/metrics.csv†L1-L4】
- `thoughts.jsonl`: 各ラウンドの思考・審査・勝者情報。【F:docs/samples/basic_cli_run/thoughts.jsonl†L1-L2】

## 回帰テストで網羅したい主要フラグ組み合わせ
| ケース | think_mode | think_debug | kpi_auto_prompt | kpi_auto_tune | shock | monitor | 目的 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A: ベースライン | 有効 | 有効 | 有効 | 有効 | off | 無効 | 既定動作と標準ログ生成の確認 |
| B: KPIヒント停止 | 有効 | 無効 | 無効 | 有効 | off | 無効 | `control.jsonl` の非出力とKPI自動調整のみを確認 |
| C: ショック探索 | 有効 | 有効 | 有効 | 有効 | explore | 無効 | ショックモードによる選択温度・ペナルティ調整を検証 |
| D: 監視AIあり | 有効 | 有効 | 有効 | 有効 | random | 有効 | `phases.jsonl` 生成とショック寿命の連動確認 |
| E: 思考なしモード | 無効 | 無効 | 有効 | 無効 | exploit | 無効 | 旧来の発言生成フローと`thoughts.jsonl`非生成の確認 |

- `think_mode`/`think_debug`/`shock`/`monitor` は CLI で直接指定可能な主要スイッチであり、ログ生成パスや補助ファイル出力の有無が変わる。【F:backend/ai_meeting/cli.py†L37-L93】【F:backend/ai_meeting/meeting.py†L297-L468】
- KPI系フラグを無効化した場合は `control.jsonl` への書き込みや自動チューニング分岐がスキップされるため、ケースB/Eでその挙動差をカバーする。【F:backend/ai_meeting/meeting.py†L448-L468】【F:backend/ai_meeting/controllers.py†L87-L145】
- ショックモードは `shock` 引数で `random/explore/exploit` を選べ、フェーズ確定時にクールダウンや選択温度へ影響するためケースC/Dで確認する。【F:backend/ai_meeting/meeting.py†L420-L466】【F:backend/ai_meeting/controllers.py†L160-L195】
