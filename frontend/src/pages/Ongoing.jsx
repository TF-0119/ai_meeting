import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Card from "../components/Card";
import { listMeetings } from "../services/api";

const REFRESH_INTERVAL_MS = 8000;

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

function renderStatusLabel(value, positive = "あり", negative = "なし") {
  return value ? positive : negative;
}

export default function Ongoing() {
  const [meetings, setMeetings] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

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

    fetchMeetings(true);
    const timerId = setInterval(() => {
      fetchMeetings(false);
    }, REFRESH_INTERVAL_MS);

    return () => {
      active = false;
      clearInterval(timerId);
    };
  }, []);

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
          return (
            <li key={meeting.id} className="meeting-list__item">
              <h2 className="meeting-list__title">
                <Link to={`/meeting/${encodeURIComponent(meeting.id)}`}>{title}</Link>
              </h2>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">開始:</span>
                <span className="meeting-list__meta-value">{formatStartedAt(meeting.started_at)}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">バックエンド:</span>
                <span className="meeting-list__meta-value">{meeting.backend || "不明"}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">稼働中:</span>
                <span className="meeting-list__meta-value">{renderStatusLabel(meeting.is_alive, "はい", "いいえ")}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">ライブログ:</span>
                <span className="meeting-list__meta-value">{renderStatusLabel(meeting.has_live)}</span>
              </p>
              <p className="meeting-list__meta">
                <span className="meeting-list__meta-label">結果:</span>
                <span className="meeting-list__meta-value">{renderStatusLabel(meeting.has_result)}</span>
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
