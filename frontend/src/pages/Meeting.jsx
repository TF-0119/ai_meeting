import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getLiveSnapshot, stopMeeting } from "@/services/api";
import { createInitials } from "@/utils/text";
import { deriveFlowTrendKind, FLOW_TREND_SYMBOLS } from "@/utils/flow";
import Card from "../components/Card";
import Button from "../components/Button";

// タイムライン用のカラーパレット（CSSカスタムプロパティで共有）
const TIMELINE_COLOR_PALETTE = [
  { bg: "var(--color-accent-soft)", fg: "var(--color-accent)" },
  { bg: "var(--color-success-soft)", fg: "var(--color-success)" },
  { bg: "var(--color-warning-soft)", fg: "var(--color-warning)" },
  { bg: "var(--color-danger-soft)", fg: "var(--color-danger)" },
  { bg: "color-mix(in srgb, var(--color-accent) 24%, transparent)", fg: "var(--color-accent-strong)" },
  { bg: "color-mix(in srgb, var(--color-success) 24%, transparent)", fg: "var(--color-success)" },
];

const INTENT_LABELS = {
  generate: "生成",
  critique: "批評",
  meta: "メタ",
};

const PROGRESS_ICON_MAP = {
  forward: { icon: FLOW_TREND_SYMBOLS.forward, label: "進行度: 議論が前進しています" },
  steady: { icon: FLOW_TREND_SYMBOLS.steady, label: "進行度: 議論は横ばいです" },
  reflect: { icon: FLOW_TREND_SYMBOLS.reflect, label: "進行度: 振り返り局面です" },
};

// 折りたたみ用の概要テキストを取り出す
function extractSnippet(text) {
  if (!text || typeof text !== "string") return "";
  const firstLine = text.split(/\r?\n/).find((line) => line.trim().length > 0);
  return firstLine ? firstLine.trim() : "";
}

// タイムスタンプを画面表示用に整形する
function formatTimestamp(ts) {
  if (!ts) return null;
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return null;
  const label = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const iso = typeof ts === "string" ? ts : date.toISOString();
  return { label, iso };
}

// intent ラベルを正規化
function normalizeIntent(intent) {
  if (!intent) return null;
  if (typeof intent === "object") {
    const candidate = intent.label ?? intent.name ?? intent.kind ?? intent.id;
    if (!candidate) return null;
    return normalizeIntent(candidate);
  }
  const value = String(intent).toLowerCase();
  if (value.includes("generate")) return "generate";
  if (value.includes("critique") || value.includes("critic")) return "critique";
  if (value.includes("meta")) return "meta";
  return null;
}

