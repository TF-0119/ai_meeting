import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getLiveSnapshot, stopMeeting } from "@/services/api";
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
  forward: { icon: "↗", label: "進行度: 議論が前進しています" },
  steady: { icon: "→", label: "進行度: 議論は横ばいです" },
  reflect: { icon: "↘", label: "進行度: 振り返り局面です" },
};

// 話者名からイニシャルを生成する
function createInitials(name) {
  if (!name || typeof name !== "string") return "?";
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const tokens = trimmed.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return trimmed.charAt(0).toUpperCase();
  const letters = tokens.length === 1
    ? [tokens[0].charAt(0)]
    : [tokens[0].charAt(0), tokens[tokens.length - 1].charAt(0)];
  const joined = letters.join("").trim();
  if (!joined) return trimmed.charAt(0).toUpperCase();
  return joined.toUpperCase().slice(0, 2);
}

// flow や phase.kind から進行度アイコン種別を決める
function resolveFlowTrend(flow) {
  if (flow == null) return null;
  if (typeof flow === "number" && Number.isFinite(flow)) {
    if (flow >= 0.66) return "forward";
    if (flow <= 0.33) return "reflect";
    return "steady";
  }
  if (typeof flow === "string") {
    const normalized = flow.toLowerCase();
    if (/(up|forward|rise|fast|positive|accelerat)/.test(normalized)) return "forward";
    if (/(down|back|slow|negative|regress|declin)/.test(normalized)) return "reflect";
    if (/(steady|flat|hold|neutral|calm)/.test(normalized)) return "steady";
    return null;
  }
  if (typeof flow === "object") {
    if (typeof flow.trend === "string") return resolveFlowTrend(flow.trend);
    if (typeof flow.direction === "string") return resolveFlowTrend(flow.direction);
    if (typeof flow.delta === "number") return resolveFlowTrend(flow.delta);
    if (typeof flow.score === "number") return resolveFlowTrend(flow.score);
  }
  return null;
}

function deriveProgressKind(phaseKind, flow) {
  const flowResult = resolveFlowTrend(flow);
  if (flowResult) return flowResult;
  const kind = typeof phaseKind === "string" ? phaseKind.toLowerCase() : "";
  switch (kind) {
    case "resolution":
    case "decision":
    case "action":
    case "synthesis":
      return "forward";
    case "wrapup":
    case "review":
    case "retrospective":
    case "reflection":
      return "reflect";
    default:
      return "steady";
  }
}

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
      const speakerName = typeof m.speaker === "string" && m.speaker.trim().length > 0
        ? m.speaker.trim()
        : "unknown";
      if (!colorMap.has(speakerName)) {
        colorMap.set(speakerName, paletteIndex);
        paletteIndex += 1;
      }
      const palette = TIMELINE_COLOR_PALETTE[colorMap.get(speakerName) % TIMELINE_COLOR_PALETTE.length];
      const phaseKind = typeof m.phase?.kind === "string" ? m.phase.kind : null;
      const progressKind = deriveProgressKind(phaseKind, m.flow);
      const normalizedIntent = normalizeIntent(m.intent);
      const timestamp = formatTimestamp(m.ts);
      return {
        id: m.id,
        speaker: speakerName,
        text: typeof m.text === "string" ? m.text : "",
        initials: createInitials(speakerName),
        snippet: extractSnippet(m.text),
        accentStyle: {
          "--timeline-accent-bg": palette.bg,
          "--timeline-accent-fg": palette.fg,
        },
        intent: normalizedIntent,
        intentLabel: normalizedIntent ? INTENT_LABELS[normalizedIntent] : null,
        phase: m.phase ?? null,
        phaseKind,
        timestamp,
        progress: PROGRESS_ICON_MAP[progressKind] ?? null,
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
          {timelineItems.length === 0 && (
            <div className="muted">（ログを待機中… ファイル未生成の可能性）</div>
          )}
          {timelineItems.map((item) => {
            const isExpanded = expandedId === item.id;
            const detailId = `timeline-detail-${item.id}`;
            return (
              <button
                key={item.id}
                type="button"
                className={`timeline-entry${isExpanded ? " is-expanded" : ""}`}
                onClick={handleEntryClick(item.id)}
                onKeyDown={(event) => handleEntryKeyDown(event, item.id)}
                aria-expanded={isExpanded ? "true" : "false"}
                aria-controls={detailId}
                style={item.accentStyle}
              >
                <span className="timeline-entry-accent" aria-hidden="true">
                  <span className="timeline-entry-initial">{item.initials}</span>
                </span>
                <div className="timeline-entry-main">
                  <div className="timeline-entry-summary">
                    <span className="timeline-entry-speaker">{item.speaker}</span>
                    {item.timestamp && (
                      <time dateTime={item.timestamp.iso} className="timeline-entry-time">
                        {item.timestamp.label}
                      </time>
                    )}
                  </div>
                  <p className="timeline-entry-snippet">
                    {item.snippet || (item.text ? "…" : "（本文なし）")}
                  </p>
                  <div
                    id={detailId}
                    className={`timeline-entry-details${isExpanded ? " is-open" : ""}`}
                    hidden={!isExpanded}
                  >
                    <div className="timeline-entry-profile">
                      <span className="timeline-avatar" aria-hidden="true">
                        {item.initials}
                      </span>
                      <div className="timeline-entry-profile-body">
                        <span className="timeline-entry-speaker-full">{item.speaker}</span>
                        {item.phaseKind && (
                          <span className="timeline-entry-phase">フェーズ: {item.phaseKind}</span>
                        )}
                        {typeof item.phase?.turn === "number" && (
                          <span className="timeline-entry-phase-turn">ターン {item.phase.turn}</span>
                        )}
                      </div>
                      {item.progress && (
                        <span
                          className="timeline-entry-progress"
                          role="img"
                          aria-label={item.progress.label}
                          title={item.progress.label}
                        >
                          {item.progress.icon}
                        </span>
                      )}
                    </div>
                    <div className="timeline-entry-text">
                      {item.text || <span className="muted">（本文なし）</span>}
                    </div>
                    <div className="timeline-entry-tags">
                      {item.intentLabel && (
                        <span className={`timeline-intent-tag intent-${item.intent}`}>
                          {item.intentLabel}
                        </span>
                      )}
                      {item.phaseKind && (
                        <span className="timeline-phase-tag">{item.phaseKind}</span>
                      )}
                    </div>
                  </div>
                </div>
              </button>
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
