import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getTimeline, existsResult } from "@/services/api";

export default function Meeting() {
  const { id: meetingId } = useParams();      // ← URLの :id が “logs のフォルダ名” と一致している必要あり
  const nav = useNavigate();

  const [msgs, setMsgs] = useState([]);
  const [done, setDone] = useState(false);
  const [lastChangeAt, setLastChangeAt] = useState(Date.now());
  const listRef = useRef(null);

  // ポーリング：5秒ごとに meeting_live.jsonl を読む
  useEffect(() => {
    let stop = false;

    const tick = async () => {
      try {
        const [arr, hasResult] = await Promise.all([
          getTimeline(meetingId),
          existsResult(meetingId),
        ]);

        setMsgs(prev => {
          if (arr.length !== prev.length) setLastChangeAt(Date.now());
          return arr;
        });

        if (hasResult) setDone(true);
      } catch (_) {
        // 読み込み失敗は無視（次のtickで再試行）
      }
      if (!stop) setTimeout(tick, 5000);
    };

    tick();
    return () => { stop = true; };
  }, [meetingId]);

  // “完了らしさ”の補助判定：30秒間メッセージ数が増えなければ done 扱い
  useEffect(() => {
    const iv = setInterval(() => {
      if (Date.now() - lastChangeAt > 30000) setDone(true);
    }, 5000);
    return () => clearInterval(iv);
  }, [lastChangeAt]);

  // 自動スクロール
  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [msgs]);

  // 直近3件のダミー要約（後でバックエンド要約に差し替え）
  const summary = useMemo(() => {
    if (!msgs.length) return "（要約はここに流れます）";
    const tail = msgs.slice(-3).map(m => `・${m.text}`).join("\n");
    return `直近の要点:\n${tail}`;
  }, [msgs]);

  const toResult = () => nav(`/result/${meetingId}`);

  return (
    <section className="grid-2">
      <div className="card">
        <div className="row-between">
          <h2 className="title-sm">進行中の会議</h2>
          <span className={`badge ${done ? "ok" : "run"}`}>{done ? "完了" : "進行中"}</span>
        </div>
        <div className="muted">Meeting ID: {meetingId}</div>

        <div className="timeline" ref={listRef}>
          {msgs.length === 0 && <div className="muted">（ログを待機中… ファイル未生成の可能性）</div>}
          {msgs.map(m => (
            <div key={m.id} className="timeline-item">
              <span className="speaker">{m.speaker}</span>
              <span className="text">{m.text}</span>
            </div>
          ))}
        </div>

        <div className="actions">
          <button className="btn ghost" onClick={() => nav("/")}>中止して戻る</button>
          <button className="btn" onClick={toResult} disabled={!done}>結果へ</button>
        </div>
      </div>

      <aside className="card">
        <h3 className="title-sm">要約</h3>
        <pre className="summary">{summary}</pre>
        <div className="hint">※ 現在はフロント側の簡易要約。後でバックエンドに差し替え。</div>
      </aside>
    </section>
  );
}
