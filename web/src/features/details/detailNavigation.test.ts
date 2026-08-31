import { describe, expect, it, vi } from "vitest";
import { adjacentLibraryOffset, captureContext, adjacentCaptureIds, canNavigateDetail, prefetchAdjacentImages, resolveDetailNavigation } from "./detailNavigation";
import type { LibraryCapture, LibraryCapturesResponse } from "../library/types";

const page = (ids: number[], offset = 0): LibraryCapturesResponse => ({
  count: 6, limit: 2, offset, items: ids.map((id) => ({ id } as LibraryCapture)),
} as LibraryCapturesResponse);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function navigationOptions() {
  return { id: 2, context: [1, 2], scope: "library" as const, page: page([1, 2]), direction: 1 as const,
    isCurrent: () => true, loadPage: vi.fn(async () => page([3, 4], 2)),
    loadCapture: vi.fn(async (id: number) => ({ id, rating: 3 })),
  };
}

describe("detail navigation", () => {
  it("keeps collapsed similarity groups as one visible representative", () => {
    const items = [
      { id: 10, selection_capture_ids: [10] },
      { id: 20, selection_capture_ids: [20, 21, 22] },
      { id: 30, selection_capture_ids: [30] },
    ] as LibraryCapture[];

    expect(captureContext(items)).toEqual([10, 20, 30]);
  });

  it("moves across page boundaries without exceeding the result set", () => {
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 0 }, -1)).toBeNull();
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 0 }, 1)).toBe(40);
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 40 }, -1)).toBe(0);
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 80 }, 1)).toBeNull();
  });

  it("stops fixed group navigation at both ends even when library pages remain", async () => {
    const options = { ...navigationOptions(), scope: "fixed" as const };
    expect(await resolveDetailNavigation(options)).toBeNull();
    expect(canNavigateDetail(2, [1, 2], "fixed", options.page, 1)).toBe(false);
    expect(canNavigateDetail(1, [1, 2], "fixed", page([1, 2], 2), -1)).toBe(false);
    expect(options.loadPage).not.toHaveBeenCalled();
    expect(options.loadCapture).not.toHaveBeenCalled();
  });

  it("does not expose navigation for a photo outside the current context", async () => {
    const options = { ...navigationOptions(), id: 99 };
    expect(canNavigateDetail(99, options.context, "library", options.page, 1)).toBe(false);
    expect(await resolveDetailNavigation(options)).toBeNull();
  });

  it("returns page and photo together only after both reads complete", async () => {
    const options = navigationOptions();
    const result = await resolveDetailNavigation(options);
    expect(result).toEqual({ id: 3, detail: { id: 3, rating: 3 }, context: [3, 4], page: page([3, 4], 2) });
    expect(options.loadCapture).toHaveBeenCalledExactlyOnceWith(3);
  });

  it("selects the last photo on the previous page", async () => {
    const options = { ...navigationOptions(), id: 3, context: [3, 4], page: page([3, 4], 2), direction: -1 as const,
      loadPage: vi.fn(async () => page([1, 2])),
    };
    expect((await resolveDetailNavigation(options))?.id).toBe(2);
    expect(options.loadPage).toHaveBeenCalledExactlyOnceWith(0);
  });

  it("ignores a page response after closing or replacing the browsing context", async () => {
    const pendingPage = deferred<LibraryCapturesResponse>();
    let current = true;
    const options = { ...navigationOptions(), isCurrent: () => current, loadPage: () => pendingPage.promise };
    const request = resolveDetailNavigation(options);
    current = false;
    pendingPage.resolve(page([3, 4], 2));
    expect(await request).toBeNull();
    expect(options.loadCapture).not.toHaveBeenCalled();
  });

  it("ignores a late detail response too", async () => {
    const pendingDetail = deferred<{ id: number }>();
    let current = true;
    const options = { ...navigationOptions(), id: 1, isCurrent: () => current, loadCapture: () => pendingDetail.promise };
    const request = resolveDetailNavigation(options);
    current = false;
    pendingDetail.resolve({ id: 2 });
    expect(await request).toBeNull();
  });

  it("does not load detail for an empty next page", async () => {
    const options = { ...navigationOptions(), loadPage: async () => page([], 2) };
    expect(await resolveDetailNavigation(options)).toBeNull();
    expect(options.loadCapture).not.toHaveBeenCalled();
  });

  it("propagates a failed detail read without returning a page-only update", async () => {
    const options = { ...navigationOptions(), loadCapture: async () => { throw new Error("read failed"); } };
    await expect(resolveDetailNavigation(options)).rejects.toThrow("read failed");
  });

  it("reads fresh mutable detail on every navigation", async () => {
    let rating = 1;
    const options = { ...navigationOptions(), id: 1, loadCapture: vi.fn(async (id: number) => ({ id, rating })) };
    expect((await resolveDetailNavigation(options))?.detail.rating).toBe(1);
    rating = 5;
    expect((await resolveDetailNavigation(options))?.detail.rating).toBe(5);
    expect(options.loadCapture).toHaveBeenCalledTimes(2);
  });

  it("prefetches at most two distinct images and releases them on cleanup", () => {
    const images: Array<{ src: string; removeAttribute: ReturnType<typeof vi.fn> }> = [];
    const cleanup = prefetchAdjacentImages([2, 2, 3, 4], () => {
      const image = { src: "", removeAttribute: vi.fn() };
      images.push(image);
      return image;
    });
    expect(images.map((image) => image.src)).toEqual(["/api/thumbnails/2?size=1280", "/api/thumbnails/3?size=1280"]);
    cleanup();
    images.forEach((image) => expect(image.removeAttribute).toHaveBeenCalledExactlyOnceWith("src"));
  });

  it("keeps prefetch within the actual context", () => {
    expect(adjacentCaptureIds(2, [1, 2, 3])).toEqual([1, 3]);
    expect(adjacentCaptureIds(1, [1, 2, 3])).toEqual([2]);
    expect(adjacentCaptureIds(99, [1, 2, 3])).toEqual([]);
  });
});
