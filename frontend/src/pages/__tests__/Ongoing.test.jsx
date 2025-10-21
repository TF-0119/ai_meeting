import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import Ongoing from "../Ongoing.jsx";
import * as api from "../../services/api";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Ongoing", () => {
  it("会議が取得できた場合は一覧を表示する", async () => {
    const meetings = [
      {
        id: "20240101-000000_12345",
        topic: "テスト会議",
        backend: "ollama",
        started_at: "20240102-030405",
        is_alive: true,
        has_live: true,
        has_result: false,
      },
    ];
    const listMock = vi.spyOn(api, "listMeetings").mockResolvedValue(meetings);

    const { container, unmount } = await renderOngoing();

    expect(container.textContent).toContain("読み込み中です…");

    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("テスト会議");
    expect(container.textContent).toContain("2024-01-02 03:04:05");

    const link = container.querySelector('a[href="/meeting/20240101-000000_12345"]');
    expect(link).not.toBeNull();

    unmount();
  });

  it("会議が存在しない場合は空状態を表示する", async () => {
    const listMock = vi.spyOn(api, "listMeetings").mockResolvedValue([]);

    const { container, unmount } = await renderOngoing();

    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("現在進行中の会議はありません");

    unmount();
  });

  it("取得に失敗した場合はエラーメッセージを表示する", async () => {
    const listMock = vi.spyOn(api, "listMeetings").mockRejectedValue(new Error("通信エラー"));

    const { container, unmount } = await renderOngoing();

    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("通信エラー");
    expect(container.querySelector(".error")).not.toBeNull();

    unmount();
  });
});

async function renderOngoing() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(
      <MemoryRouter>
        <Ongoing />
      </MemoryRouter>,
    );
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
