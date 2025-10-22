// frontend/src/utils/flow.js

export const FLOW_TREND_SYMBOLS = {
  forward: "↗",
  steady: "→",
  reflect: "↘",
};

/**
 * フロー指標から進行方向の種別を推定する。
 * @param {any} flow ログ上の flow 情報。
 * @returns {"forward"|"steady"|"reflect"|null} 種別。判定不可なら null。
 */
export function resolveFlowTrend(flow) {
  if (flow == null) return null;

  if (typeof flow === "string") {
    const trimmed = flow.trim();
    if (!trimmed) return null;
    if (/^[↗↖↑⤴]/u.test(trimmed)) return "forward";
    if (/^[↘↙↓⤵]/u.test(trimmed)) return "reflect";
    if (/^[→⟷⟺⇔]/u.test(trimmed)) return "steady";
    const normalized = trimmed.toLowerCase();
    if (/(up|forward|rise|fast|positive|accelerat)/u.test(normalized)) return "forward";
    if (/(down|back|slow|negative|regress|declin|reflect)/u.test(normalized)) return "reflect";
    if (/(steady|flat|hold|neutral|calm|stable)/u.test(normalized)) return "steady";
    return null;
  }

  if (typeof flow === "number" && Number.isFinite(flow)) {
    if (flow >= 0.66) return "forward";
    if (flow <= 0.33) return "reflect";
    return "steady";
  }

  if (typeof flow === "object") {
    if (typeof flow.trend === "string") return resolveFlowTrend(flow.trend);
    if (typeof flow.direction === "string") return resolveFlowTrend(flow.direction);
    if (typeof flow.delta === "number") return resolveFlowTrend(flow.delta);
    if (typeof flow.score === "number") return resolveFlowTrend(flow.score);
  }

  return null;
}

/**
 * フェーズ種別も考慮した進行方向を算出する。
 * @param {string|null|undefined} phaseKind フェーズ種別。
 * @param {any} flow ログ上の flow 情報。
 * @returns {"forward"|"steady"|"reflect"|null} 種別。判定不可なら null。
 */
export function deriveFlowTrendKind(phaseKind, flow) {
  const flowKind = resolveFlowTrend(flow);
  if (flowKind) return flowKind;
  const kind = typeof phaseKind === "string" ? phaseKind.toLowerCase() : "";
  switch (kind) {
    case "resolution":
    case "decision":
    case "action":
    case "synthesis":
      return "forward";
    case "wrapup":
    case "review":
    case "retrospective":
    case "reflection":
      return "reflect";
    case "":
      return null;
    default:
      return "steady";
  }
}

/**
 * 進行方向の種別から矢印を返す。
 * @param {"forward"|"steady"|"reflect"|null} kind 進行方向種別。
 * @returns {string|null} 対応する矢印。判定不可なら null。
 */
export function flowTrendToSymbol(kind) {
  if (!kind) return null;
  return FLOW_TREND_SYMBOLS[kind] ?? null;
}

export default {
  FLOW_TREND_SYMBOLS,
  resolveFlowTrend,
  deriveFlowTrendKind,
  flowTrendToSymbol,
};
