import { useEffect, useMemo, useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getModels, startMeeting } from "../services/api";

export default function Home() {
  const nav = useNavigate();
  const openaiConfigured = useMemo(() => Boolean(import.meta.env.VITE_OPENAI_API_KEY), []);
  const [modelOptions, setModelOptions] = useState([]);
  const [modelsError, setModelsError] = useState("");
  const [formState, dispatch] = useReducer(
    (state, action) => {
      switch (action.type) {
        case "update":
          return { ...state, [action.field]: action.value };
        case "setBackend":
          return {
            ...state,
            backend: action.value,
            model: "",
            openaiKeyRequired: action.value === "openai" && !action.openaiConfigured,
          };
        case "setModel":
          return { ...state, model: action.value };
        default:
          return state;
      }
    },
    {
      topic: "",
      precision: "5",
      rounds: "4",
      agents: "Alice Bob Carol",
      backend: "ollama",
      model: "",
      openaiKeyRequired: false,
      phaseTurnLimit: "",
      maxPhases: "",
      chatMode: true,
      chatMaxSentences: "",
    },
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    let ignore = false;
    (async () => {
      try {
        const list = await getModels();
        if (!ignore) {
          setModelOptions(list);
          setModelsError(list.length === 0 ? "Ollama からモデルを取得できませんでした。" : "");
        }
      } catch (err) {
        if (!ignore) {
          setModelOptions([]);
          setModelsError(err instanceof Error ? err.message : "モデル一覧の取得に失敗しました。");
        }
      }
    })();
    return () => {
      ignore = true;
    };
  }, []);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setLoading(true);
    try {
      const trimmedTopic = formState.topic.trim();
      if (!trimmedTopic) {
        throw new Error("テーマを入力してください。");
      }
      const precisionValueRaw = Number(formState.precision);
      const roundsValueRaw = Number(formState.rounds);
      const precisionValue = Number.isFinite(precisionValueRaw) ? precisionValueRaw : undefined;
      const roundsValue = Number.isFinite(roundsValueRaw) ? roundsValueRaw : undefined;
      const agentsTrimmed = formState.agents.trim();
      const backendTrimmed = formState.backend.trim();
      const modelTrimmed = formState.model.trim();
      const maxPhasesTrimmed = formState.maxPhases.trim();
      const chatMaxSentencesTrimmed = formState.chatMaxSentences.trim();

      const parseBoundedInt = (value, label, { min, max }) => {
        const numeric = Number(value);
        if (!Number.isFinite(numeric) || !Number.isInteger(numeric)) {
          throw new Error(`${label}は整数で入力してください。`);
        }
        if (typeof min === "number" && numeric < min) {
          throw new Error(`${label}は${min}以上で入力してください。`);
        }
        if (typeof max === "number" && numeric > max) {
          throw new Error(`${label}は${max}以下で入力してください。`);
        }
        return numeric;
      };

      const parsePhaseTurnLimit = (value) => {
        const trimmed = value.trim();
        if (!trimmed) return [];
        const tokens = trimmed.split(/[\s,]+/).filter(Boolean);
        if (!tokens.length) return [];
        return tokens.map((token) => {
          if (token.includes("=")) {
            const [nameRaw, numRaw] = token.split("=", 2);
            const name = nameRaw.trim();
            if (!name) {
              throw new Error("フェーズターン上限のキーが空です。");
            }
            const numeric = parseBoundedInt(numRaw, "フェーズターン上限", { min: 1, max: 12 });
            return `${name}=${numeric}`;
          }
          const numeric = parseBoundedInt(token, "フェーズターン上限", { min: 1, max: 12 });
          return numeric;
        });
      };

      const phaseTurnLimitTokens = parsePhaseTurnLimit(formState.phaseTurnLimit ?? "");
      const maxPhasesValue = maxPhasesTrimmed
        ? parseBoundedInt(maxPhasesTrimmed, "フェーズ数の上限", { min: 1, max: 10 })
        : undefined;
      const chatMaxSentencesValue = chatMaxSentencesTrimmed
        ? parseBoundedInt(chatMaxSentencesTrimmed, "チャット最大文数", { min: 1, max: 6 })
        : undefined;

      const payload = {
        topic: trimmedTopic,
        precision: precisionValue,
        rounds: roundsValue,
        agents: agentsTrimmed || undefined,
        backend: backendTrimmed || undefined,
      };

      const optionsPayload = {};
      const llmOptions = {};
      if (backendTrimmed) {
        llmOptions.backend = backendTrimmed;
      }
      if (modelTrimmed) {
        if (backendTrimmed === "openai") {
          llmOptions.openaiModel = modelTrimmed;
        } else if (backendTrimmed === "ollama") {
          llmOptions.ollamaModel = modelTrimmed;
        } else {
          llmOptions.model = modelTrimmed;
        }
      }
      if (Object.keys(llmOptions).length > 0) {
        optionsPayload.llm = llmOptions;
      }

      const flowOptions = {};
      if (phaseTurnLimitTokens.length === 1) {
        flowOptions.phaseTurnLimit = phaseTurnLimitTokens[0];
      } else if (phaseTurnLimitTokens.length > 1) {
        flowOptions.phaseTurnLimit = phaseTurnLimitTokens;
      }
      if (typeof maxPhasesValue === "number") {
        flowOptions.maxPhases = maxPhasesValue;
      }
      if (Object.keys(flowOptions).length > 0) {
        optionsPayload.flow = flowOptions;
      }

      const chatOptions = {};
      if (!formState.chatMode) {
        chatOptions.chatMode = false;
      }
      if (typeof chatMaxSentencesValue === "number") {
        chatOptions.chatMaxSentences = chatMaxSentencesValue;
      }
      if (Object.keys(chatOptions).length > 0) {
        optionsPayload.chat = chatOptions;
      }

      if (Object.keys(optionsPayload).length > 0) {
        payload.options = optionsPayload;
      }
      const data = await startMeeting(payload);
      const outdir = typeof data.outdir === "string" ? data.outdir.replace(/\\/g, "/") : "";
      const match = outdir.startsWith("logs/") ? outdir.slice(5) : outdir;
      const meetingId = match || data.id;
      if (!meetingId) {
        throw new Error("会議IDの取得に失敗しました。");
      }
      const params = new URLSearchParams({
        topic: trimmedTopic,
        precision: String(precisionValue ?? 5),
        rounds: String(roundsValue ?? 4),
        agents: agentsTrimmed,
      }).toString();
      const encodedMeetingId = encodeURIComponent(meetingId);
      nav(`/meeting/${encodedMeetingId}?${params}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };


  return (
    <section className="card">
      <h1 className="title">会議の作成</h1>
      <form className="form" onSubmit={onSubmit}>
        <label className="label">
          テーマ
          <input className="input" value={formState.topic} onChange={(e) => dispatch({ type: "update", field: "topic", value: e.target.value })} placeholder="例: 10分で遊べる1畳スポーツの仕様" required />
        </label>

        <div className="grid-2">
          <label className="label">
            精密度 (1-10)
            <input className="input" type="number" min={1} max={10} value={formState.precision} onChange={(e) => dispatch({ type: "update", field: "precision", value: e.target.value })} />
          </label>
          <label className="label">
            ラウンド数
            <input className="input" type="number" min={1} max={12} value={formState.rounds} onChange={(e) => dispatch({ type: "update", field: "rounds", value: e.target.value })} />
          </label>
        </div>

        <label className="label">
          参加者名（空白区切り、例: Alice Bob Carol)
          <input className="input" value={formState.agents} onChange={(e) => dispatch({ type: "update", field: "agents", value: e.target.value })} placeholder="Alice Bob Carol" />
        </label>

        <div className="grid-2">
          <label className="label">
            バックエンド
            <select
              className="select"
              value={formState.backend}
              onChange={(e) => dispatch({ type: "setBackend", value: e.target.value, openaiConfigured })}
            >
              <option value="ollama">Ollama (ローカル)</option>
              <option value="openai">OpenAI API</option>
            </select>
            <div className="hint">利用するLLMサービスを選択します。</div>
            {formState.openaiKeyRequired && (
              <div className="hint error">OpenAI バックエンドを利用するには環境変数 VITE_OPENAI_API_KEY を設定してください。</div>
            )}
          </label>
          <label className="label">
            モデル
            <select
              className="select"
              value={formState.model}
              onChange={(e) => dispatch({ type: "setModel", value: e.target.value })}
              disabled={formState.backend === "ollama" && modelOptions.length === 0}
            >
              <option value="">自動（バックエンド既定）</option>
              {(formState.backend === "openai" ? OPENAI_MODEL_CHOICES : modelOptions).map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
            {formState.backend === "ollama" && modelsError && (
              <div className="hint error">{modelsError}</div>
            )}
            {formState.backend === "ollama" && !modelsError && (
              <div className="hint">Ollama にインストール済みのモデル一覧から選択できます。</div>
            )}
            {formState.backend === "openai" && (
              <div className="hint">OpenAI モデルは必要に応じて選択してください。未選択時は既定値を利用します。</div>
            )}
          </label>
        </div>

        <details
          className="advanced"
          open={advancedOpen}
          onToggle={(event) => setAdvancedOpen(event.target.open)}
        >
          <summary className="advanced-summary">高度な設定</summary>
          <div className="advanced-content">
            <div className="advanced-grid">
              <label className="label">
                フェーズターン上限
                <input
                  className="input"
                  value={formState.phaseTurnLimit}
                  onChange={(e) => dispatch({ type: "update", field: "phaseTurnLimit", value: e.target.value })}
                  placeholder="例: discussion=2 resolution=1"
                />
                <div className="hint">
                  空白またはカンマで区切って複数指定できます。数値のみの場合は全フェーズ共通の上限になります。
                </div>
              </label>

              <label className="label">
                フェーズ数の上限
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={10}
                  value={formState.maxPhases}
                  onChange={(e) => dispatch({ type: "update", field: "maxPhases", value: e.target.value })}
                  placeholder="未設定"
                />
                <div className="hint">1〜10 の範囲で指定できます。空欄にすると自動判定に任せます。</div>
              </label>

              <div className="label advanced-chat-section">
                <div className="advanced-chat-title">短文チャットモード</div>
                <label className="advanced-chat-toggle">
                  <input
                    type="checkbox"
                    checked={formState.chatMode}
                    onChange={(e) => dispatch({ type: "update", field: "chatMode", value: e.target.checked })}
                  />
                  <span>短文チャットを有効にする</span>
                </label>
                <div className="hint">既定では有効です。オフにすると従来の長文モードで進行します。</div>
              </div>

              <label className="label">
                チャット最大文数
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={6}
                  value={formState.chatMaxSentences}
                  onChange={(e) => dispatch({ type: "update", field: "chatMaxSentences", value: e.target.value })}
                  placeholder="2 (既定)"
                />
                <div className="hint">1〜6 の範囲で設定できます。空欄なら既定値 2 を利用します。</div>
              </label>
            </div>
          </div>
        </details>

        <div className="actions">
          <button className="btn" type="submit" disabled={!formState.topic.trim() || loading || formState.openaiKeyRequired}>
            {loading ? "起動中..." : "会議を開始"}
          </button>
        </div>
      </form>
      {error && <div className="error" style={{ color: "#d00", marginTop: "1rem" }}>{error}</div>}
    </section>
  );
}

const OPENAI_MODEL_CHOICES = [
  "gpt-4o-mini",
  "gpt-4o",
  "gpt-4.1-mini",
  "o3-mini",
  "o1-mini",
];
