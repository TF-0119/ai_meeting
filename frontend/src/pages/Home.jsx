import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { chat } from "../services/api";

export default function Home() {
  const nav = useNavigate();
  const [topic, setTopic] = useState("");
  const [precision, setPrecision] = useState(5);
  const [rounds, setRounds] = useState(4);
  const [agents, setAgents] = useState("planner worker critic");

  const onSubmit = (e) => {
    e.preventDefault();
    // 仮の会議ID（実運用はバックエンドから受け取る想定）
    const id = String(Date.now());
    // Meeting画面へ。queryにフォーム値を渡す（後でAPI化したら置換）
    const params = new URLSearchParams({
      topic,
      precision,
      rounds,
      agents,
    }).toString();
    nav(`/meeting/${id}?${params}`);
  };

  const [input, setInput] = useState("");
  const [answer, setAnswer] = useState("");

  async function onSend() {
    setAnswer("...thinking...");
    try {
      const data = await chat(input, { temperature: 0.7 });
      setAnswer(data.response);
    } catch (e) {
      setAnswer(String(e));
    }
  }


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
          <button className="btn" type="submit" disabled={!topic.trim()}>会議を開始</button>
        </div>
      </form>
      <div style={{ padding: "1rem", marginTop: "1rem", borderTop: "1px solid #ddd" }}>
        <h2>LLM テスト</h2>
        <textarea
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="質問を入力..."
          style={{ width: "100%" }}
        />
        <br />
        <button onClick={onSend}>送信</button>
        <pre style={{ whiteSpace: "pre-wrap" }}>{answer}</pre>
      </div>

    </section>
  );
}
