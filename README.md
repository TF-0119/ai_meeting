# AI Meeting

## プロジェクト概要
AI Meeting は、大規模言語モデル (LLM) を複数の役割に分けて協調させる会議シミュレーターです。バックエンドは Python 製の CLI スクリプトで、プランナー・ワーカー・クリティックなどのエージェントを順番に呼び出し、議論ログや KPI を自動で記録します。フロントエンドは React/Vite 製の簡易ビューワーで、生成されたログをタイムライン形式で閲覧できます。

## 主な機能
- **マルチエージェント会議進行**：役割プロンプトとチャット制約を用いて各エージェントが短文で議論します。思考→審査→発言の三段階に対応し、ラウンドごとの要約や残課題解消ラウンドも自動化されています。【F:backend/ai_meeting.py†L172-L229】【F:backend/ai_meeting.py†L632-L730】
- **ログ生成と分析**：`meeting_live.md` / `meeting_live.jsonl` / `meeting_result.json` をはじめ、CPU・GPU 利用率の時系列 (`metrics.csv` やグラフ画像) を保存します。【F:backend/ai_meeting.py†L205-L288】【F:backend/ai_meeting.py†L820-L904】
- **KPI 評価とフィードバック**：議論の多様性・決定密度などを自動計測し、閾値割れ時にはプロンプトを調整する仕組みを備えています。【F:backend/ai_meeting.py†L234-L261】【F:backend/ai_meeting.py†L874-L900】
- **フロントエンド表示**：生成ログをポーリングしてタイムライン・要約・KPI を表示する React UI を提供します。【F:frontend/src/pages/Meeting.jsx†L1-L90】【F:frontend/src/pages/Result.jsx†L8-L52】

> 🔰 **初心者向けガイド**
>
> フロントエンドの Home 画面と FastAPI の連携手順を噛み砕いて説明したメモを `docs/meeting_flow_for_beginners.md` にまとめました。フォーム送信から会議ログ表示までの流れをざっくり知りたいときに活用してください。【F:docs/meeting_flow_for_beginners.md†L1-L44】

## ディレクトリ構成
```text
ai_meeting/
├── backend/            # 会議エンジン (Python)
├── frontend/           # React/Vite フロントエンド
├── logs/               # 実行ごとのログ出力 (meeting_live.jsonl 等)
└── README.md
```

## バックエンドのセットアップと実行
1. Python 3.10 以上の環境を用意し、必要なパッケージをインストールします。Ollama を使う場合は `requests`、OpenAI を使う場合は `openai` が必要です。
   ```bash
   pip install pydantic psutil matplotlib pynvml GPUtil requests openai
   ```
   ※ `pynvml` や `GPUtil` は GPU 利用率を取得したいときのみ必須です。【F:backend/ai_meeting.py†L346-L408】
2. Ollama を利用する場合は `ollama run llama3` などでローカルサーバーを立ち上げておきます (既定は `http://localhost:11434`)。【F:backend/ai_meeting.py†L60-L87】
3. OpenAI を利用する場合は `OPENAI_API_KEY` と必要なら `OPENAI_MODEL` を環境変数に設定します。【F:backend/ai_meeting.py†L41-L57】
4. 会議を実行します。例：
   ```bash
   python backend/ai_meeting.py \
     --topic "1畳で遊べる新スポーツを仕様化" \
     --precision 6 \
     --agents planner worker critic finisher \
     --rounds 4 \
     --backend ollama
   ```
   実行すると `logs/<日時_トピック>/` 以下にログ一式が出力されます。

### 主要な CLI オプション
- `--precision`：1 (発散型)〜10 (厳密型) の指標で温度や自己検証回数を調整します。【F:backend/ai_meeting.py†L180-L206】
- `--agents`：参加させる役割を順番に指定。未知の文字列は汎用メンバーとして扱われます。【F:backend/ai_meeting.py†L1639-L1691】
- `--chat-mode/--no-chat-mode`：短文チャット制約の ON/OFF。文数や文字数制限 (`--chat-max-sentences` / `--chat-max-chars`) も変更可能です。【F:backend/ai_meeting.py†L1671-L1706】【F:backend/ai_meeting.py†L693-L728】
- `--resolve-round`：残課題をまとめて解消するラウンドを挿入するかどうか。【F:backend/ai_meeting.py†L826-L864】
- `--think-mode`：思考→審査→発言 (T3→T1) のプロセスを有効化/無効化します。【F:backend/ai_meeting.py†L214-L229】【F:backend/ai_meeting.py†L632-L690】
- `--outdir`：ログ出力先を明示指定。未指定なら自動で `logs/<日時_トピック>` を作成します。【F:backend/ai_meeting.py†L205-L215】

## ログファイルの構成
- `meeting_live.jsonl`：1 行 1 発言の JSON Lines。フロントエンドのタイムラインが参照します。【F:backend/ai_meeting.py†L223-L266】【F:frontend/src/services/api.js†L17-L35】
- `meeting_live.md`：人が読みやすい Markdown ログ。
- `meeting_result.json`：会議設定・最終合意案・発言履歴をまとめた JSON。【F:backend/ai_meeting.py†L884-L904】
- `phases.jsonl` / `thoughts.jsonl`：フェーズ推定や思考ログ (デバッグ用)。
- `metrics.csv` / `metrics_cpu_mem.png` / `metrics_gpu.png`：CPU/GPU の稼働状況を記録したファイル。【F:backend/ai_meeting.py†L346-L408】

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
   Home 画面でテーマなどを入力して会議を開始すると、生成済みログを読み込みながらタイムラインと要約が更新されます。【F:frontend/src/pages/Home.jsx†L5-L51】【F:frontend/src/pages/Meeting.jsx†L1-L90】
4. ビルドは `npm run build` で生成され、`frontend/dist/` に静的ファイルが出力されます。

## 既存ログの活用
`logs/` ディレクトリには過去の会議結果がまとまっています。`meeting_live.jsonl` と `meeting_result.json` をそのまま利用すれば、フロントエンドの Result 画面で KPI や最終合意案を確認できます。【F:frontend/src/services/api.js†L17-L35】【F:frontend/src/pages/Result.jsx†L8-L52】

## ライセンス
本リポジトリのライセンスは未指定です。利用ポリシーが必要な場合はリポジトリ所有者に確認してください。
