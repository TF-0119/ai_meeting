import { describe, expect, it } from "vitest";
import { createAgentToken, quoteToken } from "../Home.jsx";

describe("createAgentToken", () => {
  it("シングルクォートを含む名前を引用する", () => {
    const participant = { name: "O'Brien" };
    expect(createAgentToken(participant)).toBe('"O\'Brien"');
  });

  it("シングルクォート入り名前とプロンプトを引用する", () => {
    const participant = {
      name: "O'Brien",
      prompt: "討論を先導する",
    };
    expect(createAgentToken(participant)).toBe('"O\'Brien=討論を先導する"');
  });
});

describe("quoteToken", () => {
  it("バックスラッシュとダブルクォートのみをエスケープする", () => {
    const value = 'path\\to\\"file"';
    expect(quoteToken(value)).toBe('"path\\\\to\\\\\"file\""');
  });
});
