// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PhotoComparison, clampComparison } from "./PhotoComparison";

let host: HTMLDivElement;
let root: Root;
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(() => root.render(<PhotoComparison photos={[{ id: 1, stem: "left" }, { id: 2, stem: "right" }]} back={vi.fn()} />));
});
afterEach(async () => { await act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); });

it("synchronizes both images through zoom, keyboard pan and reset", async () => {
  await act(() => host.querySelector<HTMLButtonElement>('[aria-label="同步放大"]')!.click());
  const pane = host.querySelector<HTMLElement>(".photo-comparison-image")!;
  await act(() => pane.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })));
  const images = [...host.querySelectorAll("img")];
  expect(images[0].style.transform).toBe("translate(5%, 0%) scale(1.25)");
  expect(images[1].style.transform).toBe(images[0].style.transform);
  await act(() => [...host.querySelectorAll("button")].find((button) => button.textContent === "适应窗口")!.click());
  expect(images.every((image) => image.style.transform === "translate(0%, 0%) scale(1)")).toBe(true);
  expect(host.querySelector<HTMLButtonElement>('[aria-label="同步缩小"]')!.disabled).toBe(true);
});

it("normalizes dragging and releases capture before resetting", async () => {
  await act(() => host.querySelector<HTMLButtonElement>('[aria-label="同步放大"]')!.click());
  const pane = host.querySelector<HTMLDivElement>(".photo-comparison-image")!;
  pane.setPointerCapture = vi.fn(); pane.hasPointerCapture = vi.fn(() => true); pane.releasePointerCapture = vi.fn();
  vi.spyOn(pane, "getBoundingClientRect").mockReturnValue({ width: 400, height: 200 } as DOMRect);
  const pointer = async (type: string, x: number) => {
    const event = new Event(type, { bubbles: true });
    Object.assign(event, { pointerId: 1, button: 0, clientX: x, clientY: 0 });
    await act(() => pane.dispatchEvent(event));
  };
  await pointer("pointerdown", 0); await pointer("pointermove", 20);
  expect([...host.querySelectorAll("img")].every((image) => image.style.transform === "translate(5%, 0%) scale(1.25)")).toBe(true);
  await pointer("pointerup", 20);
  expect(pane.releasePointerCapture).toHaveBeenCalledWith(1);
});

it("retries only the failed side and leaves the other source unchanged", async () => {
  const images = host.querySelectorAll("img"); const right = images[1].src;
  await act(() => images[0].dispatchEvent(new Event("error")));
  await act(() => [...host.querySelectorAll("button")].find((button) => button.textContent === "重试这张")!.click());
  expect(host.querySelectorAll("img")[0].src).toContain("retry=1");
  expect(host.querySelectorAll("img")[1].src).toBe(right);
});

it("bounds zoom and pan and restores center at fit size", () => {
  expect(clampComparison({ zoom: 10, x: 100, y: -100 })).toEqual({ zoom: 6, x: 2.5, y: -2.5 });
  expect(clampComparison({ zoom: .5, x: 3, y: -2 })).toEqual({ zoom: 1, x: 0, y: -0 });
});
