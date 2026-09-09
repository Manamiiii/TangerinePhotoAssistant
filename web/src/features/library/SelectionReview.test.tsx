// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import { SelectionReview } from "./SelectionReview";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
vi.mock("./LibraryThumbnail", () => ({ LibraryThumbnail: () => <span>thumbnail</span> }));
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getJson).mockReset().mockImplementation(async (url) => ({ items: new URL(String(url), "http://localhost").searchParams.getAll("ids").map((id) => ({ id: Number(id), stem: `photo-${id}`, jpeg_present: 0 })) }));
});
afterEach(async () => { await act(() => root.unmount()); host.remove(); });
const click = async (label: string) => {
  await act(() => [...host.querySelectorAll("button")].find((button) => button.textContent === label)!.click());
};

it("queries only a page of explicit IDs and moves back after removing the final page's last item", async () => {
  function Wrapper() {
    const [selected, setSelected] = useState(new Set(Array.from({ length: 41 }, (_, index) => index + 1)));
    return <SelectionReview selected={selected} close={vi.fn()} remove={(id) => setSelected((current) => new Set([...current].filter((value) => value !== id)))} />;
  }
  await act(() => root.render(<Wrapper />));
  expect(host.querySelectorAll("article")).toHaveLength(40);
  expect(String(vi.mocked(getJson).mock.calls[0][0])).not.toContain("ids=41");
  await click("下一页");
  expect(host.querySelectorAll("article")).toHaveLength(1);
  expect(host.textContent).toContain("photo-41");
  await click("移除");
  expect(host.textContent).toContain("共 40 张");
  expect(host.querySelector('[aria-label="简化分页"]')).toBeNull();
  expect(host.textContent).not.toContain("photo-41");
});

it("keeps the selection on failure and allows an explicit retry", async () => {
  vi.mocked(getJson).mockRejectedValueOnce(new Error("offline"));
  const remove = vi.fn();
  await act(() => root.render(<SelectionReview selected={new Set([9])} remove={remove} close={vi.fn()} />));
  expect(host.textContent).toContain("清单读取失败");
  expect(remove).not.toHaveBeenCalled();
  await click("重试清单");
  expect(host.textContent).toContain("photo-9");
  await click("移除");
  expect(remove).toHaveBeenCalledWith(9);
});

it("aborts superseded reads and does not resurrect an old selection after it is cleared", async () => {
  let resolve!: (result: unknown) => void;
  vi.mocked(getJson).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  await act(() => root.render(<SelectionReview selected={new Set([8])} remove={vi.fn()} close={vi.fn()} />));
  const signal = vi.mocked(getJson).mock.calls[0][1]?.signal;
  await act(() => root.render(<SelectionReview selected={new Set()} remove={vi.fn()} close={vi.fn()} />));
  expect(signal?.aborted).toBe(true);
  await act(() => resolve({ items: [{ id: 8, stem: "old" }] }));
  expect(host.textContent).toContain("已清空选择");
  expect(host.textContent).not.toContain("old");
});

it("compares candidates from different pages and returns without changing the library selection", async () => {
  vi.mocked(getJson).mockImplementation(async (url) => ({ items: new URL(String(url), "http://localhost").searchParams.getAll("ids").map((id) => ({ id: Number(id), stem: `photo-${id}`, jpeg_present: 1 })) }));
  const remove = vi.fn();
  await act(() => root.render(<SelectionReview selected={new Set(Array.from({ length: 41 }, (_, index) => index + 1))} remove={remove} close={vi.fn()} />));
  await click("加入对比");
  await click("下一页");
  await click("加入对比");
  await click("对比两张");
  expect([...host.querySelectorAll(".photo-comparison img")].map((image) => image.getAttribute("src"))).toEqual(["/api/thumbnails/1?size=1280", "/api/thumbnails/41?size=1280"]);
  await click("返回已选清单");
  expect(host.textContent).toContain("共 41 张");
  expect(host.textContent).toContain("对比候选 2 / 2");
  expect(remove).not.toHaveBeenCalled();
  expect(document.activeElement?.textContent).toBe("对比两张");
});
