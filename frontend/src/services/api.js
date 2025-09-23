// frontend/src/services/api.js

// JSONL (1行 = 1 JSON) を配列に変換
export async function fetchJSONL(url) {
  const res = await fetch(url + `?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetch failed: ${res.status} ${url}`);
  const text = await res.text();
  return text
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line); } catch { return null; }
    })
    .filter(Boolean);
}

// meeting_live.jsonl → タイムライン配列に整形
export async function getTimeline(meetingId) {
  const url = `/logs/${meetingId}/meeting_live.jsonl`;
  try {
    const rows = await fetchJSONL(url);
    return rows.map((r, i) => ({
      id: r.id ?? r.index ?? i + 1,
      speaker: r.speaker ?? r.role ?? r.agent ?? "unknown",
      text: r.text ?? r.message ?? r.content ?? "",
      ts: r.ts ?? r.time ?? null,
    }));
  } catch (e) {
    // ファイル未生成・一時的な404は空扱い
    return [];
  }
}

// “完了”の簡易判定に使う存在チェック（resultがあれば完了とみなす）
export async function existsResult(meetingId) {
  const res = await fetch(`/logs/${meetingId}/meeting_result.json?t=${Date.now()}`, { method: "HEAD" });
  return res.ok;
}
