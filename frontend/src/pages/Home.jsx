import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getModels, startMeeting } from "../services/api";
import { loadHomePreset, saveHomePreset } from "../services/presets";
import FieldError from "../components/FieldError";

const INITIAL_FORM_STATE = {
  topic: "",
  precision: "5",
  backend: "ollama",
  model: "",
  openaiKeyRequired: false,
  phaseTurnLimit: "",
  maxPhases: "",
  chatMode: true,
  chatMaxSentences: "",
};

const FORM_FIELDS = [
  "topic",
  "precision",
  "backend",
  "model",
  "phaseTurnLimit",
  "maxPhases",
  "chatMode",
  "chatMaxSentences",
];

const DEFAULT_PARTICIPANT_DATA = [
  { name: "Alice", prompt: "" },
  { name: "Bob", prompt: "" },
  { name: "Carol", prompt: "" },
];

const TEMPLATE_DEFINITIONS = [
  {
    value: "default",
    label: "標準テンプレート",
    description: "最小限の初期設定で会議を開始します。",
    form: { ...INITIAL_FORM_STATE },
    participants: DEFAULT_PARTICIPANT_DATA,
  },
  {
    value: "brainstorm",
    label: "ブレインストーミング",
    description: "アイデア出しを重視したファシリテーション構成です。",
    form: {
      ...INITIAL_FORM_STATE,
      precision: "6",
      phaseTurnLimit: "discussion=2 wrapup=1",
      maxPhases: "4",
      chatMode: true,
      chatMaxSentences: "",
    },
    participants: [
      { name: "Facilitator", prompt: "議論を整理し、全員の発言を促す" },
      { name: "Ideator", prompt: "革新的なアイデアを積極的に提案する" },
      { name: "Critic", prompt: "リスクと課題を客観的に指摘する" },
    ],
  },
  {
    value: "planning",
    label: "要件整理",
    description: "要件定義や進行管理を想定したバランス型の構成です。",
    form: {
      ...INITIAL_FORM_STATE,
      precision: "7",
      phaseTurnLimit: "analysis=2 decision=1",
      maxPhases: "3",
      chatMode: false,
    },
    participants: [
      { name: "Planner", prompt: "ゴールと成功条件を明確にする" },
      { name: "Engineer", prompt: "技術的な実現可能性を検討する" },
      { name: "Stakeholder", prompt: "ビジネス観点から優先順位を判断する" },
    ],
  },
];

const PRECISION_BOUNDS = { min: 1, max: 10 };
const MAX_PHASES_BOUNDS = { min: 1, max: 10 };
const CHAT_SENTENCE_BOUNDS = { min: 1, max: 6 };
const PHASE_TURN_BOUNDS = { min: 1, max: 12 };

function validateTopicValue(value) {
  return value.trim() ? "" : "テーマを入力してください。";
}

function parseBoundedInteger(value, label, bounds) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || !Number.isInteger(numeric)) {
    return { value: undefined, error: `${label}は整数で入力してください。` };
  }
  if (typeof bounds.min === "number" && numeric < bounds.min) {
    return { value: undefined, error: `${label}は${bounds.min}以上で入力してください。` };
  }
  if (typeof bounds.max === "number" && numeric > bounds.max) {
    return { value: undefined, error: `${label}は${bounds.max}以下で入力してください。` };
  }
  return { value: numeric, error: "" };
}

function evaluatePrecision(value) {
  return parseBoundedInteger(value, "精密度", PRECISION_BOUNDS);
}

function evaluateOptionalBoundedInteger(value, label, bounds) {
  if (typeof value !== "string" || value.trim() === "") {
    return { value: undefined, error: "" };
  }
  return parseBoundedInteger(value, label, bounds);
}

