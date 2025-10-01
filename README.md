# AI Meeting

## プロジェクト概要
AI Meeting は、大規模言語モデル (LLM) を複数名の参加者として協調させる会議シミュレーターです。バックエンドは Python 製の CLI スクリプトで、任意の名前とプロンプトを与えた参加者が議論し、ログや KPI を自動で記録します。フロントエンドは React/Vite 製の簡易ビューワーで、生成されたログをタイムライン形式で閲覧できます。

## 主な機能
- **マルチエージェント会議進行**：任意の参加者名とシステムプロンプトを組み合わせ、短文チャット制約の下で思考→審査→発言を繰り返し、ラウンド要約や残課題解消ラウンドも自動化されています。【F:backend/ai_meeting/config.py†L30-L85】【F:backend/ai_meeting/meeting.py†L281-L507】
- **ログ生成と分析**：`meeting_live.md` / `meeting_live.jsonl` / `meeting_result.json` をはじめ、CPU・GPU 利用率の時系列 (`metrics.csv` やグラフ画像) を保存します。【F:backend/ai_meeting/logging.py†L14-L139】【F:backend/ai_meeting/meeting.py†L541-L564】
- **KPI 評価とフィードバック**：議論の多様性・決定密度などを自動計測し、閾値割れ時にはプロンプトを調整する仕組みを備えています。【F:backend/ai_meeting/controllers.py†L87-L145】【F:backend/ai_meeting/evaluation.py†L10-L47】
- **フロントエンド表示**：生成ログをポーリングしてタイムライン・要約・KPI を表示する React UI を提供します。【F:frontend/src/pages/Meeting.jsx†L1-L96】【F:frontend/src/pages/Result.jsx†L8-L58】

> 🔰 **初心者向けガイド**
>
> フロントエンドの Home 画面と FastAPI の連携手順を噛み砕いて説明したメモを `docs/meeting_flow_for_beginners.md` にまとめました。フォーム送信から会議ログ表示までの流れをざっくり知りたいときに活用してください。【F:docs/meeting_flow_for_beginners.md†L1-L44】

## ディレクトリ構成
```text
ai_meeting/
├── backend/
│   ├── ai_meeting/     # Python パッケージ化された会議エンジン
│   │   ├── cli.py      # CLI 引数と main()
│   │   ├── meeting.py  # 進行ロジック本体
│   │   ├── testing.py  # 決定論的バックエンドなどテスト支援
│   │   └── ...
│   └── tests/          # CLI エンドツーエンドテスト
├── docs/               # 技術メモ・サンプルログ
├── frontend/           # React/Vite フロントエンド
├── scripts/            # CI 向け補助スクリプト
└── logs/               # 実行ごとのログ出力 (meeting_live.jsonl 等)
```

### Python パッケージとしての利用例

`backend.ai_meeting` はモジュール分割済みのパッケージとしても利用できます。CLI を呼ぶ代わりに、コード内で直接会議を実行したい場合は以下のようにします。

```python
from backend.ai_meeting import Meeting, MeetingConfig, build_agents

agents = build_agents(["Alice", "Bob"])
cfg = MeetingConfig(topic="1畳で遊べる新スポーツを仕様化", agents=agents)
Meeting(cfg).run()
```

オフラインの自動テストでは `AI_MEETING_TEST_MODE=deterministic` を環境変数に設定すると、`backend.ai_meeting.testing.DeterministicLLMBackend` が自動で差し替わり、外部 LLM なしで決定論的なログと KPI を得られます。

## バックエンドのセットアップと実行
1. Python 3.10 以上の環境を用意し、必要なパッケージをインストールします。Ollama を使う場合は `requests`、OpenAI を使う場合は `openai` が必要です。テストモードのみを動かす場合は `pydantic` と `psutil` があれば十分です。
   ```bash
   pip install pydantic psutil matplotlib pynvml GPUtil requests openai
   ```
   ※ `pynvml` や `GPUtil` は GPU 利用率を取得したいときのみ必須です。【F:backend/ai_meeting/metrics.py†L17-L93】
2. Ollama を利用する場合は `ollama run llama3` などでローカルサーバーを立ち上げておきます (既定は `http://localhost:11434`)。【F:backend/ai_meeting/llm.py†L55-L80】
3. OpenAI を利用する場合は `OPENAI_API_KEY` と必要なら `OPENAI_MODEL` を環境変数に設定します。【F:backend/ai_meeting/llm.py†L27-L52】
4. 会議を実行します。例：
   ```bash
   python backend/ai_meeting.py \
     --topic "1畳で遊べる新スポーツを仕様化" \
     --precision 6 \
     --agents Alice Bob Carol \
     --agents Alice Bob "Carol=議事録を即時に整理する" \
     --rounds 4 \
     --backend ollama
   ```
   実行すると `logs/<日時_トピック>/` 以下にログ一式が出力されます。

