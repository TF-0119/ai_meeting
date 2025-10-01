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

function parseLiveRows(rows) {
  const timeline = [];
  let latestSummary = "";
  let latestFinal = "";

  rows.forEach((r, i) => {
    const type = (r.type ?? "").toLowerCase();
    const inferredType = type
      || (Object.prototype.hasOwnProperty.call(r, "summary") ? "summary"
        : Object.prototype.hasOwnProperty.call(r, "final") ? "final"
        : "turn");

    if (inferredType === "summary") {
      const summaryText = r.summary ?? r.text ?? r.message ?? r.content ?? "";
      if (summaryText) {
        latestSummary = summaryText;
      }
      return;
    }

    if (inferredType === "final") {
      const finalText = r.final ?? r.text ?? r.message ?? r.content ?? "";
      if (finalText) {
        latestFinal = finalText;
      }
      return;
    }

    if (inferredType !== "turn") {
      // 未知タイプはそのままスキップ
      return;
    }

    timeline.push({
      id: r.id ?? r.index ?? r.turn ?? i + 1,
      speaker: r.speaker ?? r.role ?? r.agent ?? "unknown",
      text: r.text ?? r.message ?? r.content ?? "",
      ts: r.ts ?? r.time ?? r.timestamp ?? null,
    });
  });

  return { timeline, latestSummary, latestFinal };
}

// meeting_live.jsonl → タイムライン配列に整形
export async function getTimeline(meetingId) {
  const url = `/logs/${meetingId}/meeting_live.jsonl`;
  try {
    const rows = await fetchJSONL(url);
    return parseLiveRows(rows).timeline;
  } catch (e) {
    // ファイル未生成・一時的な404は空扱い
    return [];
  }
}

async function fetchOptionalJSON(url) {
  try {
    const res = await fetch(withCacheBuster(url), { cache: "no-store" });
    if (!res.ok) return null;
    const text = await res.text();
    if (!text.trim()) return null;
    return JSON.parse(text);
  } catch (err) {
    return null;
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

export async function tryGetMeetingResult(meetingId) {
  return fetchOptionalJSON(`/logs/${meetingId}/meeting_result.json`);
}

async function getKpi(meetingId) {
  const data = await fetchOptionalJSON(`/logs/${meetingId}/kpi.json`);
  if (!data || typeof data !== "object") return {};
  return data;
}

export async function getLiveSnapshot(meetingId) {
  const url = `/logs/${meetingId}/meeting_live.jsonl`;
  let rows = [];
  try {
    rows = await fetchJSONL(url);
  } catch (_) {
    rows = [];
  }

  const { timeline, latestSummary, latestFinal } = parseLiveRows(rows);

  const [kpi, result] = await Promise.all([
    getKpi(meetingId),
    tryGetMeetingResult(meetingId),
  ]);

  const progress = typeof kpi.progress === "number" ? kpi.progress : null;
  const finalText = result?.final ?? latestFinal ?? "";
  const summaryText = latestSummary || finalText || "";
  const resultReady = Boolean(result && typeof result.final === "string" && result.final.trim().length > 0);

  return {
    timeline,
    summary: summaryText,
    kpi,
    progress,
    resultReady,
    final: finalText,
    topic: result?.topic ?? "",
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