function evaluatePhaseTurnLimit(value) {
  const trimmed = typeof value === "string" ? value.trim() : "";
  if (!trimmed) {
    return { tokens: [], error: "" };
  }
  const tokens = trimmed.split(/[\s,]+/).filter(Boolean);
  const normalized = [];
  for (const token of tokens) {
    if (token.includes("=")) {
      const [nameRaw, countRaw] = token.split("=", 2);
      const name = (nameRaw ?? "").trim();
      if (!name) {
        return { tokens: [], error: "フェーズターン上限のキーが空です。" };
      }
      const { value: numeric, error } = parseBoundedInteger(countRaw, "フェーズターン上限", PHASE_TURN_BOUNDS);
      if (error) {
        return { tokens: [], error };
      }
      normalized.push(`${name}=${numeric}`);
      continue;
    }
    const { value: numeric, error } = parseBoundedInteger(token, "フェーズターン上限", PHASE_TURN_BOUNDS);
    if (error) {
      return { tokens: [], error };
    }
    normalized.push(numeric);
  }
  return { tokens: normalized, error: "" };
}

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
        case "reset":
          return {
            ...INITIAL_FORM_STATE,
            ...action.value,
            openaiKeyRequired:
              ((action.value?.backend ?? INITIAL_FORM_STATE.backend) === "openai") &&
              !action.openaiConfigured,
          };
        default:
          return state;
      }
    },
    INITIAL_FORM_STATE,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const defaultParticipants = useMemo(
    () => createParticipantsFromData(DEFAULT_PARTICIPANT_DATA),
    [],
  );
  const [participants, setParticipants] = useState(defaultParticipants);
  const [presetLoaded, setPresetLoaded] = useState(false);
  const [expandedStep, setExpandedStep] = useState("basic");
  const [selectedTemplate, setSelectedTemplate] = useState(TEMPLATE_DEFINITIONS[0].value);
  const [hasSavedPreset, setHasSavedPreset] = useState(false);
  const [presetStatus, setPresetStatus] = useState("");
  const [errors, setErrors] = useState({});
  const [touchedFields, setTouchedFields] = useState({});
  const [precisionValue, setPrecisionValue] = useState(5);
  const [phaseTurnLimitTokens, setPhaseTurnLimitTokens] = useState([]);
  const [maxPhasesValue, setMaxPhasesValue] = useState(undefined);
  const [chatMaxSentencesValue, setChatMaxSentencesValue] = useState(undefined);
  const [agentsValue, setAgentsValue] = useState("");
  const [liveMessage, setLiveMessage] = useState("");
  const presetStatusTimer = useRef(null);

  const updateError = useCallback((field, message) => {
    setErrors((prev) => {
      const next = { ...prev };
      if (message) {
        next[field] = message;
      } else {
        delete next[field];
      }
      return next;
    });
  }, []);

  const showPresetStatus = (message) => {
    setPresetStatus(message);
    if (typeof window !== "undefined") {
      if (presetStatusTimer.current) {
        window.clearTimeout(presetStatusTimer.current);
      }
      presetStatusTimer.current = window.setTimeout(() => {
        setPresetStatus("");
        presetStatusTimer.current = null;
      }, 3000);
    }
  };

  const applyTemplate = (template, { silent = false } = {}) => {
    if (!template) return false;
    const patch = createFormPatchFromPreset(template.form);
    dispatch({ type: "reset", value: patch, openaiConfigured });
    setParticipants(createParticipantsFromData(template.participants ?? DEFAULT_PARTICIPANT_DATA));
    setExpandedStep("basic");
    if (!silent) {
      showPresetStatus(`${template.label}を適用しました。`);
    }
    return true;
  };

  const applyTemplateByValue = (value, { silent = false } = {}) => {
    const template = TEMPLATE_DEFINITIONS.find((item) => item.value === value) ?? TEMPLATE_DEFINITIONS[0];
    setSelectedTemplate(template.value);
    return applyTemplate(template, { silent });
  };

  const applySavedPreset = (preset, { silent = false } = {}) => {
    if (!preset || typeof preset !== "object") {
      return false;
    }
    const patch = createFormPatchFromPreset(preset.form);
    dispatch({ type: "reset", value: patch, openaiConfigured });
    const derivedParticipants = deriveParticipants(preset.participants);
    if (Array.isArray(derivedParticipants) && derivedParticipants.length > 0) {
      setParticipants(derivedParticipants);
    } else {
      setParticipants(createParticipantsFromData(DEFAULT_PARTICIPANT_DATA));
    }
    setExpandedStep("basic");
    if (!silent) {
      showPresetStatus("保存済みプリセットを読み込みました。");
    }
    return true;
  };

  const handleTemplateChange = (event) => {
    applyTemplateByValue(event.target.value);
  };

  const handleStepToggle = (step) => {
    setExpandedStep(step);
  };

  const handleSavePreset = () => {
    const payload = buildPresetPayload(formState, participants);
    saveHomePreset(payload);
    setHasSavedPreset(true);
    showPresetStatus("現在の設定をプリセットとして保存しました。");
  };

  const handleLoadPreset = () => {
    const preset = loadHomePreset();
    if (applySavedPreset(preset, { silent: true })) {
      setHasSavedPreset(true);
      showPresetStatus("保存済みプリセットを読み込みました。");
    } else {
      showPresetStatus("保存済みプリセットが見つかりません。保存後にお試しください。");
    }
  };

  useEffect(() => {
    return () => {
      if (presetStatusTimer.current && typeof window !== "undefined") {
        window.clearTimeout(presetStatusTimer.current);
      }
    };
  }, []);

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

  const activeStep = expandedStep ?? "basic";
  const templateInfo =
    TEMPLATE_DEFINITIONS.find((item) => item.value === selectedTemplate) ?? TEMPLATE_DEFINITIONS[0];
  const participantNames = participants
    .map((participant) => (participant.name ?? "").trim())
    .filter((name) => name.length > 0);
  const backendLabel = formState.backend === "openai" ? "OpenAI API" : "Ollama (ローカル)";
  const backendSummary = formState.openaiKeyRequired
    ? `${backendLabel}（API Key 未設定）`
    : backendLabel;
  const basicSummaryItems = [
    { label: "テーマ", value: formState.topic.trim() || "未入力" },
    { label: "精密度", value: formState.precision },
    { label: "バックエンド", value: backendSummary },
    { label: "モデル", value: formState.model.trim() || "自動" },
  ];
  const participantsSummaryItems = [
    { label: "参加者数", value: `${participants.length} 名` },
    {
      label: "参加者一覧",
      value: participantNames.length ? participantNames.join("、") : "未設定",
    },
  ];
  const advancedConfigSet = Boolean(
    formState.phaseTurnLimit.trim() ||
      formState.maxPhases.trim() ||
      !formState.chatMode ||
      formState.chatMaxSentences.trim(),
  );
  const advancedSummaryItems = [
    { label: "フェーズターン上限", value: formState.phaseTurnLimit.trim() || "自動" },
    { label: "フェーズ数の上限", value: formState.maxPhases.trim() || "自動" },
    { label: "短文チャットモード", value: formState.chatMode ? "有効" : "無効" },
    {
      label: "チャット最大文数",
      value: formState.chatMode
        ? formState.chatMaxSentences.trim() || "既定 (2)"
        : "短文モード無効",
    },
  ];
  const progressSteps = [
    {
      id: "basic",
      label: "基本設定",
      complete: Boolean(formState.topic.trim()) && !formState.openaiKeyRequired,
      current: activeStep === "basic",
      status: formState.openaiKeyRequired ? "API Key 未設定" : formState.topic.trim() ? "完了" : "未入力",
    },
    {
      id: "participants",
      label: "参加者設定",
      complete: participantNames.length > 0,
      current: activeStep === "participants",
      status: participantNames.length > 0 ? "完了" : "参加者未設定",
    },
    {
      id: "advanced",
      label: "高度な設定",
      complete: advancedConfigSet,
      current: activeStep === "advanced",
      status: advancedConfigSet ? "調整済み" : "既定を使用",
    },
  ];
  const hasErrors = Object.keys(errors).length > 0;
  const topicErrorId = "home-topic-error";
  const topicHintId = "home-topic-hint";
  const precisionErrorId = "home-precision-error";
  const backendHintId = "home-backend-hint";
  const backendErrorId = "home-backend-error";
  const modelErrorId = "home-model-error";
  const modelHintBaseId = "home-model-hint";
  const phaseTurnLimitHintId = "home-phase-turn-hint";
  const phaseTurnLimitErrorId = "home-phase-turn-error";
  const maxPhasesHintId = "home-max-phases-hint";
  const maxPhasesErrorId = "home-max-phases-error";
  const chatModeHintId = "home-chat-mode-hint";
  const chatMaxHintId = "home-chat-max-hint";
  const chatMaxErrorId = "home-chat-max-error";
  const participantsHintId = "home-participants-hint";
  const participantsErrorId = "home-participants-error";

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
    if (applySavedPreset(preset, { silent: true })) {
      setHasSavedPreset(true);
    } else {
      applyTemplateByValue(TEMPLATE_DEFINITIONS[0].value, { silent: true });
    }
    setPresetLoaded(true);
  }, [openaiConfigured]);

  useEffect(() => {
    if (!presetLoaded) return;
    const payload = buildPresetPayload(formState, participants);
    saveHomePreset(payload);
    setHasSavedPreset(true);
  }, [formState, participants, presetLoaded]);

  useEffect(() => {
    const { value, error: precisionError } = evaluatePrecision(formState.precision ?? "");
    setPrecisionValue(typeof value === "number" ? value : undefined);
    updateError("precision", precisionError);
  }, [formState.precision, updateError]);

  useEffect(() => {
    const { tokens, error } = evaluatePhaseTurnLimit(formState.phaseTurnLimit ?? "");
    setPhaseTurnLimitTokens(tokens);
    updateError("phaseTurnLimit", error);
  }, [formState.phaseTurnLimit, updateError]);

  useEffect(() => {
    const { value, error } = evaluateOptionalBoundedInteger(
      formState.maxPhases,
      "フェーズ数の上限",
      MAX_PHASES_BOUNDS,
    );
    setMaxPhasesValue(typeof value === "number" ? value : undefined);
    updateError("maxPhases", error);
  }, [formState.maxPhases, updateError]);

  useEffect(() => {
    const { value, error } = evaluateOptionalBoundedInteger(
      formState.chatMaxSentences,
      "チャット最大文数",
      CHAT_SENTENCE_BOUNDS,
    );
    setChatMaxSentencesValue(typeof value === "number" ? value : undefined);
    updateError("chatMaxSentences", error);
  }, [formState.chatMaxSentences, updateError]);

  useEffect(() => {
    const value = buildAgentsString(participants);
    setAgentsValue(value);
    updateError("participants", value ? "" : "参加者を1人以上設定してください。");
  }, [participants, updateError]);

  const topicTouched = touchedFields.topic;

  useEffect(() => {
    if (!topicTouched) return;
    updateError("topic", validateTopicValue(formState.topic));
  }, [formState.topic, topicTouched, updateError]);

  useEffect(() => {
    setLiveMessage(error);
  }, [error]);

  const handleFieldBlur = useCallback(
    (field) => {
      setTouchedFields((prev) => (prev[field] ? prev : { ...prev, [field]: true }));
      if (field === "topic") {
        updateError(field, validateTopicValue(formState.topic));
      }
    },
    [formState.topic, updateError],
  );

  const combineFieldDescriptors = useCallback((...ids) => {
    return ids.filter(Boolean).join(" ") || undefined;
  }, []);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    const submissionErrors = { ...errors };
    const topicError = validateTopicValue(formState.topic);
    if (topicError) {
      submissionErrors.topic = topicError;
    } else {
      delete submissionErrors.topic;
    }
    const finalAgentsValue = agentsValue || buildAgentsString(participants);
    if (!finalAgentsValue) {
      submissionErrors.participants = "参加者を1人以上設定してください。";
    } else {
      delete submissionErrors.participants;
    }
    if (Object.keys(submissionErrors).length > 0) {
      setErrors(submissionErrors);
      setTouchedFields((prev) => ({ ...prev, topic: true, participants: true }));
      const message = "入力内容を確認してください。";
      setError(message);
      setLiveMessage(message);
      return;
    }
    setLoading(true);
    try {
      const trimmedTopic = formState.topic.trim();
      const backendTrimmed = formState.backend.trim();
      const modelTrimmed = formState.model.trim();

      const payload = {
        topic: trimmedTopic,
        precision: typeof precisionValue === "number" ? precisionValue : undefined,
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
    <section className="card home-card">
      <h1 className="title">会議の作成</h1>

      <div className="template-toolbar" role="region" aria-label="テンプレートの選択">
        <div className="template-select">
          <label className="template-label">
            <span className="template-label-text">テンプレート</span>
            <select className="select" value={selectedTemplate} onChange={handleTemplateChange}>
              {TEMPLATE_DEFINITIONS.map((template) => (
                <option key={template.value} value={template.value}>
                  {template.label}
                </option>
              ))}
            </select>
          </label>
          <div className="template-description">{templateInfo?.description}</div>
        </div>
        <div className="template-actions">
          <button type="button" className="btn ghost" onClick={handleLoadPreset} disabled={!hasSavedPreset}>
            プリセットを読込
          </button>
          <button type="button" className="btn ghost" onClick={handleSavePreset}>
            プリセットとして保存
          </button>
        </div>
      </div>

      {presetStatus && <div className="preset-status">{presetStatus}</div>}

      <StepProgress steps={progressSteps} />

      <div className="home-layout">
        <form className="form step-form" onSubmit={onSubmit}>
          <StepCard
            stepNumber={1}
            stepId="basic"
            title="基本設定"
            isOpen={expandedStep === "basic"}
            onToggle={() => handleStepToggle("basic")}
          >
            <label
              className={`label${errors.topic ? " has-error" : ""}`}
              htmlFor="home-topic"
            >
              <span className="label-title">テーマ</span>
              <input
                id="home-topic"
                className={`input${errors.topic ? " is-error" : ""}`}
                value={formState.topic}
                onChange={(e) => dispatch({ type: "update", field: "topic", value: e.target.value })}
                onBlur={() => handleFieldBlur("topic")}
                placeholder="例: 10分で遊べる1畳スポーツの仕様"
                required
                aria-invalid={errors.topic ? "true" : "false"}
                aria-describedby={combineFieldDescriptors(
                  topicHintId,
                  errors.topic ? topicErrorId : null,
                )}
              />
              <FieldError id={topicErrorId} message={errors.topic} />
              <div id={topicHintId} className="hint">
                会議のテーマを入力してください。
              </div>
            </label>
            <div className="grid-2 step-grid">
              <label
                className={`label${errors.precision ? " has-error" : ""}`}
                htmlFor="home-precision"
              >
                <span className="label-title">精密度 (1-10)</span>
                <div className="slider-control">
                  <input
                    id="home-precision"
                    className={`range-input${errors.precision ? " is-error" : ""}`}
                    type="range"
                    min={1}
                    max={10}
                    step={1}
                    value={formState.precision}
                    onChange={(e) => dispatch({ type: "update", field: "precision", value: e.target.value })}
                    aria-invalid={errors.precision ? "true" : "false"}
                    aria-describedby={combineFieldDescriptors(
                      errors.precision ? precisionErrorId : null,
                    )}
                  />
                  <span className="slider-value" id="home-precision-value">
                    {formState.precision}
                  </span>
                </div>
                <FieldError id={precisionErrorId} message={errors.precision} />
              </label>
              <label
                className={`label${formState.openaiKeyRequired ? " has-error" : ""}`}
                htmlFor="home-backend"
              >
                <span className="label-title">バックエンド</span>
                <select
                  id="home-backend"
                  className={`select${formState.openaiKeyRequired ? " is-error" : ""}`}
                  value={formState.backend}
                  onChange={(e) => dispatch({ type: "setBackend", value: e.target.value, openaiConfigured })}
                  aria-invalid={formState.openaiKeyRequired ? "true" : "false"}
                  aria-describedby={combineFieldDescriptors(
                    backendHintId,
                    formState.openaiKeyRequired ? backendErrorId : null,
                  )}
                >
                  <option value="ollama">Ollama (ローカル)</option>
                  <option value="openai">OpenAI API</option>
                </select>
                <FieldError
                  id={backendErrorId}
                  message={
                    formState.openaiKeyRequired
                      ? "OpenAI バックエンドを利用するには環境変数 VITE_OPENAI_API_KEY を設定してください。"
                      : ""
                  }
                />
                <div id={backendHintId} className="hint">
                  利用するLLMサービスを選択します。
                </div>
              </label>
            </div>
            <label
              className={`label${modelsError ? " has-error" : ""}`}
              htmlFor="home-model"
            >
              <span className="label-title">モデル</span>
              <select
                id="home-model"
                className={`select${modelsError ? " is-error" : ""}`}
                value={formState.model}
                onChange={(e) => dispatch({ type: "setModel", value: e.target.value })}
                disabled={formState.backend === "ollama" && modelOptions.length === 0}
                aria-invalid={modelsError ? "true" : "false"}
                aria-describedby={combineFieldDescriptors(
                  modelsError ? modelErrorId : null,
                  formState.backend === "ollama" && !modelsError
                    ? `${modelHintBaseId}-ollama`
                    : formState.backend === "openai"
                    ? `${modelHintBaseId}-openai`
                    : null,
                )}
              >
                <option value="">自動（バックエンド既定）</option>
                {(formState.backend === "openai" ? OPENAI_MODEL_CHOICES : modelOptions).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <FieldError id={modelErrorId} message={modelsError} />
              {formState.backend === "ollama" && !modelsError && (
                <div id={`${modelHintBaseId}-ollama`} className="hint">
                  Ollama にインストール済みのモデル一覧から選択できます。
                </div>
              )}
              {formState.backend === "openai" && (
                <div id={`${modelHintBaseId}-openai`} className="hint">
                  OpenAI モデルは必要に応じて選択してください。未選択時は既定値を利用します。
                </div>
              )}
            </label>
          </StepCard>

          <StepCard
            stepNumber={2}
            stepId="participants"
            title="参加者設定"
            isOpen={expandedStep === "participants"}
            onToggle={() => handleStepToggle("participants")}
          >
            <div
              className={`label participant-section${errors.participants ? " has-error" : ""}`}
              role="group"
              aria-labelledby="home-participants-label"
              aria-invalid={errors.participants ? "true" : "false"}
              aria-describedby={combineFieldDescriptors(
                participantsHintId,
                errors.participants ? participantsErrorId : null,
              )}
            >
              <div className="participant-header" id="home-participants-label">
                <span>参加者リスト</span>
                <button type="button" className="btn ghost participant-add" onClick={handleParticipantAdd}>
                  行を追加
                </button>
              </div>
              <ParticipantsEditor
                participants={participants}
                onChange={handleParticipantChange}
                onRemove={handleParticipantRemove}
                onAdd={handleParticipantAdd}
              />
              <FieldError id={participantsErrorId} message={errors.participants} />
              <div id={participantsHintId} className="hint">
                各参加者の名前と任意のシステムプロンプトを設定できます。
              </div>
            </div>
          </StepCard>

          <StepCard
            stepNumber={3}
            stepId="advanced"
            title="高度な設定"
            isOpen={expandedStep === "advanced"}
            onToggle={() => handleStepToggle("advanced")}
          >
            <div className="advanced-grid">
              <label
                className={`label${errors.phaseTurnLimit ? " has-error" : ""}`}
                htmlFor="home-phase-turn"
              >
                <span className="label-title">フェーズターン上限</span>
                <input
                  id="home-phase-turn"
                  className={`input${errors.phaseTurnLimit ? " is-error" : ""}`}
                  value={formState.phaseTurnLimit}
                  onChange={(e) => dispatch({ type: "update", field: "phaseTurnLimit", value: e.target.value })}
                  placeholder="例: discussion=2 resolution=1"
                  aria-invalid={errors.phaseTurnLimit ? "true" : "false"}
                  aria-describedby={combineFieldDescriptors(
                    phaseTurnLimitHintId,
                    errors.phaseTurnLimit ? phaseTurnLimitErrorId : null,
                  )}
                />
                <FieldError id={phaseTurnLimitErrorId} message={errors.phaseTurnLimit} />
                <div id={phaseTurnLimitHintId} className="hint">
                  空白またはカンマで区切って複数指定できます。数値のみの場合は全フェーズ共通の上限になります。
                </div>
              </label>
              <label
                className={`label${errors.maxPhases ? " has-error" : ""}`}
                htmlFor="home-max-phases"
              >
                <span className="label-title">フェーズ数の上限</span>
                <div className="slider-control">
                  <input
                    id="home-max-phases"
                    className={`range-input${errors.maxPhases ? " is-error" : ""}`}
                    type="range"
                    min={1}
                    max={10}
                    step={1}
                    value={resolvedMaxPhasesValue}
                    onChange={(e) => dispatch({ type: "update", field: "maxPhases", value: e.target.value })}
                    aria-invalid={errors.maxPhases ? "true" : "false"}
                    aria-describedby={combineFieldDescriptors(
                      maxPhasesHintId,
                      errors.maxPhases ? maxPhasesErrorId : null,
                    )}
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
                <FieldError id={maxPhasesErrorId} message={errors.maxPhases} />
                <div id={maxPhasesHintId} className="hint">1〜10 の範囲で指定できます。空欄にすると自動判定に任せます。</div>
              </label>
              <div className="label advanced-chat-section">
                <div className="advanced-chat-title">短文チャットモード</div>
                <label className="advanced-chat-toggle" htmlFor="home-chat-mode">
                  <input
                    id="home-chat-mode"
                    type="checkbox"
                    checked={formState.chatMode}
                    onChange={(e) => dispatch({ type: "update", field: "chatMode", value: e.target.checked })}
                    aria-invalid="false"
                    aria-describedby={chatModeHintId}
                  />
                  <span>短文チャットを有効にする</span>
                </label>
                <div id={chatModeHintId} className="hint">既定では有効です。オフにすると従来の長文モードで進行します。</div>
              </div>
              <label
                className={`label${errors.chatMaxSentences ? " has-error" : ""}`}
                htmlFor="home-chat-max"
              >
                <span className="label-title">チャット最大文数</span>
                <div className="slider-control">
                  <input
                    id="home-chat-max"
                    className={`range-input${errors.chatMaxSentences ? " is-error" : ""}`}
                    type="range"
                    min={1}
                    max={6}
                    step={1}
                    value={resolvedChatMaxSentencesValue}
                    onChange={(e) => dispatch({ type: "update", field: "chatMaxSentences", value: e.target.value })}
                    aria-invalid={errors.chatMaxSentences ? "true" : "false"}
                    aria-describedby={combineFieldDescriptors(
                      chatMaxHintId,
                      errors.chatMaxSentences ? chatMaxErrorId : null,
                    )}
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
                <FieldError id={chatMaxErrorId} message={errors.chatMaxSentences} />
                <div id={chatMaxHintId} className="hint">1〜6 の範囲で設定できます。空欄なら既定値 2 を利用します。</div>
              </label>
            </div>
          </StepCard>

          <div className="actions">
            <button
              className="btn"
              type="submit"
              disabled={!formState.topic.trim() || loading || formState.openaiKeyRequired || hasErrors}
            >
              {loading ? "起動中..." : "会議を開始"}
            </button>
          </div>
        </form>

        <aside className="step-summaries" aria-label="設定サマリー">
          <StepSummaryCard title="基本設定" items={basicSummaryItems} />
          <StepSummaryCard title="参加者設定" items={participantsSummaryItems} />
          <StepSummaryCard title="高度な設定" items={advancedSummaryItems} />
        </aside>
      </div>

      <div className="visually-hidden" aria-live="assertive" role="alert">
        {liveMessage}
      </div>
      {error && <div className="form-submit-error">{error}</div>}
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

function StepProgress({ steps }) {
  if (!Array.isArray(steps) || steps.length === 0) {
    return null;
  }
  return (
    <ol className="step-progress" aria-label="設定の進捗">
      {steps.map((step) => (
        <li
          key={step.id}
          className={`step-progress-item${step.current ? " is-current" : ""}${
            step.complete ? " is-complete" : ""
          }`}
        >
          <span className="step-progress-marker" aria-hidden="true" />
          <div className="step-progress-content">
            <span className="step-progress-label">{step.label}</span>
            <span className="step-progress-status">{step.status}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function StepCard({ stepNumber, stepId, title, isOpen, onToggle, children }) {
  const contentId = `${stepId}-content`;
  return (
    <div className={`step-card${isOpen ? " is-open" : ""}`}>
      <button
        type="button"
        className="step-card-toggle"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls={contentId}
      >
        <span className="step-card-index">Step {stepNumber}</span>
        <span className="step-card-title">{title}</span>
        <span className="step-card-icon" aria-hidden="true" />
      </button>
      <div className="step-card-body" id={contentId} hidden={!isOpen}>
        {children}
      </div>
    </div>
  );
}

function StepSummaryCard({ title, items }) {
  const summaryItems = Array.isArray(items) ? items : [];
  return (
    <div className="step-summary-card">
      <h2 className="step-summary-title">{title}</h2>
      <dl className="step-summary-list">
        {summaryItems.map((item) => (
          <div key={item.label} className="step-summary-item">
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

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

function createFormPatchFromPreset(form) {
  if (!form || typeof form !== "object") {
    return {};
  }
  const patch = {};
  FORM_FIELDS.forEach((field) => {
    if (typeof form[field] === "undefined") return;
    if (field === "chatMode") {
      patch.chatMode = Boolean(form[field]);
      return;
    }
    if (typeof form[field] === "string") {
      patch[field] = form[field];
      return;
    }
    if (typeof form[field] === "number") {
      patch[field] = String(form[field]);
    }
  });
  return patch;
}

function buildPresetPayload(formState, participants) {
  if (!formState || typeof formState !== "object") {
    return { form: {}, participants: [] };
  }
  const form = {};
  FORM_FIELDS.forEach((field) => {
    if (field === "chatMode") {
      form.chatMode = Boolean(formState.chatMode);
      return;
    }
    const value = formState[field];
    if (typeof value === "string") {
      form[field] = value;
      return;
    }
    if (typeof value === "number") {
      form[field] = String(value);
      return;
    }
    if (typeof value !== "undefined" && value !== null) {
      form[field] = String(value);
    }
  });
  const participantList = Array.isArray(participants)
    ? participants.map((item) => ({
        name: typeof item?.name === "string" ? item.name : "",
        prompt: typeof item?.prompt === "string" ? item.prompt : "",
      }))
    : [];
  return { form, participants: participantList };
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
