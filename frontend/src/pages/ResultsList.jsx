import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Card from "../components/Card";
import { listResults } from "../services/api";

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

export default function ResultsList() {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    setStatus("loading");
    setError("");

    listResults()
      .then((data) => {
        if (cancelled) return;
        setItems(Array.isArray(data) ? data : []);
        setStatus("success");
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof Error && err.message
          ? err.message
          : "結果一覧の取得に失敗しました。";
        setItems([]);
        setError(message);
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  let content;
  if (status === "loading") {
    content = <p className="muted">読み込み中です…</p>;
  } else if (status === "error") {
    content = <p className="error" role="alert">{error}</p>;
  } else if (!items.length) {
    content = <p className="muted">会議結果が見つかりませんでした。</p>;
  } else {
    const validItems = items.filter((item) => {
      const id = item?.id || item?.meeting_id;
      return typeof id === "string" && id.trim();
    });

    if (!validItems.length) {
      content = <p className="muted">会議結果が見つかりませんでした。</p>;
    } else {
      content = (
        <ul className="results-list" aria-live="polite">
          {validItems.map((item) => {
            const id = (item?.id || item?.meeting_id || "").trim();
            const title = typeof item.topic === "string" && item.topic.trim() ? item.topic.trim() : "（トピック未設定）";
            const startedLabel = formatStartedAt(item.started_at);
            const finalRaw = typeof item.final === "string" ? item.final : "";
            const normalizedFinal = finalRaw.replace(/\r\n/g, "\n");
            const finalText = normalizedFinal.trim();
            const finalClassName = `results-list__final${finalText ? "" : " results-list__final--empty"}`;
            const detailUrl = `/result/${encodeURIComponent(id)}`;

            return (
              <li key={id} className="results-list__item">
                <div className="results-list__header">
                  <h2 className="results-list__title">
                    <Link to={detailUrl}>{title}</Link>
                  </h2>
                  <p className="results-list__meta">
                    <span className="results-list__meta-label">Meeting ID:</span>
                    <span className="results-list__meta-value">{id}</span>
                  </p>
                  <p className="results-list__meta">
                    <span className="results-list__meta-label">開始:</span>
                    <span className="results-list__meta-value">{startedLabel}</span>
                  </p>
                </div>
                <div className="results-list__body">
                  <p className="results-list__final-label">Final</p>
                  <pre className={finalClassName} aria-live="polite">
                    {finalText || "Finalはまだありません。"}
                  </pre>
                </div>
                <div className="results-list__actions">
                  <Link className="results-list__link" to={detailUrl}>
                    詳細を見る
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      );
    }
  }

  return (
    <section aria-labelledby="results-title">
      <Card as="article" title="結果一覧" headingLevel="h1" id="results">
        {content}
      </Card>
    </section>
  );
}
