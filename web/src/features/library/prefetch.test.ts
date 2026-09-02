import { afterEach, describe, expect, it, vi } from "vitest";
import { defaultLibraryQuery } from "../../navigationState";
import { nextPagePreviewUrl, prefetchLibraryPage } from "./prefetch";
import type { LibraryCapture, LibraryCapturesResponse } from "./types";

const items = Array.from({ length: 12 }, (_, id) => ({ id, thumbnail_url: `/api/thumbnails/${id}?size=640` } as LibraryCapture));
const page: LibraryCapturesResponse = { count: 120, offset: 40, limit: 40, collapsed: false, items };
// Keep body completion deterministic under fake timers (no Node stream scheduling).
const jsonResponse = (value: unknown) => ({ ok: true, status: 200, json: async () => value });
const imageResponse = () => ({ ok: true, status: 200, blob: async () => new Blob(["jpeg"]) });

describe("bounded next-page thumbnail prefetch", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("uses the real next-page offset and preserves filters and group folding", () => {
    const url = nextPagePreviewUrl({ ...defaultLibraryQuery, albumId: "7", collapseGroups: true, search: "海", tagSubject: "风景", sort: "oldest" }, page)!;
    const parameters = new URL(url, "http://localhost").searchParams;
    expect(Object.fromEntries(parameters)).toMatchObject({ offset: "80", limit: "8", album_id: "7", collapse_groups: "true", search: "海", tag_subject: "风景", sort: "oldest" });
  });

  it("does not wrap past the last page or speculate for an empty result", () => {
    expect(nextPagePreviewUrl(defaultLibraryQuery, { ...page, count: 80 })).toBeNull();
    expect(nextPagePreviewUrl(defaultLibraryQuery, { ...page, items: [] })).toBeNull();
    expect(nextPagePreviewUrl(defaultLibraryQuery, { ...page, count: 83 })).toContain("limit=3&offset=80");
  });

  it("fetches at most eight correctly sized thumbnails, not original photos", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async (url: string) => url.startsWith("/api/library/")
      ? jsonResponse(page) : imageResponse());
    vi.stubGlobal("fetch", fetcher);
    const result = prefetchLibraryPage("/api/library/captures?limit=8&offset=80", "list", new AbortController().signal);
    expect(fetcher).not.toHaveBeenCalled();
    await vi.runAllTimersAsync();
    await result;
    expect(fetcher).toHaveBeenCalledTimes(9);
    expect(fetcher.mock.calls.slice(1).map(([url]) => url)).toEqual(items.slice(0, 8).map((item) => `/api/thumbnails/${item.id}?size=320`));
  });

  it("does not request any images after a page/filter cancellation", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetcher = vi.fn(async () => { controller.abort(); return jsonResponse(page); });
    vi.stubGlobal("fetch", fetcher);
    const result = prefetchLibraryPage("/api/library/captures", "large", controller.signal);
    await vi.runAllTimersAsync();
    await result;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("abandons the batch on cache backpressure without retries or surfaced errors", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async (url: string) => url.startsWith("/api/library/")
      ? jsonResponse(page) : { ok: false, status: 503 });
    vi.stubGlobal("fetch", fetcher);
    const result = prefetchLibraryPage("/api/library/captures", "medium", new AbortController().signal);
    await vi.runAllTimersAsync();
    await expect(result).resolves.toBeUndefined();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][0]).toBe("/api/thumbnails/0?size=640");
  });

  it("does not follow original or external image URLs", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => jsonResponse({ ...page, items: [
      { thumbnail_url: "/api/originals/1" }, { thumbnail_url: "https://example.com/photo.jpg" },
    ] }));
    vi.stubGlobal("fetch", fetcher);
    const result = prefetchLibraryPage("/api/library/captures", "small", new AbortController().signal);
    await vi.runAllTimersAsync();
    await result;
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
