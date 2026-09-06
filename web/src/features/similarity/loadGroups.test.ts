import { afterEach, describe, expect, it, vi } from "vitest";
import { createLatestRequestGuard } from "../../requestGuard";
import { loadGroups } from "./loadGroups";

const query = { limit: 40, offset: 80, reviewFilter: "pending" as const,
  albumId: "7", confidenceFilter: "low" as const, ageFilter: "older" as const };

function pending() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("similarity list refresh", () => {
  it("preserves all active filters on reload", async () => {
    const fetch = vi.fn().mockImplementation(async () => Response.json({ items: [], count: 0 }));
    vi.stubGlobal("fetch", fetch);
    const guard = createLatestRequestGuard();
    const apply = vi.fn();
    const first = loadGroups(query, guard, apply, vi.fn());
    await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1));
    first();
    const reload = loadGroups(query, guard, apply, vi.fn());
    await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(2));
    for (const [url] of fetch.mock.calls) {
      const params = new URL(String(url), "http://localhost").searchParams;
      expect(Object.fromEntries(params)).toEqual({ limit: "40", offset: "80",
        review_filter: "pending", album_id: "7", confidence_filter: "low", age_filter: "older" });
    }
    reload();
  });

  it.each([200, 500])("ignores a late old response (%s) after changing albums", async (status) => {
    const old = pending();
    const fetch = vi.fn().mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(Response.json({ items: [{ id: 22 }] }));
    vi.stubGlobal("fetch", fetch);
    const guard = createLatestRequestGuard();
    const apply = vi.fn();
    const fail = vi.fn();
    const cancelOld = loadGroups(query, guard, apply, fail);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const cancelNew = loadGroups({ ...query, albumId: "9" }, guard, apply, fail);
    cancelOld();
    await vi.waitFor(() => expect(apply).toHaveBeenCalledExactlyOnceWith({ items: [{ id: 22 }] }));
    old.resolve(Response.json({ items: [{ id: 11 }], detail: "old failure" }, { status }));
    await old.promise;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(apply).toHaveBeenCalledTimes(1);
    expect(fail).not.toHaveBeenCalled();
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    cancelNew();
  });

  it("reports a current failure and can reload successfully", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({ detail: "retry" }, { status: 503 }))
      .mockResolvedValueOnce(Response.json({ items: [] })));
    const guard = createLatestRequestGuard();
    const apply = vi.fn();
    const fail = vi.fn();
    const cancel = loadGroups(query, guard, apply, fail);
    await vi.waitFor(() => expect(fail).toHaveBeenCalledWith("retry"));
    cancel();
    const retry = loadGroups(query, guard, apply, fail);
    await vi.waitFor(() => expect(apply).toHaveBeenCalledWith({ items: [] }));
    retry();
  });
});
