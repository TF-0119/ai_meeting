import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Meeting from "../Meeting.jsx";
import * as api from "../../services/api";

const baseSnapshot = {
  timeline: [],
  summary: "",
  kpi: null,
  progress: null,
  resultReady: false,
  final: "",
  topic: "",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Meeting", () => {
  it("中止操作が成功すると stopMeeting を呼んでトップページへ遷移する", async () => {
    vi.spyOn(api, "getLiveSnapshot").mockResolvedValue(baseSnapshot);
    const stopMock = vi.spyOn(api, "stopMeeting").mockResolvedValue();

    const { container, unmount } = await renderMeeting();

    const cancelButton = getButtonByText(container, "中止して戻る");
    expect(cancelButton).not.toBeNull();

    await clickButton(cancelButton);

    expect(stopMock).toHaveBeenCalledTimes(1);
    expect(stopMock).toHaveBeenCalledWith("sample-meeting");
    expect(container.querySelector('[data-testid="home"]')).not.toBeNull();

    unmount();
  });

  it("中止操作が失敗するとエラーメッセージを通知しページに留まる", async () => {
    vi.spyOn(api, "getLiveSnapshot").mockResolvedValue(baseSnapshot);
    const stopMock = vi.spyOn(api, "stopMeeting").mockRejectedValue(new Error("停止に失敗しました"));
    const alertMock = vi.spyOn(window, "alert").mockImplementation(() => {});

    const { container, unmount } = await renderMeeting();

    const cancelButton = getButtonByText(container, "中止して戻る");
    expect(cancelButton).not.toBeNull();

    await clickButton(cancelButton);

    expect(stopMock).toHaveBeenCalledTimes(1);
    expect(stopMock).toHaveBeenCalledWith("sample-meeting");
    expect(alertMock).toHaveBeenCalledWith("停止に失敗しました");
    expect(container.querySelector('[data-testid="home"]')).toBeNull();
    expect(cancelButton?.disabled).toBe(false);

    unmount();
  });
});

async function renderMeeting() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/meeting/sample-meeting"]}>
        <Routes>
          <Route path="/" element={<div data-testid="home">ホーム</div>} />
          <Route path="/meeting/:id" element={<Meeting />} />
        </Routes>
      </MemoryRouter>,
    );
  });

  await flushEffects();

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

async function clickButton(button) {
  if (!button) return;
  await act(async () => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await flushEffects();
}

function getButtonByText(container, text) {
  return Array.from(container.querySelectorAll("button")).find(
    (btn) => btn.textContent && btn.textContent.trim() === text,
  );
}
