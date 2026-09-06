// @vitest-environment jsdom
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EditPreviewImage } from "./features/details/EditPreviewImage";
import { StatisticsView } from "./features/statistics/StatisticsView";
import { HomeView } from "./features/home/HomeView";
import { BurstsView } from "./features/similarity/BurstsView";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(() => root.unmount()); host.remove(); vi.useRealTimers(); });

it("retries a failed preview without changing its adjustment parameters", async () => {
  await act(() => root.render(<EditPreviewImage url="/edit-preview?exposure_ev=1" name="test" pending={false} />));
  await act(() => host.querySelector("img")!.dispatchEvent(new Event("error")));
  expect(host.textContent).toContain("参数已保留");
  await act(() => host.querySelector("button")!.click());
  expect(host.querySelector("img")!.getAttribute("src")).toBe("/edit-preview?exposure_ev=1&retry=1");
  expect(host.querySelector('[role="alert"]')).toBeNull();
  await act(() => host.querySelector("img")!.dispatchEvent(new Event("load")));
  expect(host.querySelector('[role="status"]')).toBeNull();
});

it("does not let the previous preview's completion clear a new preview's loading state", async () => {
  await act(() => root.render(<EditPreviewImage key="a" url="/a" name="test" pending={false} />));
  const old = host.querySelector("img")!;
  await act(() => root.render(<EditPreviewImage key="b" url="/b" name="test" pending={false} />));
  await act(() => old.dispatchEvent(new Event("load")));
  expect(host.querySelector('[role="status"]')).not.toBeNull();
  await act(() => host.querySelector("img")!.dispatchEvent(new Event("load")));
  expect(host.querySelector('[role="status"]')).toBeNull();
});

it("offers retry after a stalled preview and clears its timeout on unmount", async () => {
  vi.useFakeTimers();
  await act(() => root.render(<EditPreviewImage url="/stalled" name="test" pending={false} />));
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  await act(() => host.querySelector("button")!.click());
  await act(() => root.render(null));
  expect(vi.getTimerCount()).toBe(0);
});

it("distinguishes unavailable statistics from an empty result", () => {
  const loading = renderToStaticMarkup(<StatisticsView statistics={null} openLibraryWith={vi.fn()} />);
  expect(loading).toContain("正在读取摄影统计");
  expect(loading).not.toContain("暂无");
  const failed = renderToStaticMarkup(<StatisticsView statistics={null} loadError="offline" openLibraryWith={vi.fn()} />);
  expect(failed).toContain("统计读取失败");
  expect(failed).not.toContain("正在读取");
});

it("distinguishes recent-photo loading, failure and an empty library", () => {
  const props = { overview: null, statistics: null, archive: null, activeBaseline: null, library: null, filters: null, similarity: null, task: null, capabilities: null } as unknown as ComponentProps<typeof HomeView>;
  const render = (changes: Partial<typeof props>) => renderToStaticMarkup(<HomeView {...props} {...changes} />);
  expect(render({})).not.toContain("还没有可显示");
  expect(render({ readErrors: { "/api/library/captures?limit=8&offset=0&sort=newest": "offline" } })).toContain("读取失败");
  expect(render({ library: { items: [] } as unknown as NonNullable<typeof props.library> })).toContain("还没有可显示的最近照片");
});

it("blocks starting similarity analysis while paused or while task status is unknown", () => {
  const props = { groups: null, selectedGroup: null, albumId: "", task: null } as unknown as ComponentProps<typeof BurstsView>;
  for (const task of [null, { status: "paused", stage: "ai-paused", message: "paused" }]) {
    host.innerHTML = renderToStaticMarkup(<BurstsView {...props} task={task as typeof props.task} />);
    expect(host.querySelector<HTMLButtonElement>(".primary-action")!.disabled).toBe(true);
  }
  host.innerHTML = renderToStaticMarkup(<BurstsView {...props} task={{ status: "idle" } as NonNullable<typeof props.task>} />);
  expect(host.querySelector<HTMLButtonElement>(".primary-action")!.disabled).toBe(false);
});