### 主要な CLI オプション
- `--precision`：1 (発散型)〜10 (厳密型) の指標で温度や自己検証回数を調整します。【F:backend/ai_meeting/config.py†L30-L85】【F:backend/ai_meeting/meeting.py†L28-L43】
- `--agents`：参加者名を順番に指定。`名前=systemプロンプト` 形式を混在させると個別ルールを注入できます。【F:backend/ai_meeting/cli.py†L97-L112】【F:backend/ai_meeting/config.py†L12-L19】
- `--chat-mode/--no-chat-mode`：短文チャット制約の ON/OFF。文数や文字数制限 (`--chat-max-sentences` / `--chat-max-chars`) も変更可能です。【F:backend/ai_meeting/config.py†L43-L47】【F:backend/ai_meeting/meeting.py†L247-L264】
- `--resolve-round`：残課題をまとめて解消するラウンドを挿入するかどうか。【F:backend/ai_meeting/config.py†L41-L47】【F:backend/ai_meeting/meeting.py†L481-L505】
- `--think-mode`：思考→審査→発言 (T3→T1) のプロセスを有効化/無効化します。【F:backend/ai_meeting/config.py†L66-L68】【F:backend/ai_meeting/meeting.py†L297-L320】
- `--outdir`：ログ出力先を明示指定。未指定なら自動で `logs/<日時_トピック>` を作成します。【F:backend/ai_meeting/config.py†L77-L78】【F:backend/ai_meeting/logging.py†L14-L44】

## ログファイルの構成
- `meeting_live.jsonl`：1 行 1 発言の JSON Lines。フロントエンドのタイムラインが参照します。【F:backend/ai_meeting/logging.py†L14-L107】【F:frontend/src/services/api.js†L17-L37】
- `meeting_live.md`：人が読みやすい Markdown ログ。
- `meeting_result.json`：会議設定・最終合意案・発言履歴をまとめた JSON。【F:backend/ai_meeting/meeting.py†L542-L558】
- `phases.jsonl` / `thoughts.jsonl`：フェーズ推定や思考ログ (デバッグ用)。【F:backend/ai_meeting/logging.py†L23-L77】【F:backend/ai_meeting/meeting.py†L297-L437】
- `metrics.csv` / `metrics_cpu_mem.png` / `metrics_gpu.png`：CPU/GPU の稼働状況を記録したファイル。【F:backend/ai_meeting/metrics.py†L17-L148】

## フロントエンドのセットアップとプレビュー
1. Node.js 18 以上を用意し、依存関係をインストールします。
   ```bash
   cd frontend
   npm install
   ```
2. 別ターミナルでリポジトリ直下からログディレクトリを配信します。例：
   ```bash
   python -m http.server 8000
   ```
   Vite の開発サーバーは `/logs` へのアクセスを `http://localhost:8000` にプロキシする設定です。【F:frontend/vite.config.js†L6-L16】
3. 開発サーバーを起動し、`http://localhost:5173` を開きます。
   ```bash
   npm run dev
   ```
   Home 画面でテーマなどを入力して会議を開始すると、生成済みログを読み込みながらタイムラインと要約が更新されます。【F:frontend/src/pages/Home.jsx†L5-L84】【F:frontend/src/pages/Meeting.jsx†L1-L96】
4. ビルドは `npm run build` で生成され、`frontend/dist/` に静的ファイルが出力されます。

## 既存ログの活用
`logs/` ディレクトリには過去の会議結果がまとまっています。`meeting_live.jsonl` と `meeting_result.json` をそのまま利用すれば、フロントエンドの Result 画面で KPI や最終合意案を確認できます。【F:frontend/src/services/api.js†L17-L37】【F:frontend/src/pages/Result.jsx†L8-L58】

## CI によるリグレッションチェック

GitHub Actions のワークフロー `.github/workflows/cli-regression.yml` では `pytest backend/tests/test_cli_e2e.py` を実行した後、`python scripts/check_cli_baseline.py` を介して `python -m backend.ai_meeting` の出力ログと `docs/samples/cli_baseline/*.json` に保存したベースラインを比較します。決定論的バックエンドを利用することで、主要フラグ（短文チャット／旧フロー）ごとのログ・KPI 差分を CI 上で自動検知します。

## ライセンス
本リポジトリのライセンスは未指定です。利用ポリシーが必要な場合はリポジトリ所有者に確認してください。
