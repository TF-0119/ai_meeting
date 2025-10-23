import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Card from "../components/Card";
import Button from "../components/Button";
import { listMeetings, getMeetingStatusDetail, stopMeeting } from "../services/api";

const MEETING_REFRESH_INTERVAL_MS = 8000;
const STATUS_REFRESH_INTERVAL_MS = 5000;

function formatStartedAt(startedAt) {
  if (!startedAt) {
    return "開始時刻不明";
  }

  const match = /^([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})$/.exec(startedAt);
  if (!match) {
    return startedAt;
  }

  const [, year, month, day, hour, minute, second] = match;
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

export default function Ongoing() {
  const [meetings, setMeetings] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusMap, setStatusMap] = useState({});
  const [stoppingMap, setStoppingMap] = useState({});
  const fetchMeetingsRef = useRef(async () => {});

  useEffect(() => {
    let active = true;

    const fetchMeetings = async (showLoading = false) => {
      if (!active) return;
      if (showLoading) {
        setIsLoading(true);
      }
      try {
        const items = await listMeetings();
        if (!active) return;
        setMeetings(items);
        setError("");
      } catch (err) {
        if (!active) return;
        const message = err instanceof Error && err.message ? err.message : "会議一覧の取得に失敗しました。";
        setError(message);
        setMeetings([]);
      } finally {
        if (!active) return;
        setIsLoading(false);
      }
    };

    fetchMeetingsRef.current = fetchMeetings;

    fetchMeetings(true);
    const timerId = setInterval(() => {
      fetchMeetings(false);
    }, MEETING_REFRESH_INTERVAL_MS);

    return () => {
      active = false;
      clearInterval(timerId);
    };
  }, []);

  useEffect(() => {
    const validMeetings = meetings.filter((meeting) => Boolean(meeting?.id));
    if (!validMeetings.length) {
      setStatusMap({});
      return undefined;
    }

    let cancelled = false;

    const refreshStatuses = async () => {
      const entries = await Promise.all(
        validMeetings.map(async (meeting) => {
          try {
            const detail = await getMeetingStatusDetail(meeting.id, meeting.log_id);
            return [meeting.id, detail];
          } catch (_) {
            return [meeting.id, {
              is_alive: Boolean(meeting.is_alive),
              has_result: Boolean(meeting.has_result),
              summary: "",
            }];
          }
        }),
      );

      if (cancelled) return;

      const next = {};
      entries.forEach(([id, detail]) => {
        if (!id) return;
        next[id] = detail;
      });
      setStatusMap(next);
    };

    refreshStatuses().catch(() => {});
    const timerId = setInterval(() => {
      refreshStatuses().catch(() => {});
    }, STATUS_REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timerId);
    };
  }, [meetings]);

  const handleStop = async (meetingId) => {
    if (!meetingId || stoppingMap[meetingId]) {
      return;
    }

    setStoppingMap((prev) => ({ ...prev, [meetingId]: true }));

    let stopError = null;
    try {
      await stopMeeting(meetingId);
    } catch (err) {
      stopError = err;
    }

    if (stopError) {
      const message = stopError instanceof Error && stopError.message
        ? stopError.message
        : "会議の中止に失敗しました。";
      window.alert(message);
      setStoppingMap((prev) => {
        const next = { ...prev };
        delete next[meetingId];
        return next;
      });
      return;
    }

    try {
      await fetchMeetingsRef.current(true);
    } catch (_) {
      // 取得失敗時は fetchMeetings 側でエラー表示されるため、ここでは握りつぶす
    } finally {
      setStoppingMap((prev) => {
        const next = { ...prev };
        delete next[meetingId];
        return next;
      });
    }
  };

  let content;
  if (isLoading) {
    content = <p className="muted">読み込み中です…</p>;
  } else if (error) {
    content = (
      <p className="error" role="alert">
        {error}
      </p>
    );
  } else if (!meetings.length) {
    content = (
      <p className="muted">
        現在進行中の会議はありません。会議が開始されるとここに表示されます。
      </p>
    );
  } else {
    content = (
      <ul className="meeting-list" aria-live="polite">
        {meetings.map((meeting) => {
          const title = meeting.topic?.trim() ? meeting.topic : "（トピック未設定）";
          const status = statusMap[meeting.id] ?? {
            is_alive: Boolean(meeting.is_alive),
            has_result: Boolean(meeting.has_result),
            summary: "",
          };
          const isAlive = Boolean(status.is_alive);
          const hasResult = Boolean(status.has_result);
          const summaryTextRaw = typeof status.summary === "string" ? status.summary.trim() : "";
          const summaryText = summaryTextRaw || "サマリーはまだありません。";
          const summaryClassName = `meeting-list__summary${summaryTextRaw ? "" : " meeting-list__summary--empty"}`;
          const preferredId = typeof meeting.log_id === "string" && meeting.log_id.trim().length > 0
            ? meeting.log_id.trim()
            : meeting.id;
          const meetingUrl = `/meeting/${encodeURIComponent(preferredId)}`;
          const resultUrl = `/result/${encodeURIComponent(preferredId)}`;
          const isStopping = Boolean(stoppingMap[meeting.id]);
          return (
            <li key={meeting.id} className="meeting-list__item">
              <h2 className="meeting-list__title">
                <Link to={meetingUrl}>{title}</Link>
              </h2>
              <div className="meeting-list__status" aria-label="会議の状態">
                <span className={`meeting-status-badge ${isAlive ? "meeting-status-badge--alive" : "meeting-status-badge--stopped"}`}>
                  {isAlive ? "稼働中" : "停止中"}
                </span>
                <span className={`meeting-status-badge ${hasResult ? "meeting-status-badge--result" : "meeting-status-badge--pending"}`}>
                  {hasResult ? "結果あり" : "結果待ち"}
                </span>
              </div>
              <p className={summaryClassName}>
                <span className="meeting-list__summary-label">最新サマリー:</span>
                <span className="meeting-list__summary-text">{summaryText}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">開始:</span>
                <span className="meeting-list__meta-value">{formatStartedAt(meeting.started_at)}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">バックエンド:</span>
                <span className="meeting-list__meta-value">{meeting.backend || "不明"}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">ライブログ:</span>
                <span className="meeting-list__meta-value">{meeting.has_live ? "あり" : "なし"}</span>
              </p>
              <p className="meeting-list__actions">
                <Button
                  variant="danger"
                  onClick={() => handleStop(meeting.id)}
                  disabled={!meeting.id || isStopping}
                  isLoading={isStopping}
                >
                  {isStopping ? "停止中…" : "停止"}
                </Button>
                {hasResult ? (
                  <Link className="meeting-list__result-link" to={resultUrl}>
                    結果を見る
                  </Link>
                ) : null}
              </p>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section aria-labelledby="ongoing-title">
      <Card as="article" title="進行中の会議" headingLevel="h1" id="ongoing">
        {content}
      </Card>
    </section>
  );
}
