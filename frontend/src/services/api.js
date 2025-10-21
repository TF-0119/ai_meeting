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

function toOptionalString(value) {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return null;
}

function toOptionalNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

/**
 * @typedef {Object} LiveLabeledEntity
 * @property {string|null} id IDやスラッグなどの識別子。
 * @property {string|null} name 正式名称。
 * @property {string|null} label UI表示向けラベル。
 * @property {string|null} kind 種別。
 * @property {string|null} description 詳細説明。
 * @property {string|null} icon 代表アイコン。
 */

function normalizeLabeledEntity(raw) {
  if (!raw) return null;
  if (typeof raw === "string") {
    const text = raw.trim();
    if (!text) return null;
    return {
      id: null,
      name: text,
      label: text,
      kind: null,
      description: null,
      icon: null,
    };
  }
  if (typeof raw !== "object") return null;

  const idCandidate = raw.id ?? raw.slug ?? raw.code ?? raw.identifier ?? raw.intent_id ?? raw.flow_id;
  const nameCandidate = raw.name ?? raw.title;
  const labelCandidate = raw.label ?? raw.display ?? nameCandidate;
  const kindCandidate = raw.kind ?? raw.type ?? raw.category;
  const descCandidate = raw.description ?? raw.detail ?? raw.summary ?? raw.text;
  const iconCandidate = raw.icon ?? raw.emoji ?? raw.avatar;

  return {
    id: toOptionalString(idCandidate),
    name: toOptionalString(nameCandidate),
    label: toOptionalString(labelCandidate),
    kind: toOptionalString(kindCandidate),
    description: toOptionalString(descCandidate),
    icon: toOptionalString(iconCandidate),
  };
}

/**
 * @typedef {LiveLabeledEntity & {role: string|null}} LivePersona
 */

function normalizePersona(raw) {
  const base = normalizeLabeledEntity(raw);
  if (!base) return null;
  if (typeof raw === "object" && raw !== null) {
    const roleCandidate = raw.role ?? raw.persona ?? raw.archetype ?? raw.kind ?? raw.type;
    const detailCandidate = raw.summary ?? raw.description ?? raw.detail ?? raw.about;
    return {
      ...base,
      role: toOptionalString(roleCandidate),
      description: toOptionalString(detailCandidate) ?? base.description,
    };
  }
  return {
    ...base,
    role: null,
  };
}

/**
 * @typedef {Object} LivePhaseInfo
 * @property {string|null} id フェーズID。
 * @property {string|null} kind フェーズ種別。
 * @property {string|null} name 名称。
 * @property {string|null} label 表示ラベル。
 * @property {number|null} turn 現在ターン（フェーズ内）。
 * @property {number|null} total 想定ターン数/上限。
 * @property {number|null} progress 進行率（0-1想定）。
 * @property {string|null} status 状態。
 * @property {number|null} ordinal 通番。
 */

function normalizePhase(rawPhase) {
  if (!rawPhase) return null;
  if (typeof rawPhase === "string") {
    const text = rawPhase.trim();
    if (!text) return null;
    return {
      id: text,
      kind: null,
      name: text,
      label: text,
      turn: null,
      total: null,
      progress: null,
      status: null,
      ordinal: null,
    };
  }
  if (typeof rawPhase !== "object") return null;

  const idCandidate = rawPhase.id ?? rawPhase.phase_id;
  const kindCandidate = rawPhase.kind ?? rawPhase.type;
  const nameCandidate = rawPhase.name ?? rawPhase.label;
  const labelCandidate = rawPhase.label ?? rawPhase.name;
  const turnCandidate = rawPhase.turn ?? rawPhase.current_turn ?? rawPhase.index ?? rawPhase.step;
  const totalCandidate = rawPhase.total ?? rawPhase.turn_limit ?? rawPhase.count ?? rawPhase.steps;
  const progressCandidate = rawPhase.progress ?? rawPhase.ratio ?? rawPhase.percent;
  const statusCandidate = rawPhase.status ?? rawPhase.state;
  const ordinalCandidate = rawPhase.ordinal ?? rawPhase.order ?? rawPhase.sequence;

  return {
    id: toOptionalString(idCandidate),
    kind: toOptionalString(kindCandidate),
    name: toOptionalString(nameCandidate),
    label: toOptionalString(labelCandidate),
    turn: toOptionalNumber(turnCandidate),
    total: toOptionalNumber(totalCandidate),
    progress: toOptionalNumber(progressCandidate),
    status: toOptionalString(statusCandidate),
    ordinal: toOptionalNumber(ordinalCandidate),
  };
}

function clampRatio(value) {
  if (typeof value !== "number" || Number.isNaN(value) || !Number.isFinite(value)) {
    return null;
  }
  if (value <= 0) return 0;
  if (value >= 1) return 1;
  return value;
}

/**
 * @typedef {Object} LiveProgressHint
 * @property {number|null} ratio 0-1に正規化された進行率。算出不可なら null。
 * @property {number|null} current 現在のステップ数。
 * @property {number|null} total 全ステップ数。
 */

function deriveProgressHint(phase) {
  if (!phase) return null;

  const ratio = clampRatio(phase.progress ?? null);
  const currentCandidate = phase.turn ?? phase.ordinal ?? null;
  const total = typeof phase.total === "number" && Number.isFinite(phase.total)
    ? phase.total
    : null;

  if (ratio !== null) {
    return {
      ratio,
      current: typeof currentCandidate === "number" && Number.isFinite(currentCandidate)
        ? currentCandidate
        : null,
      total,
    };
  }

  const current = typeof currentCandidate === "number" && Number.isFinite(currentCandidate)
    ? currentCandidate
    : null;

  if (current !== null && total !== null && total > 0) {
    return {
      ratio: clampRatio(current / total),
      current,
      total,
    };
  }

  if (current !== null || total !== null) {
    return {
      ratio: null,
      current,
      total,
    };
  }

  return null;
}

