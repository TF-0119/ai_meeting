import { describe, expect, it, afterEach, vi } from "vitest";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import Home, { createAgentToken, quoteToken } from "../Home.jsx";
import * as api from "../../services/api";
import * as presets from "../../services/presets";

afterEach(() => {
  vi.restoreAllMocks();
});

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

describe("Home", () => {
  it("プリセットから参加者が復元され、エージェント文字列が専用フォームの値のみで構築される", async () => {
    const presetParticipants = [
      { name: "Leader", prompt: "Lead discussion" },
      { name: "Recorder", prompt: "Take notes" },
    ];

    vi.spyOn(api, "getModels").mockResolvedValue([]);
    const startMeetingMock = vi.spyOn(api, "startMeeting").mockResolvedValue({ id: "meeting-123" });
    vi.spyOn(presets, "loadHomePreset").mockReturnValue({
      form: {
        topic: "Preset Topic",
        precision: "6",
      },
      participants: presetParticipants,
    });
    vi.spyOn(presets, "saveHomePreset").mockImplementation(() => {});

    const { container, unmount } = await renderWithRouter(<Home />);

    await flushEffects();

    const topicInput = container.querySelector('input[value="Preset Topic"]');
    expect(topicInput).not.toBeNull();
    const leaderInput = container.querySelector('input[value="Leader"]');
    expect(leaderInput).not.toBeNull();
    const promptFields = Array.from(container.querySelectorAll('textarea[class~="participant-prompt"]'));
    expect(promptFields.length).toBe(2);
    expect(promptFields[0]?.value).toBe("Lead discussion");
    expect(promptFields[1]?.value).toBe("Take notes");
    expect(container.textContent).not.toContain("追加の参加者指定（文字列入力）");

    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    await submitReactForm(form);

    expect(startMeetingMock).toHaveBeenCalledTimes(1);

    const payload = startMeetingMock.mock.calls[0][0];
    expect(payload.agents).toBe('"Leader=Lead discussion" "Recorder=Take notes"');
    expect(payload.rounds).toBeUndefined();

    unmount();
  });
});

async function renderWithRouter(ui) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(<MemoryRouter>{ui}</MemoryRouter>);
  });

  return {
    container,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function submitReactForm(form) {
  await act(async () => {
    const event = new Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(event);
  });
  await flushEffects();
}
