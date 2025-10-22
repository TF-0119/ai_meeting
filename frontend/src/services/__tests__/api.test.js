import { describe, expect, it } from "vitest";
import { parseLiveRows } from "../api.js";

describe("parseLiveRows", () => {
  it("新しいフィールドを抽出して派生情報を付加する", () => {
    const rows = [
      {
        type: "turn",
        id: "row-1",
        speaker: "Planner",
        text: "次の工程へ進めましょう",
        ts: "2025-01-01T00:00:00Z",
        phase: {
          id: "phase-1",
          kind: "analysis",
          name: "分析フェーズ",
          turn: 3,
          total: 5,
          progress: 0.6,
        },
        intent: {
          id: "intent-1",
          name: "Collect feedback",
          kind: "goal",
          description: "顧客からのフィードバック収集",
          icon: "🎯",
        },
        flow: {
          id: "flow-1",
          name: "Default Flow",
          kind: "standard",
        },
        persona: {
          id: "persona-1",
          name: "Strategist",
          role: "leader",
          icon: "🧠",
        },
        icon: "💡",
      },
    ];

    const { timeline } = parseLiveRows(rows);
    expect(timeline).toHaveLength(1);
    const entry = timeline[0];

    expect(entry.phase).toMatchObject({
      id: "phase-1",
      kind: "analysis",
      name: "分析フェーズ",
      turn: 3,
      total: 5,
      progress: 0.6,
    });
    expect(entry.phaseId).toBe("phase-1");
    expect(entry.phaseKind).toBe("analysis");
    expect(entry.progressHint).toMatchObject({ ratio: 0.6, current: 3, total: 5 });
    expect(entry.intent).toMatchObject({ id: "intent-1", name: "Collect feedback", kind: "goal", icon: "🎯" });
    expect(entry.flow).toMatchObject({ id: "flow-1", name: "Default Flow" });
    expect(entry.persona).toMatchObject({ id: "persona-1", role: "leader" });
    expect(entry.icon).toBe("💡");
  });

  it("旧形式のログでも欠損フィールドを null で補完する", () => {
    const rows = [
      { type: "summary", summary: "暫定要約" },
      {
        type: "turn",
        speaker: "Alice",
        content: "議題に入ります",
      },
      { type: "final", final: "最終結論" },
    ];

    const { timeline, latestSummary, latestFinal } = parseLiveRows(rows);
    expect(timeline).toHaveLength(1);
    const entry = timeline[0];

    expect(entry.phase).toBeNull();
    expect(entry.phaseId).toBeNull();
    expect(entry.phaseKind).toBeNull();
    expect(entry.progressHint).toBeNull();
    expect(entry.intent).toBeNull();
    expect(entry.flow).toBeNull();
    expect(entry.persona).toBeNull();
    expect(entry.icon).toBeNull();

    expect(latestSummary).toBe("暫定要約");
    expect(latestFinal).toBe("最終結論");
  });
});