function pickIcon(row, persona) {
  const fromRow = toOptionalString(row.icon);
  if (fromRow) return fromRow;

  if (row.intent && typeof row.intent === "object") {
    const intentIcon = toOptionalString(row.intent.icon ?? row.intent.emoji ?? row.intent.avatar);
    if (intentIcon) return intentIcon;
  }

  if (persona) {
    const personaIcon = toOptionalString(persona.icon);
    if (personaIcon) return personaIcon;
  }

  if (row.phase && typeof row.phase === "object") {
    const phaseIcon = toOptionalString(row.phase.icon ?? row.phase.emoji ?? row.phase.badge);
    if (phaseIcon) return phaseIcon;
  }

  return null;
}

/**
 * @typedef {Object} LiveTimelineEntry
 * @property {string|number} id 一意な識別子。欠損時は行番号を補う。
 * @property {string} speaker 発話者名。
 * @property {string} text 本文テキスト。
 * @property {string|null} ts タイムスタンプ。
 * @property {LivePhaseInfo|null} phase フェーズ情報。欠損時は null。
 * @property {string|null} phaseId フェーズID。フェーズ情報が無ければ null。
 * @property {string|null} phaseKind フェーズ種別。フェーズ情報が無ければ null。
 * @property {LiveProgressHint|null} progressHint 進行度推定用ヒント。
 * @property {LiveLabeledEntity|null} intent 話題意図。欠損時は null。
 * @property {LiveLabeledEntity|null} flow 採用フロー。欠損時は null。
 * @property {LivePersona|null} persona ペルソナ・キャラクタ情報。欠損時は null。
 * @property {string|null} icon 表示用アイコン。欠損時は null。
 */

export function parseLiveRows(rows) {
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

    const phase = normalizePhase(r.phase ?? r.stage ?? null);
    const intent = normalizeLabeledEntity(r.intent ?? r.intent_info ?? r.intentSummary ?? null);
    const flow = normalizeLabeledEntity(r.flow ?? r.flow_info ?? r.playbook ?? null);
    const persona = normalizePersona(r.persona ?? r.profile ?? r.character ?? null);
    const icon = pickIcon(r, persona);
    const progressHint = deriveProgressHint(phase);
    const phaseKind = phase?.kind ?? null;
    const phaseId = phase?.id ?? null;

    timeline.push({
      id: r.id ?? r.index ?? r.turn ?? i + 1,
      speaker: r.speaker ?? r.role ?? r.agent ?? "unknown",
      text: r.text ?? r.message ?? r.content ?? "",
      ts: r.ts ?? r.time ?? r.timestamp ?? null,
      phase,
      phaseId,
      phaseKind,
      progressHint,
      intent,
      flow,
      persona,
      icon,
    });
  });

  return { timeline, latestSummary, latestFinal };
}

// meeting_live.jsonl → タイムライン配列に整形
/**
 * @param {string} meetingId
 * @returns {Promise<LiveTimelineEntry[]>}
 */
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

/**
 * @param {string} meetingId
 * @returns {Promise<{
 *   timeline: LiveTimelineEntry[],
 *   summary: string,
 *   kpi: any,
 *   progress: number|null,
 *   resultReady: boolean,
 *   final: string,
 *   topic: string,
 * }>} ライブビューに必要な情報。
 */
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

// 会議の稼働状況や結果サマリーを手軽に取得するラッパー
export async function getMeetingStatusDetail(meetingId) {
  if (!meetingId) {
    throw new Error("会議IDが指定されていません。");
  }

  const [statusResult, snapshotResult] = await Promise.allSettled([
    getMeetingStatus(meetingId),
    getLiveSnapshot(meetingId),
  ]);

  const status = statusResult.status === "fulfilled" ? statusResult.value : null;
  const snapshot = snapshotResult.status === "fulfilled" ? snapshotResult.value : null;

  const summaryCandidate = [snapshot?.summary, snapshot?.final]
    .map((text) => (typeof text === "string" ? text.trim() : ""))
    .find((text) => text.length > 0) ?? "";

  const isAlive = typeof status?.is_alive === "boolean" ? status.is_alive : false;
  const snapshotHasResult = Boolean(
    snapshot && typeof snapshot.final === "string" && snapshot.final.trim().length > 0,
  );
  const hasResult = typeof status?.has_result === "boolean"
    ? status.has_result
    : snapshotHasResult;

  return {
    is_alive: isAlive,
    has_result: hasResult,
    summary: summaryCandidate,
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

function normalizeResultRecord(source = {}) {
  const idCandidate =
    typeof source.meeting_id === "string" && source.meeting_id.trim()
      ? source.meeting_id.trim()
      : typeof source.id === "string" && source.id.trim()
        ? source.id.trim()
        : String(source.meeting_id ?? source.id ?? "");
  const topic = typeof source.topic === "string" ? source.topic.trim() : "";
  const startedAt = typeof source.started_at === "string" ? source.started_at : "";
  const finalText = typeof source.final === "string" ? source.final : "";

  return {
    id: idCandidate,
    meeting_id: idCandidate,
    topic,
    started_at: startedAt,
    final: finalText,
  };
}

export async function listResults() {
  const res = await fetch(withCacheBuster("/api/results"), { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const message = text.trim() ? `結果一覧の取得に失敗しました: ${text.trim()}` : `結果一覧の取得に失敗しました (HTTP ${res.status}).`;
    throw new Error(message);
  }

  const payload = await res.json().catch(() => ({}));
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    return [];
  }

  return items
    .map((item) => normalizeResultRecord(item))
    .filter((item) => Boolean(item.id))
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
