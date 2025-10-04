import { useEffect, useMemo, useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getModels, startMeeting } from "../services/api";
import { loadHomePreset, saveHomePreset } from "../services/presets";

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
        case "hydrate":
          return {
            ...state,
            ...action.value,
            openaiKeyRequired:
              ((action.value?.backend ?? state.backend) === "openai") && !action.openaiConfigured,
          };
        default:
          return state;
      }
    },
    {
      topic: "",
      precision: "5",
      rounds: "4",
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
  const defaultParticipants = useMemo(
    () => createParticipantsFromData(DEFAULT_PARTICIPANT_DATA),
    [],
  );
  const [participants, setParticipants] = useState(defaultParticipants);
  const [presetLoaded, setPresetLoaded] = useState(false);

  const resolvedMaxPhasesValue = formState.maxPhases === "" ? "1" : formState.maxPhases;
  const resolvedChatMaxSentencesValue =
    formState.chatMaxSentences === "" ? "2" : formState.chatMaxSentences;

  const handleParticipantChange = (id, field, value) => {
    setParticipants((prev) => prev.map((item) => (item.id === id ? { ...item, [field]: value } : item)));
  };

  const handleParticipantRemove = (id) => {
    setParticipants((prev) => prev.filter((item) => item.id !== id));
  };

  const handleParticipantAdd = () => {
    setParticipants((prev) => [...prev, createParticipantEntry()]);
  };

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

  useEffect(() => {
    const preset = loadHomePreset();
    if (preset && typeof preset === "object") {
      const { form, participants: storedParticipants } = preset;
      if (form && typeof form === "object") {
        const patch = {};
        const fields = [
          "topic",
          "precision",
          "rounds",
          "backend",
          "model",
          "phaseTurnLimit",
          "maxPhases",
          "chatMode",
          "chatMaxSentences",
        ];
        fields.forEach((field) => {
          const value = form[field];
          if (typeof value === "undefined") return;
          if (field === "chatMode") {
            patch.chatMode = Boolean(value);
            return;
          }
          if (typeof value === "string") {
            patch[field] = value;
            return;
          }
          if (typeof value === "number") {
            patch[field] = String(value);
          }
        });
        if (Object.keys(patch).length > 0) {
          dispatch({ type: "hydrate", value: patch, openaiConfigured });
        }
      }
      const derivedParticipants = deriveParticipants(storedParticipants);
      if (Array.isArray(derivedParticipants)) {
        setParticipants(derivedParticipants);
      }
    }
    setPresetLoaded(true);
  }, [openaiConfigured]);

  useEffect(() => {
    if (!presetLoaded) return;
    const { openaiKeyRequired: _ignored, ...formToSave } = formState;
    const participantsToSave = participants.map((item) => ({
      name: item.name ?? "",
      prompt: item.prompt ?? "",
    }));
    saveHomePreset({
      form: formToSave,
      participants: participantsToSave,
    });
  }, [formState, participants, presetLoaded]);

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
      const finalAgentsValue = buildAgentsString(participants);
      if (!finalAgentsValue) {
        throw new Error("参加者を1人以上設定してください。");
      }
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
        agents: finalAgentsValue,
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
        agents: finalAgentsValue,
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
            <div className="slider-control">
              <input
                className="range-input"
                type="range"
                min={1}
                max={10}
                step={1}
                value={formState.precision}
                onChange={(e) => dispatch({ type: "update", field: "precision", value: e.target.value })}
              />
              <span className="slider-value">{formState.precision}</span>
            </div>
          </label>
          <label className="label">
            ラウンド数
            <div className="slider-control">
              <input
                className="range-input"
                type="range"
                min={1}
                max={12}
                step={1}
                value={formState.rounds}
                onChange={(e) => dispatch({ type: "update", field: "rounds", value: e.target.value })}
              />
              <span className="slider-value">{formState.rounds}</span>
            </div>
          </label>
        </div>

        <div className="label participant-section">
          <div className="participant-header">
            <span>参加者リスト</span>
            <button
              type="button"
              className="btn ghost participant-add"
              onClick={handleParticipantAdd}
            >
              行を追加
            </button>
          </div>
          <ParticipantsEditor
            participants={participants}
            onChange={handleParticipantChange}
            onRemove={handleParticipantRemove}
            onAdd={handleParticipantAdd}
          />
          <div className="hint">各参加者の名前と任意のシステムプロンプトを設定できます。</div>
        </div>
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
                <div className="slider-control">
                  <input
                    className="range-input"
                    type="range"
                    min={1}
                    max={10}
                    step={1}
                    value={resolvedMaxPhasesValue}
                    onChange={(e) => dispatch({ type: "update", field: "maxPhases", value: e.target.value })}
                  />
                  <span className="slider-value">{formState.maxPhases || "未設定"}</span>
                  <button
                    type="button"
                    className="slider-reset"
                    onClick={() => dispatch({ type: "update", field: "maxPhases", value: "" })}
                    disabled={formState.maxPhases === ""}
                  >
                    クリア
                  </button>
                </div>
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
                <div className="slider-control">
                  <input
                    className="range-input"
                    type="range"
                    min={1}
                    max={6}
                    step={1}
                    value={resolvedChatMaxSentencesValue}
                    onChange={(e) => dispatch({ type: "update", field: "chatMaxSentences", value: e.target.value })}
                  />
                  <span className="slider-value">{formState.chatMaxSentences || "既定 (2)"}</span>
                  <button
                    type="button"
                    className="slider-reset"
                    onClick={() => dispatch({ type: "update", field: "chatMaxSentences", value: "" })}
                    disabled={formState.chatMaxSentences === ""}
                  >
                    クリア
                  </button>
                </div>
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

function ParticipantsEditor({ participants, onChange, onRemove, onAdd }) {
  if (!participants.length) {
    return (
      <div className="participants-empty">
        <div className="participants-empty-text">参加者が設定されていません。</div>
        {onAdd && (
          <button type="button" className="participant-empty-add" onClick={onAdd}>
            行を追加
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="participants-wrapper">
      <table className="participants-table">
        <thead>
          <tr>
            <th className="participant-col-index">#</th>
            <th className="participant-col-name">名前</th>
            <th className="participant-col-prompt">システムプロンプト（任意）</th>
            <th className="participant-col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          {participants.map((participant, index) => (
            <tr key={participant.id}>
              <td className="participant-index">{index + 1}</td>
              <td>
                <input
                  className="input"
                  value={participant.name}
                  onChange={(e) => onChange(participant.id, "name", e.target.value)}
                  placeholder={DEFAULT_PARTICIPANT_DATA[index]?.name ?? "Agent"}
                />
              </td>
              <td>
                <textarea
                  className="input participant-prompt"
                  rows={2}
                  value={participant.prompt}
                  onChange={(e) => onChange(participant.id, "prompt", e.target.value)}
                  placeholder="例: 調整役として議論をまとめる"
                />
              </td>
              <td className="participant-actions">
                <button
                  type="button"
                  className="participant-remove"
                  onClick={() => onRemove(participant.id)}
                  aria-label={`参加者${index + 1}を削除`}
                >
                  削除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DEFAULT_PARTICIPANT_DATA = [
  { name: "Alice", prompt: "" },
  { name: "Bob", prompt: "" },
  { name: "Carol", prompt: "" },
];

function createParticipantId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `p-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function createParticipantEntry(name = "", prompt = "") {
  return {
    id: createParticipantId(),
    name: typeof name === "string" ? name : "",
    prompt: typeof prompt === "string" ? prompt : "",
  };
}

function createParticipantsFromData(list) {
  if (!Array.isArray(list)) return [];
  return list.map((item) => createParticipantEntry(item?.name ?? "", item?.prompt ?? ""));
}

function deriveParticipants(savedList) {
  if (!Array.isArray(savedList)) {
    return null;
  }
  return createParticipantsFromData(savedList);
}

function buildAgentsString(participants) {
  if (!Array.isArray(participants) || participants.length === 0) {
    return "";
  }
  const tokens = participants
    .map((participant) => createAgentToken(participant))
    .filter(Boolean);
  return tokens.join(" ").trim();
}

function createAgentToken(participant) {
  if (!participant) return null;
  const rawName = typeof participant.name === "string" ? participant.name : "";
  const rawPrompt = typeof participant.prompt === "string" ? participant.prompt : "";
  const normalizedName = rawName.replace(/\s+/g, " ").trim();
  if (!normalizedName) return null;
  const normalizedPrompt = rawPrompt.replace(/\r?\n/g, " ").trim();
  const base = normalizedPrompt ? `${normalizedName}=${normalizedPrompt}` : normalizedName;
  return needsQuoting(base) ? quoteToken(base) : base;
}

function needsQuoting(value) {
  return /[\s"']/u.test(value);
}

function quoteToken(value) {
  const escaped = value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `"${escaped}"`;
}

export { createAgentToken, needsQuoting, quoteToken };
