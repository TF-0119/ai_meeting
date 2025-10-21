import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getLiveSnapshot, stopMeeting } from "@/services/api";
import Card from "../components/Card";
import Button from "../components/Button";

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
          {msgs.length === 0 && <div className="muted">（ログを待機中… ファイル未生成の可能性）</div>}
          {msgs.map((m) => (
            <div key={m.id} className="timeline-item">
              <span className="speaker">{m.speaker}</span>
              <span className="text">{m.text}</span>
            </div>
          ))}
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
