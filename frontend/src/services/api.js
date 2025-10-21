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

// バックエンドのヘルスチェック。成功時は ok=true を返す。
export async function getHealth() {
  try {
    const res = await fetch(withCacheBuster("/health"), { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const message = text.trim() || `HTTP ${res.status}`;
      return { status: "error", ok: false, message };
    }
    const payload = await res.json().catch(() => ({}));
    const ok = payload?.ok !== false;
    return { status: "ready", ok, message: ok ? "" : "バックエンドからエラーが返されました。", detail: payload };
  } catch (err) {
    const message = err instanceof Error ? err.message : "ヘルスチェックに失敗しました。";
    return { status: "error", ok: false, message };
  }
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

// 会議情報APIから受け取ったフィールドを最小限の形に整形
function normalizeMeetingRecord(source = {}) {
  const id = typeof source.id === "string" && source.id.trim() ? source.id : String(source.id ?? "");
  const topic = typeof source.topic === "string" ? source.topic : "";
  const backend = typeof source.backend === "string" ? source.backend : "";
  const startedAt = typeof source.started_at === "string" ? source.started_at : "";
  return {
    id,
    topic,
    backend,
    started_at: startedAt,
    is_alive: Boolean(source.is_alive),
    has_live: Boolean(source.has_live),
    has_result: Boolean(source.has_result),
  };
}

// 個別会議の状態（プロセスの生存や生成済みファイル）を取得
export async function getMeetingStatus(meetingId) {
  if (!meetingId) {
    throw new Error("会議IDが指定されていません。");
  }

  const res = await fetch(withCacheBuster(`/api/meetings/${encodeURIComponent(meetingId)}`), {
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const message = text.trim() ? `会議状態の取得に失敗しました: ${text.trim()}` : `会議状態の取得に失敗しました (HTTP ${res.status}).`;
    throw new Error(message);
  }

  const payload = await res.json().catch(() => null);
  if (!payload || payload.ok === false) {
    const detail = typeof payload?.error === "string" && payload.error.trim() ? payload.error.trim() : "会議状態の取得に失敗しました。";
    throw new Error(detail);
  }

  return normalizeMeetingRecord({ ...payload, id: payload?.id ?? meetingId });
}

// 会議一覧と各会議の状態をまとめて取得
export async function listMeetings() {
  const res = await fetch(withCacheBuster("/api/meetings"), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const message = text.trim() ? `会議一覧の取得に失敗しました: ${text.trim()}` : `会議一覧の取得に失敗しました (HTTP ${res.status}).`;
    throw new Error(message);
  }

  const payload = await res.json().catch(() => ({}));
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    return [];
  }

  const baseList = items.map((item) => normalizeMeetingRecord(item));

  const enriched = await Promise.all(
    baseList.map(async (entry) => {
      if (!entry.id) return entry;
      try {
        const status = await getMeetingStatus(entry.id);
        return {
          ...entry,
          ...status,
          started_at: status.started_at || entry.started_at,
          topic: status.topic || entry.topic,
          backend: status.backend || entry.backend,
        };
      } catch {
        return entry;
      }
    })
  );

  return enriched
    .slice()
    .sort((a, b) => {
      const aKey = a.started_at || "";
      const bKey = b.started_at || "";
      if (aKey && bKey && aKey !== bKey) {
        return aKey > bKey ? -1 : 1;
      }
      if (aKey && !bKey) return -1;
      if (!aKey && bKey) return 1;
      return a.id.localeCompare(b.id);
    });
}

export async function stopMeeting(meetingId) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort(new DOMException("Request timed out", "AbortError"));
  }, 15000);

  try {
    const res = await fetch(`/api/meetings/${encodeURIComponent(meetingId)}/stop`, {
      method: "POST",
      signal: controller.signal,
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      const reason = txt.trim();
      throw new Error(`stop meeting failed: ${res.status}${reason ? ` ${reason}` : ""}`);
    }
  } finally {
    clearTimeout(timeoutId);
  }
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

export async function getModels() {
  const res = await fetch(withCacheBuster("/api/models"), {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`fetch failed: ${res.status} /api/models`);
  }
  const payload = await res.json();
  const list = Array.isArray(payload?.models) ? payload.models : Array.isArray(payload) ? payload : [];
  return list
    .map((item) => {
      if (!item) return null;
      if (typeof item === "string") return item;
      if (typeof item.name === "string" && item.name.trim()) return item.name;
      if (typeof item.model === "string" && item.model.trim()) return item.model;
      if (typeof item.id === "string" && item.id.trim()) return item.id;
      return null;
    })
    .filter((name, index, arr) => Boolean(name) && arr.indexOf(name) === index)
    .sort((a, b) => a.localeCompare(b));
}
