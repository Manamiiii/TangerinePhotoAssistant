import { describe, expect, it, vi } from "vitest";
import { changeZoom, fittedTransform, imageIsReady, previewUrl, toggleFullscreen } from "./viewerState";

describe("photo viewer state", () => {
  it("clears panning when wheel or minus returns to fitted size", () => {
    expect(changeZoom({ zoom: 1.25, x: 200, y: 70 }, -.25)).toEqual(fittedTransform);
    expect(changeZoom({ zoom: 1, x: 200, y: 70 }, -.25)).toEqual(fittedTransform);
  });

  it("bounds zoom and preserves panning above fitted size", () => {
    expect(changeZoom({ zoom: 5.75, x: 20, y: 10 }, 1)).toEqual({ zoom: 6, x: 20, y: 10 });
  });

  it("shares the first-load URL with prefetch and changes only retries", () => {
    const url = "/api/thumbnails/2?size=1280";
    expect(previewUrl(url, 0)).toBe(url);
    expect(previewUrl(url, 1)).toBe(`${url}&retry=1`);
    expect(previewUrl("/photo.jpg", 2)).toBe("/photo.jpg?retry=2");
  });

  it("recognizes cached images without waiting for another load event", () => {
    expect(imageIsReady({ complete: true, naturalWidth: 1280 })).toBe(true);
    expect(imageIsReady({ complete: false, naturalWidth: 0 })).toBe(false);
    expect(imageIsReady({ complete: true, naturalWidth: 0 })).toBe(false);
  });

  it("toggles fullscreen for the actual owner element", async () => {
    const element = { requestFullscreen: vi.fn(async () => {}) } as unknown as HTMLElement;
    const doc = { fullscreenElement: null as Element | null, fullscreenEnabled: true, exitFullscreen: vi.fn(async () => {}) };
    await toggleFullscreen(element, doc);
    expect(element.requestFullscreen).toHaveBeenCalledOnce();
    doc.fullscreenElement = element;
    await toggleFullscreen(element, doc);
    expect(doc.exitFullscreen).toHaveBeenCalledOnce();
  });

  it("reports unavailable or rejected fullscreen requests to the caller", async () => {
    const doc = { fullscreenElement: null, fullscreenEnabled: false, exitFullscreen: vi.fn(async () => {}) };
    await expect(toggleFullscreen(null, doc)).rejects.toThrow("不支持");
    const element = { requestFullscreen: vi.fn(async () => { throw new Error("Permission denied"); }) } as unknown as HTMLElement;
    await expect(toggleFullscreen(element, { ...doc, fullscreenEnabled: true })).rejects.toThrow("Permission denied");
  });
});
