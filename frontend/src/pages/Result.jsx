import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Card from "../components/Card";
import Button from "../components/Button";
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
      <section className="grid-2" aria-labelledby="result-title">
        <Card as="article" headingLevel="h1" title="Final" id="result" description={`Meeting ID: ${id}`}>
          <p className="muted">{statusMessage}</p>
        </Card>
      </section>
    );
  }

  return (
    <section className="grid-2" aria-labelledby="result-title">
      <Card
        as="article"
        headingLevel="h1"
        title="Final"
        id="result"
        description={`Meeting ID: ${id}`}
        actions={
          <>
            {downloads.map(({ label, path }) =>
              path ? (
                <Button key={label} as="a" variant="ghost" href={path} download rel="noreferrer">
                  {label}
                </Button>
              ) : (
                <Button key={label} variant="ghost" disabled>
                  {label}
                </Button>
              )
            )}
          </>
        }
      >
        <p className="muted">Topic: {topic}</p>
        <pre className="final" aria-live="polite">
          {final}
        </pre>
      </Card>

      <Card as="aside" title="KPI" headingLevel="h2" id="result-kpi">
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
      </Card>
    </section>
  );
}
