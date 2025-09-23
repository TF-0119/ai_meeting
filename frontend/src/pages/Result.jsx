import { useLocation, useParams } from "react-router-dom";

function useQuery() {
  const { search } = useLocation();
  return new URLSearchParams(search);
}

export default function Result() {
  const { id } = useParams();
  const q = useQuery();
  const topic = q.get("topic") || "（無題）";
  const final = decodeURIComponent(q.get("final") || "（Finalは未取得）");
  let kpi;
  try {
    kpi = JSON.parse(decodeURIComponent(q.get("kpi") || "{}"));
  } catch {
    kpi = {};
  }

  const items = [
    { key: "progress", label: "Progress" },
    { key: "diversity", label: "Diversity" },
    { key: "decision_density", label: "Decision Density" },
    { key: "spec_coverage", label: "Spec Coverage" },
  ];

  return (
    <section className="grid-2">
      <div className="card">
        <h2 className="title-sm">Final</h2>
        <div className="muted">Meeting ID: {id}</div>
        <div className="muted">Topic: {topic}</div>
        <pre className="final">{final}</pre>

        <div className="actions">
          <button className="btn ghost" disabled>meeting_live.md をDL</button>
          <button className="btn ghost" disabled>metrics.csv をDL</button>
          <button className="btn ghost" disabled>metrics_cpu_mem.png をDL</button>
        </div>
        <div className="hint">※ 今はダミー。後でログ/画像が生成されたら有効化。</div>
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