export default function Meeting() {
  const { id: meetingId } = useParams();      // ← URLの :id が “logs のフォルダ名” と一致している必要あり
  const nav = useNavigate();

  const [msgs, setMsgs] = useState([]);
  const [resultReady, setResultReady] = useState(false);
  const [lastChangeAt, setLastChangeAt] = useState(Date.now());
  const [summary, setSummary] = useState("");
  const [kpi, setKpi] = useState(null);
  const [progress, setProgress] = useState(null);
  const [autoCompleted, setAutoCompleted] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const listRef = useRef(null);

  // ポーリング：5秒ごとに meeting_live.jsonl を読む
  useEffect(() => {
    let stop = false;

    const tick = async () => {
      try {
        const snapshot = await getLiveSnapshot(meetingId);

        setMsgs(prev => {
          if (snapshot.timeline.length !== prev.length) {
            setLastChangeAt(Date.now());
            setAutoCompleted(false);
          }
          return snapshot.timeline;
        });

        setSummary(snapshot.summary || "");
        setKpi(snapshot.kpi);
        setProgress(snapshot.progress);
        if (snapshot.resultReady) {
          setResultReady(true);
        }
      } catch (_) {
        // 読み込み失敗は無視（次のtickで再試行）
      }
      if (!stop) setTimeout(tick, 5000);
    };

    tick();
    return () => { stop = true; };
  }, [meetingId]);

  useEffect(() => {
    setMsgs([]);
    setSummary("");
    setKpi(null);
    setProgress(null);
    setResultReady(false);
    setAutoCompleted(false);
    setLastChangeAt(Date.now());
    setExpandedId(null);
  }, [meetingId]);

  // “完了らしさ”の補助判定：30秒間メッセージ数が増えなければ done 扱い
  useEffect(() => {
    const iv = setInterval(() => {
      if (!resultReady && Date.now() - lastChangeAt > 30000) {
        setAutoCompleted(true);
      }
    }, 5000);
    return () => clearInterval(iv);
  }, [lastChangeAt, resultReady]);

  // 自動スクロール
  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [msgs]);

  useEffect(() => {
    if (expandedId === null) return;
    if (!msgs.some((m) => m.id === expandedId)) {
      setExpandedId(null);
    }
  }, [msgs, expandedId]);

  const toggleExpanded = (id) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const handleEntryClick = (id) => (event) => {
    if (event.detail === 0) return;
    toggleExpanded(id);
  };

  const handleEntryKeyDown = (event, id) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      toggleExpanded(id);
    }
  };

  const timelineItems = useMemo(() => {
    if (!Array.isArray(msgs) || msgs.length === 0) return [];
    const colorMap = new Map();
    let paletteIndex = 0;
    return msgs.map((m) => {
      const primaryName = typeof m.speaker_name === "string" && m.speaker_name.trim().length > 0
        ? m.speaker_name.trim()
        : null;
      const fallbackName = typeof m.speaker === "string" && m.speaker.trim().length > 0
        ? m.speaker.trim()
        : null;
      const personaLabel = typeof m.persona?.label === "string" && m.persona.label.trim().length > 0
        ? m.persona.label.trim()
        : (typeof m.persona?.name === "string" && m.persona.name.trim().length > 0
          ? m.persona.name.trim()
          : null);
      const displayName = primaryName ?? fallbackName ?? personaLabel ?? "unknown";

      if (!colorMap.has(displayName)) {
        colorMap.set(displayName, paletteIndex);
        paletteIndex += 1;
      }
      const palette = TIMELINE_COLOR_PALETTE[colorMap.get(displayName) % TIMELINE_COLOR_PALETTE.length];
      const bandIndex = (colorMap.get(displayName) % TIMELINE_COLOR_PALETTE.length) + 1;

      const text = typeof m.text === "string" ? m.text : "";
      const snippet = extractSnippet(text);
      const initials = typeof m.speaker_initials === "string" && m.speaker_initials.trim().length > 0
        ? m.speaker_initials.trim().slice(0, 2)
        : createInitials(displayName);
      const timestamp = formatTimestamp(m.ts);

      const phaseKind = typeof m.phaseKind === "string"
        ? m.phaseKind
        : typeof m.phase?.kind === "string"
          ? m.phase.kind
          : null;
      const flowTrendKind = m.flowTrendKind ?? deriveFlowTrendKind(phaseKind, m.flowTrend ?? m.flow ?? null);
      const resolvedProgressKind = flowTrendKind ?? "steady";
      const progress = PROGRESS_ICON_MAP[resolvedProgressKind] ?? null;
      const flowTrendSymbol = m.flowTrend ?? progress?.icon ?? null;

      const intentBase = typeof m.intent === "object"
        ? m.intent.label ?? m.intent.name ?? m.intent.kind ?? m.intent.id
        : m.intent;
      const normalizedIntent = normalizeIntent(intentBase);
      const intentChipLabel = normalizedIntent
        ? (INTENT_LABELS[normalizedIntent] ?? intentBase ?? normalizedIntent)
        : (intentBase ?? null);
      const intentDescription = typeof m.intent === "object" && typeof m.intent.description === "string"
        ? m.intent.description
        : null;

      const personaRole = typeof m.persona?.role === "string" && m.persona.role.trim().length > 0
        ? m.persona.role.trim()
        : null;
      const personaDescription = typeof m.persona?.description === "string" && m.persona.description.trim().length > 0
        ? m.persona.description.trim()
        : null;

      const phaseLabel = typeof m.phase?.label === "string" && m.phase.label.trim().length > 0
        ? m.phase.label.trim()
        : (typeof m.phase?.name === "string" && m.phase.name.trim().length > 0
          ? m.phase.name.trim()
          : null);
      const phaseStatus = typeof m.phase?.status === "string" && m.phase.status.trim().length > 0
        ? m.phase.status.trim()
        : null;

      const progressHint = m.progressHint ?? null;
      const progressHintParts = [];
      if (progressHint && typeof progressHint.ratio === "number" && Number.isFinite(progressHint.ratio)) {
        const ratioPercent = Math.round(Math.min(1, Math.max(0, progressHint.ratio)) * 100);
        progressHintParts.push(`推定進捗 ${ratioPercent}%`);
      }
      if (progressHint) {
        const stepParts = [];
        if (typeof progressHint.current === "number" && Number.isFinite(progressHint.current)) {
          stepParts.push(`現在 ${progressHint.current}`);
        }
        if (typeof progressHint.total === "number" && Number.isFinite(progressHint.total)) {
          stepParts.push(`全体 ${progressHint.total}`);
        }
        if (stepParts.length) {
          progressHintParts.push(stepParts.join(" / "));
        }
      }

      const phaseDetailParts = [];
      if (typeof m.phase?.turn === "number" && Number.isFinite(m.phase.turn)) {
        phaseDetailParts.push(`ターン ${m.phase.turn}`);
      }
      if (typeof m.phase?.total === "number" && Number.isFinite(m.phase.total)) {
        phaseDetailParts.push(`合計 ${m.phase.total}`);
      }
      if (typeof m.phase?.progress === "number" && Number.isFinite(m.phase.progress)) {
        const pct = Math.round(Math.min(1, Math.max(0, m.phase.progress)) * 100);
        phaseDetailParts.push(`進捗率 ${pct}%`);
      }
      if (typeof m.phase?.base === "number" && Number.isFinite(m.phase.base)) {
        phaseDetailParts.push(`開始ターン ${m.phase.base}`);
      }
      const phaseDescriptionParts = [...phaseDetailParts];
      if (progressHintParts.length) phaseDescriptionParts.push(...progressHintParts);
      const phaseDescription = phaseDescriptionParts.join(" / ") || null;

      const flowLabel = typeof m.flow === "object"
        ? m.flow.label ?? m.flow.name ?? m.flow.kind ?? null
        : (typeof m.flow === "string" && m.flow.trim().length > 0 ? m.flow.trim() : null);
      const flowDescription = typeof m.flow === "object" && typeof m.flow.description === "string"
        ? m.flow.description
        : null;

      const roundTurnParts = [];
      if (typeof m.round === "number" && Number.isFinite(m.round)) {
        roundTurnParts.push(`ラウンド ${m.round}`);
      }
      if (typeof m.turn === "number" && Number.isFinite(m.turn)) {
        roundTurnParts.push(`ターン ${m.turn}`);
      }

      const flowValueParts = [];
      if (flowTrendSymbol) flowValueParts.push(flowTrendSymbol);
      if (progress?.label) flowValueParts.push(progress.label);
      if (flowLabel && !flowValueParts.includes(flowLabel)) flowValueParts.push(flowLabel);
      const flowValue = flowValueParts.join(" ").trim();

      const details = [];
      if (personaLabel || personaRole || personaDescription) {
        const personaValueParts = [personaLabel, personaRole].filter(Boolean);
        details.push({
          label: "ペルソナ",
          value: personaValueParts.length ? personaValueParts.join(" / ") : (personaDescription ?? "—"),
          description: personaDescription && personaValueParts.length ? personaDescription : null,
        });
      }
      if (intentChipLabel || intentDescription) {
        details.push({
          label: "意図",
          value: intentChipLabel ?? "—",
          description: intentDescription ?? null,
        });
      }
      if (flowValue || flowDescription) {
        details.push({
          label: "フロー",
          value: flowValue || flowDescription || "—",
          description: flowDescription && flowDescription !== flowValue ? flowDescription : null,
        });
      }
      if (phaseLabel || phaseKind || phaseStatus || phaseDescription) {
        const phaseValueParts = [];
        if (phaseLabel) phaseValueParts.push(phaseLabel);
        if (phaseKind && (!phaseLabel || phaseKind !== phaseLabel)) phaseValueParts.push(`種類: ${phaseKind}`);
        if (phaseStatus) phaseValueParts.push(`状態: ${phaseStatus}`);
        const phaseValue = phaseValueParts.join(" / ") || phaseDescription || "—";
        details.push({
          label: "フェーズ",
          value: phaseValue,
          description: phaseDescription && phaseDescription !== phaseValue ? phaseDescription : null,
        });
      }
      if (roundTurnParts.length) {
        details.push({
          label: "インデックス",
          value: roundTurnParts.join(" / "),
          description: null,
        });
      }

      return {
        id: m.id,
        displayName,
        text,
        snippet,
        initials,
        avatar: typeof m.avatar === "string" && m.avatar.trim().length > 0
          ? m.avatar
          : (typeof m.icon === "string" && m.icon.trim().length > 0 ? m.icon.trim() : null),
        timestamp,
        palette,
        bandIndex,
        intentKey: normalizedIntent,
        intentLabel: intentChipLabel,
        intentDescription,
        progressKind: resolvedProgressKind,
        progress,
        flowTrendSymbol,
        details,
      };
    });
  }, [msgs]);

  const memoSummary = useMemo(() => {
    if (summary && summary.trim().length > 0) return summary;
    if (!msgs.length) return "（要約はまだ生成されていません）";
    const tail = msgs.slice(-3).map(m => `・${m.text}`).join("\n");
    return `直近の要点（暫定）:\n${tail}`;
  }, [summary, msgs]);

  const progressPercent = useMemo(() => {
    if (typeof progress !== "number" || Number.isNaN(progress)) return null;
    const clamped = Math.min(1, Math.max(0, progress));
    return Math.round(clamped * 100);
  }, [progress]);

  const done = resultReady || (progressPercent !== null && progressPercent >= 99) || autoCompleted;

  const badge = resultReady
    ? { className: "ok", label: "完了" }
    : progressPercent !== null
      ? { className: "run", label: `集計中 ${progressPercent}%` }
      : { className: "run", label: done ? "終盤" : "進行中" };

  const kpiItems = useMemo(() => ([
    { key: "progress", label: "Progress" },
    { key: "diversity", label: "Diversity" },
    { key: "decision_density", label: "Decision Density" },
    { key: "spec_coverage", label: "Spec Coverage" },
  ]), []);

  const toResult = () => {
    const encodedMeetingId = encodeURIComponent(meetingId);
    nav(`/result/${encodedMeetingId}`);
  };

  const handleStop = async () => {
    if (isStopping) return;
    setIsStopping(true);
    try {
      await stopMeeting(meetingId);
    } catch (err) {
      setIsStopping(false);
      const message = err instanceof Error && err.message
        ? err.message
        : "会議の中止に失敗しました。";
      window.alert(message);
      return;
    }
    setIsStopping(false);
    nav("/");
  };

  return (
    <section className="grid-2" aria-labelledby="meeting-title">
      <Card
        as="article"
        headingLevel="h1"
        title="進行中の会議"
        id="meeting"
        description={`Meeting ID: ${meetingId}`}
        actions={
          <>
            <Button variant="ghost" onClick={handleStop} disabled={isStopping}>
              中止して戻る
            </Button>
            <Button onClick={toResult} disabled={!resultReady}>
              結果へ
            </Button>
          </>
        }
      >
        <div className="row-between" aria-live="polite">
          <span className={`badge ${badge.className}`}>{badge.label}</span>
          <span className="muted">
            {resultReady ? "最終結果が利用可能です" : "集計が完了するまでお待ちください"}
          </span>
        </div>
        <div className="timeline" ref={listRef} aria-live="polite">
          {timelineItems.length === 0 && <div className="muted">（ログを待機中… ファイル未生成の可能性）</div>}
          {timelineItems.map((item) => {
            const expanded = expandedId === item.id;
            const isImageAvatar = typeof item.avatar === "string" && /^(data:|https?:\/\/|\/)/i.test(item.avatar);
            const avatarContent = typeof item.avatar === "string" && !isImageAvatar && item.avatar.trim().length > 0
              ? item.avatar.trim()
              : item.initials;
            const summaryText = item.snippet && item.snippet.trim().length > 0
              ? item.snippet
              : "（本文なし）";
            const bodyText = item.text && item.text.trim().length > 0
              ? item.text
              : "（本文なし）";
            return (
              <article
                key={item.id}
                className={`timeline-card timeline-card--accent-${item.bandIndex}`}
                data-expanded={expanded}
                aria-label={`${item.displayName} の発言`}
                role="button"
                tabIndex={0}
                aria-expanded={expanded}
                onClick={handleEntryClick(item.id)}
                onKeyDown={(event) => handleEntryKeyDown(event, item.id)}
                style={{ "--timeline-accent-bg": item.palette.bg, "--timeline-accent-fg": item.palette.fg }}
              >
                <div className="timeline-card__band" aria-hidden="true" />
                <div className="timeline-card__body">
                  <header className="timeline-card__header">
                    {isImageAvatar ? (
                      <img
                        src={item.avatar}
                        alt={`${item.displayName} のアバター`}
                        className="timeline-card__avatar"
                      />
                    ) : (
                      <span className="timeline-card__initial" aria-hidden="true">
                        {avatarContent}
                      </span>
                    )}
                    <div className="timeline-card__meta">
                      <span className="timeline-card__speaker speaker">{item.displayName}</span>
                      {item.timestamp && (
                        <time className="timeline-card__timestamp" dateTime={item.timestamp.iso}>
                          {item.timestamp.label}
                        </time>
                      )}
                    </div>
                  </header>
                  {(item.intentLabel || item.progress || item.flowTrendSymbol) && (
                    <div className="timeline-card__badges">
                      {item.intentLabel && (
                        <span
                          className={`timeline-chip timeline-chip--intent${item.intentKey ? ` timeline-chip--intent-${item.intentKey}` : ""}`}
                        >
                          {item.intentLabel}
                        </span>
                      )}
                      {item.progress ? (
                        <span
                          className="timeline-chip timeline-chip--progress"
                          title={item.progress.label}
                        >
                          {item.progress.icon}
                        </span>
                      ) : item.flowTrendSymbol ? (
                        <span className="timeline-chip timeline-chip--progress" aria-hidden="true">
                          {item.flowTrendSymbol}
                        </span>
                      ) : null}
                    </div>
                  )}
                  <div className="timeline-card__summary">
                    <p className="timeline-card__summary-text text">{summaryText}</p>
                  </div>
                  <div className="timeline-card__content">
                    <p className="timeline-card__text text">{bodyText}</p>
                    {item.details.length > 0 && (
                      <dl className="timeline-card__details">
                        {item.details.map((detail, detailIndex) => (
                          <div className="timeline-card__detail" key={`${item.id}-${detail.label}-${detailIndex}`}>
                            <dt>{detail.label}</dt>
                            <dd>
                              <span>{detail.value}</span>
                              {detail.description && (
                                <p className="timeline-card__detail-note">{detail.description}</p>
                              )}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
        {!resultReady && (
          <p className="hint" role="note">
            meeting_result.json の生成完了後に「結果へ」ボタンが有効になります。
          </p>
        )}
      </Card>

      <Card as="aside" title="要約" headingLevel="h2" id="meeting-summary">
        <pre className="summary" aria-live="polite">
          {memoSummary}
        </pre>
        <div className="hint">
          {resultReady
            ? "バックエンドから受け取った最終要約です。"
            : summary
              ? "バックエンド計算の最新ラウンド要約です。"
              : "要約算出を待機中です。"}
        </div>
        <div className="hint">
          {progressPercent !== null
            ? `KPI Progress: ${progressPercent}%`
            : "KPI 指標を計算中です。"}
        </div>
        {kpi && Object.keys(kpi).length > 0 && (
          <div className="kpi-grid inline">
            {kpiItems.map(({ key, label }) => (
              <div className="kpi" key={key}>
                <div className="kpi-label">{label}</div>
                <div className="kpi-value">
                  {typeof kpi[key] === "number" ? kpi[key].toFixed(2) : "—"}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </section>
  );
}
