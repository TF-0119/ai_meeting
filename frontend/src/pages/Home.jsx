import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { startMeeting } from "../services/api";

export default function Home() {
  const nav = useNavigate();
  const [topic, setTopic] = useState("");
  const [precision, setPrecision] = useState(5);
  const [rounds, setRounds] = useState(4);
  const [agents, setAgents] = useState("planner worker critic");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setLoading(true);
    try {
      const precisionValue = Number(precision) || 5;
      const roundsValue = Number(rounds) || 4;
      const payload = {
        topic: topic.trim(),
        precision: precisionValue,
        rounds: roundsValue,
        agents: agents.trim(),
        backend: "ollama",
      };
      const data = await startMeeting(payload);
      const outdir = typeof data.outdir === "string" ? data.outdir.replace(/\\/g, "/") : "";
      const match = outdir.startsWith("logs/") ? outdir.slice(5) : outdir;
      const meetingId = match || data.id;
      if (!meetingId) {
        throw new Error("会議IDの取得に失敗しました。");
      }
      const params = new URLSearchParams({
        topic,
        precision: String(precisionValue),
        rounds: String(roundsValue),
        agents,
      }).toString();
      nav(`/meeting/${meetingId}?${params}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };


  return (
    <section className="card">
      <h1 className="title">会議の作成</h1>
      <form className="form" onSubmit={onSubmit}>
        <label className="label">
          テーマ
          <input className="input" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="例: 10分で遊べる1畳スポーツの仕様" required />
        </label>

        <div className="grid-2">
          <label className="label">
            精密度 (1-10)
            <input className="input" type="number" min={1} max={10} value={precision} onChange={(e) => setPrecision(e.target.value)} />
          </label>
          <label className="label">
            ラウンド数
            <input className="input" type="number" min={1} max={12} value={rounds} onChange={(e) => setRounds(e.target.value)} />
          </label>
        </div>

        <label className="label">
          エージェント（空白区切り）
          <input className="input" value={agents} onChange={(e) => setAgents(e.target.value)} placeholder="planner worker critic" />
        </label>

        <div className="actions">
          <button className="btn" type="submit" disabled={!topic.trim() || loading}>
            {loading ? "起動中..." : "会議を開始"}
          </button>
        </div>
      </form>
      {error && <div className="error" style={{ color: "#d00", marginTop: "1rem" }}>{error}</div>}
    </section>
  );
}
