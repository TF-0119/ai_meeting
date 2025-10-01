// frontend/src/services/api.js

// キャッシュバスター用のクエリを付与
function withCacheBuster(url) {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}t=${Date.now()}`;
}

// JSONL (1行 = 1 JSON) を配列に変換
export async function fetchJSONL(url) {
  const res = await fetch(withCacheBuster(url), { cache: "no-store" });
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
  const res = await fetch(withCacheBuster(`/logs/${meetingId}/meeting_result.json`), { method: "HEAD" });
  return res.ok;
}

// meeting_result.json（Final/KPI/関連ファイル情報）を取得
export async function getMeetingResult(meetingId) {
  const res = await fetch(withCacheBuster(`/logs/${meetingId}/meeting_result.json`), {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`fetch failed: ${res.status} /logs/${meetingId}/meeting_result.json`);
  }
  const payload = await res.json();
  const kpi = payload.kpi ?? payload.metrics ?? {};
  const files = await ensureFilesExist(payload.files ?? {}, meetingId);
  return {
    topic: payload.topic ?? "",
    final: payload.final ?? "",
    kpi,
    files,
  };
}

async function ensureFilesExist(files, meetingId) {
  const entries = Object.entries(files);
  if (!entries.length) return {};
  const checked = await Promise.all(
    entries.map(async ([key, path]) => {
      if (!path) return [key, null];
      const target = normalizeFilePath(path, meetingId);
      if (!target) return [key, null];
      try {
        const headRes = await fetch(withCacheBuster(target), { method: "HEAD" });
        if (!headRes.ok) return [key, null];
      } catch {
        return [key, null];
      }
      return [key, target];
    })
  );
  return Object.fromEntries(checked.filter(([, path]) => Boolean(path)));
}

function normalizeFilePath(path, meetingId) {
  if (!path) return null;
  if (/^https?:\/\//.test(path) || path.startsWith("/")) {
    return path;
  }
  return `/logs/${meetingId}/${path}`;
}

export async function startMeeting(payload) {
  const res = await fetch("/api/meetings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`start meeting failed: ${res.status} ${txt}`);
  }
  return res.json();
}
