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
    },
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

      const payload = {
        topic: trimmedTopic,
        precision: precisionValue,
        rounds: roundsValue,
        agents: agentsTrimmed || undefined,
        options: {
          llmBackend: backendTrimmed || undefined,
          model: modelTrimmed || undefined,
        },
      };
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
