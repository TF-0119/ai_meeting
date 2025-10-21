import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import ResultsList from "../ResultsList.jsx";
import * as api from "../../services/api";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ResultsList", () => {
  it("結果が取得できた場合は一覧を表示する", async () => {
    const results = [
      {
        id: "20240105-120000_product_launch",
        topic: "新製品発表の準備",
        started_at: "20240105-120000",
        final: "合意事項: 発表会の進行表を確定する",
      },
      {
        id: "20231224-090000_winter",
        topic: "冬季キャンペーン",
        started_at: "20231224-090000",
        final: "",
      },
    ];

    const listMock = vi.spyOn(api, "listResults").mockResolvedValue(results);

    const { container, unmount } = await renderResultsList();

    expect(container.textContent).toContain("読み込み中です…");

    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("新製品発表の準備");
    expect(container.textContent).toContain("冬季キャンペーン");
    expect(container.textContent).toContain("2024-01-05 12:00:00");
    expect(container.textContent).toContain("合意事項: 発表会の進行表を確定する");
    expect(container.textContent).toContain("Finalはまだありません。");

    const detailLink = container.querySelector('a[href="/result/20240105-120000_product_launch"]');
    expect(detailLink).not.toBeNull();
    expect(detailLink?.textContent).toContain("詳細を見る");

    unmount();
  });

  it("結果が存在しない場合は空状態を表示する", async () => {
    const listMock = vi.spyOn(api, "listResults").mockResolvedValue([]);

    const { container, unmount } = await renderResultsList();

    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("会議結果が見つかりませんでした。");

    unmount();
  });

  it("取得に失敗した場合はエラーメッセージを表示する", async () => {
    const listMock = vi.spyOn(api, "listResults").mockRejectedValue(new Error("通信エラー"));

    const { container, unmount } = await renderResultsList();

    await flushEffects();
    await flushEffects();

    expect(listMock).toHaveBeenCalledTimes(1);
    const errorNode = container.querySelector(".error");
    expect(errorNode).not.toBeNull();
    expect(errorNode?.textContent).toContain("通信エラー");

    unmount();
  });
});

async function renderResultsList() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(
      <MemoryRouter>
        <ResultsList />
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
