import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getMeetingResult } from "../services/api";

export default function Result() {
  const { id } = useParams();
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setResult(null);
    getMeetingResult(id)
      .then((data) => {
        if (cancelled) return;
        setResult(data);
        setStatus("success");
      })
      .catch((err) => {
        console.error(err);
        if (cancelled) return;
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const topic = result?.topic || "（無題）";
  const final = result?.final || "（Finalは未取得）";
  const kpi = result?.kpi || {};
  const files = result?.files || {};

  const filePath = (candidates) => {
    for (const key of candidates) {
      if (files[key]) return files[key];
    }
    return null;
  };

  const downloads = [
    {
      label: "meeting_live.md をDL",
      path: filePath(["meeting_live_md", "meeting_live", "meeting_live.md"]),
    },
    {
      label: "metrics.csv をDL",
      path: filePath(["metrics_csv", "metrics", "metrics.csv"]),
    },
    {
      label: "metrics_cpu_mem.png をDL",
      path: filePath(["metrics_cpu_mem_png", "metrics_cpu_mem", "metrics_cpu_mem.png"]),
    },
  ];

  const items = [
    { key: "progress", label: "Progress" },
    { key: "diversity", label: "Diversity" },
    { key: "decision_density", label: "Decision Density" },
    { key: "spec_coverage", label: "Spec Coverage" },
  ];

  const statusMessage =
    status === "loading"
      ? "結果を読み込み中です..."
      : "結果の取得に失敗しました。時間を置いて再度お試しください。";

  if (status !== "success") {
    return (
      <section className="grid-2">
        <div className="card">
          <h2 className="title-sm">Final</h2>
          <div className="muted">Meeting ID: {id}</div>
          <p className="muted">{statusMessage}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="grid-2">
      <div className="card">
        <h2 className="title-sm">Final</h2>
        <div className="muted">Meeting ID: {id}</div>
        <div className="muted">Topic: {topic}</div>
        <pre className="final">{final}</pre>

        <div className="actions">
          {downloads.map(({ label, path }) =>
            path ? (
              <a
                key={label}
                className="btn ghost"
                href={path}
                download
                rel="noreferrer"
              >
                {label}
              </a>
            ) : (
              <button key={label} className="btn ghost" disabled>
                {label}
              </button>
            )
          )}
        </div>
      </div>

      <aside className="card">
        <h3 className="title-sm">KPI</h3>
        <div className="kpi-grid">
          {items.map(({ key, label }) => (
            <div className="kpi" key={key}>
              <div className="kpi-label">{label}</div>
              <div className="kpi-value">
                {typeof kpi[key] === "number" ? kpi[key].toFixed(2) : "—"}
              </div>
            </div>
          ))}
        </div>
      </aside>
    </section>
  );
}
