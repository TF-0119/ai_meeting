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
    const statusMock = vi.spyOn(api, "getMeetingStatusDetail").mockResolvedValue({
      is_alive: true,
      has_result: true,
      summary: "これは最新サマリーです。",
    });

    const { container, unmount } = await renderOngoing();

    expect(container.textContent).toContain("読み込み中です…");

    await flushEffects();
    await flushEffects();

    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(statusMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("テスト会議");
    expect(container.textContent).toContain("2024-01-02 03:04:05");
    expect(container.textContent).toContain("これは最新サマリーです。");

    const aliveBadge = container.querySelector(".meeting-status-badge--alive");
    expect(aliveBadge).not.toBeNull();
    expect(aliveBadge?.textContent).toContain("稼働中");

    const resultBadge = container.querySelector(".meeting-status-badge--result");
    expect(resultBadge).not.toBeNull();
    expect(resultBadge?.textContent).toContain("結果あり");

    const link = container.querySelector('a[href="/meeting/20240101-000000_12345"]');
    expect(link).not.toBeNull();

    const resultLink = container.querySelector('a[href="/result/20240101-000000_12345"]');
    expect(resultLink).not.toBeNull();
    expect(resultLink?.textContent).toContain("結果を見る");

    unmount();
  });

  it("結果ファイルが未完成でも結果待ち状態を維持する", async () => {
    const meetings = [
      {
        id: "20240101-000000_67890",
        topic: "部分的な結果",
        backend: "ollama",
        started_at: "20240103-040506",
        is_alive: false,
        has_live: true,
        has_result: false,
      },
    ];
    const listMock = vi.spyOn(api, "listMeetings").mockResolvedValue(meetings);
    const statusMock = vi.spyOn(api, "getMeetingStatusDetail").mockResolvedValue({
      is_alive: false,
      has_result: false,
      summary: "最終出力を生成中です。",
    });

    const { container, unmount } = await renderOngoing();

    await flushEffects();
    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(statusMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("部分的な結果");
    expect(container.textContent).toContain("最終出力を生成中です。");

    const resultBadge = container.querySelector(".meeting-status-badge--pending");
    expect(resultBadge).not.toBeNull();
    expect(resultBadge?.textContent).toContain("結果待ち");

    const resultLink = container.querySelector('a[href="/result/20240101-000000_67890"]');
    expect(resultLink).toBeNull();

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

  it("停止操作が成功すると一覧を再取得しボタン状態が戻る", async () => {
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
    const updatedMeetings = [
      {
        ...meetings[0],
        is_alive: false,
        has_result: true,
      },
    ];
    const listMock = vi.spyOn(api, "listMeetings")
      .mockResolvedValueOnce(meetings)
      .mockResolvedValueOnce(updatedMeetings);
    const statusMock = vi.spyOn(api, "getMeetingStatusDetail")
      .mockResolvedValueOnce({
        is_alive: true,
        has_result: false,
        summary: "停止前",
      })
      .mockResolvedValueOnce({
        is_alive: false,
        has_result: true,
        summary: "停止後",
      });

    let resolveStop;
    const stopPromise = new Promise((resolve) => {
      resolveStop = resolve;
    });
    const stopMock = vi.spyOn(api, "stopMeeting").mockImplementation(() => stopPromise);

    const { container, unmount } = await renderOngoing();

    await flushEffects();
    await flushEffects();
    await flushEffects();

    let button = container.querySelector("button");
    expect(button).not.toBeNull();
    expect(button?.textContent).toContain("停止");
    expect(button?.disabled).toBe(false);

    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await flushEffects();

    expect(stopMock).toHaveBeenCalledTimes(1);
    button = container.querySelector("button");
    expect(button?.disabled).toBe(true);
    expect(button?.textContent).toContain("停止中");

    await act(async () => {
      resolveStop();
      await Promise.resolve();
    });

    await flushEffects();
    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(2);
    expect(statusMock).toHaveBeenCalledTimes(2);
    button = container.querySelector("button");
    expect(button?.disabled).toBe(false);
    expect(button?.textContent).toContain("停止");

    unmount();
  });

  it("停止操作が失敗するとエラーを通知してボタン状態を戻す", async () => {
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
    const statusMock = vi.spyOn(api, "getMeetingStatusDetail").mockResolvedValue({
      is_alive: true,
      has_result: false,
      summary: "",
    });

    let rejectStop;
    const stopPromise = new Promise((_, reject) => {
      rejectStop = reject;
    });
    const stopMock = vi.spyOn(api, "stopMeeting").mockImplementation(() => stopPromise);
    const alertMock = vi.spyOn(window, "alert").mockImplementation(() => {});

    const { container, unmount } = await renderOngoing();

    await flushEffects();
    await flushEffects();
    await flushEffects();

    let button = container.querySelector("button");
    expect(button).not.toBeNull();
    expect(button?.disabled).toBe(false);

    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await flushEffects();

    expect(stopMock).toHaveBeenCalledTimes(1);
    button = container.querySelector("button");
    expect(button?.disabled).toBe(true);
    expect(button?.textContent).toContain("停止中");

    await act(async () => {
      rejectStop(new Error("停止に失敗しました"));
      await Promise.resolve();
    });

    await flushEffects();
    await flushEffects();

    expect(alertMock).toHaveBeenCalledTimes(1);
    expect(alertMock).toHaveBeenCalledWith("停止に失敗しました");
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(statusMock).toHaveBeenCalledTimes(1);
    button = container.querySelector("button");
    expect(button?.disabled).toBe(false);
    expect(button?.textContent).toContain("停止");

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
