// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { GroupComparison } from "./GroupComparison";
import type { SimilarityGroupDetail } from "./types";

let root: Root;
let host: HTMLDivElement;
const group = (ids: number[]) => ({ id: 1, event_name: "相册", items: ids.map((capture_id) => ({ capture_id, stem: `photo-${capture_id}` })) }) as SimilarityGroupDetail;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(() => root.unmount()); host.remove(); });

it("compares group members, prevents duplicate sides and restores the group entry on exit", async () => {
  await act(() => root.render(<GroupComparison group={group([1, 2, 3])} />));
  await act(() => host.querySelector("button")!.click());
  const right = host.querySelector<HTMLSelectElement>('[aria-label="B 对比照片"]')!;
  expect(right.querySelector<HTMLOptionElement>('option[value="1"]')!.disabled).toBe(true);
  await act(() => { right.value = "3"; right.dispatchEvent(new Event("change", { bubbles: true })); });
  expect([...host.querySelectorAll("img")].map((image) => image.getAttribute("src"))).toEqual(["/api/thumbnails/1?size=1280", "/api/thumbnails/3?size=1280"]);
  await act(() => [...host.querySelectorAll("button")].find((button) => button.textContent === "返回相似组")!.click());
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(host.textContent).toBe("双图对比");
});

it("disables comparison when fewer than two group members remain", async () => {
  await act(() => root.render(<GroupComparison group={group([1])} />));
  expect(host.querySelector("button")!.disabled).toBe(true);
});
