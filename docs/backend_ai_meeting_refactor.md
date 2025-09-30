# `backend.ai_meeting` パッケージ化計画

## 目的

* 旧 `backend/ai_meeting.py` に集中している機能を段階的に分割し、
  パッケージとして管理しやすくする。
* CLI インターフェース、設定、LLM アダプタなどを明確にモジュール化し、
  メンテナンス性とテスト容易性を向上させる。

## 現状の公開構成

2024 年時点で `backend/ai_meeting/` パッケージは以下のモジュールに整理済みです。

```text
backend/ai_meeting/
├── __init__.py      # MeetingConfig / Meeting / build_agents などの公開 API
├── __main__.py      # `python -m backend.ai_meeting` エントリーポイント
├── cli.py           # CLI 引数解析と main()
├── config.py        # AgentConfig / MeetingConfig モデル
├── controllers.py   # KPI 制御・フェーズ判定
├── evaluation.py    # KPI 評価器
├── logging.py       # LiveLogWriter
├── meeting.py       # 実際の会議進行ロジック
├── testing.py       # DeterministicLLMBackend などテスト補助
└── ...
```

`testing.py` に含まれる `DeterministicLLMBackend` と `NullMetricsLogger` は `AI_MEETING_TEST_MODE=deterministic` をセットしたときに自動利用され、CLI を含むエンドツーエンドテストを完全オフラインで再現できます。CI ではこのテストモードを前提に `scripts/check_cli_baseline.py` からベースライン比較を行います。

## 段階的移行手順

1. **パッケージ土台の作成（現段階）**
   * `backend/ai_meeting/` ディレクトリを作成し、`__init__.py` と `__main__.py` を追加する。
   * `__init__.py` で旧モジュールを動的読み込みし、`main()` へのアクセスポイントを提供する。
   * `python -m backend.ai_meeting` で従来どおりの CLI を起動できることを確認する。

2. **CLI エントリーポイントの分離**
   * 旧モジュールから `argparse` 関連コードと `main()` 関数を `cli.py` に移動する。
   * `__main__.py` と将来の `backend/__init__.py` からは `cli.main()` を呼び出すようにする。
   * 単体テストで CLI の基本動作を保証する。

3. **設定・データモデルの分割**
   * `MeetingConfig` や `AgentConfig` などの Pydantic モデルを `config.py` に移行。
   * デフォルト設定・バリデーション関連を `defaults.py` と `validators.py` に整理。
   * 旧モジュールでのインポート箇所を順次更新。

4. **LLM バックエンドの独立化**
   * `LLMBackend`, `OpenAIBackend`, `OllamaBackend` 等を `llm/` サブパッケージ（例: `llm/base.py`, `llm/openai.py`, `llm/ollama.py`）へ移動。
   * 新サブパッケージでの依存関係を整理し、テスト用モックを準備。

5. **会議ロジックのモジュール化**
   * 会議進行・ログ関連クラスを `meeting/` サブパッケージ（`controller.py`, `logging.py`, `state.py` など）に移す。
   * ロジック単位でユニットテストを追加し、回帰防止を図る。

6. **不要コードの整理と最終調整**
   * 旧 `backend/ai_meeting.py` を最終的に削除し、新しいパッケージ構成に統合。
   * ドキュメントおよび CLI ヘルプメッセージを最新化する。
   * CI での静的解析・テストを更新された構成に合わせて整備。

## 最終モジュール構成（案）

```
backend/
  ai_meeting/
    __init__.py          # パッケージ初期化と公開 API
    __main__.py          # `python -m backend.ai_meeting` 用 CLI ラッパー
    cli.py               # 引数解析と CLI エントリーポイント
    config.py            # Pydantic 設定モデル・デフォルト値
    logging.py           # ログ出力関連ユーティリティ
    orchestrator.py      # 会議進行のメインロジック
    participants.py      # エージェント管理・選定ロジック
    llm/
      __init__.py
      base.py            # LLMBackend インターフェース
      openai.py          # OpenAI 実装
      ollama.py          # Ollama 実装
    prompts/
      __init__.py
      templates.py       # プロンプトテンプレートと生成ヘルパー
    utils/
      __init__.py
      text.py            # 文字列整形・共通ユーティリティ
      math.py            # スコア計算などのユーティリティ
```

上記構成では、CLI・設定・LLM・会議ロジックを独立したモジュールに分割し、
責務ごとにテストを実施できるようにする。段階的な移行により、既存機能の
動作を維持しつつ大規模な変更リスクを最小化する。
