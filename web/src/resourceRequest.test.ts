import { afterEach, describe, expect, it, vi } from "vitest";
import { createLatestRequestGuard } from "./requestGuard";
import { resourceRequest } from "./resourceRequest";

function pending() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

afterEach(() => vi.unstubAllGlobals());

describe("independent page reads", () => {
  it("does not request disabled resources, including after invalidation", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const guard = createLatestRequestGuard();
    resourceRequest("/api/statistics", false, guard, vi.fn(), vi.fn())();
    resourceRequest("/api/statistics", false, guard, vi.fn(), vi.fn())();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("displays a fast response without waiting for a slow or failed sibling", async () => {
    const slow = pending();
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(slow.promise)
      .mockResolvedValueOnce(Response.json({ capture_total: 13809 })));
    const statistics = vi.fn();
    const overview = vi.fn();
    const failed = vi.fn();
    const stopStats = resourceRequest("/api/statistics", true, createLatestRequestGuard(), statistics, failed);
    const stopOverview = resourceRequest("/api/overview", true, createLatestRequestGuard(), overview, vi.fn());
    await vi.waitFor(() => expect(overview).toHaveBeenCalledWith({ capture_total: 13809 }));
    expect(statistics).not.toHaveBeenCalled();
    slow.resolve(Response.json({ detail: "temporarily unavailable" }, { status: 503 }));
    await vi.waitFor(() => expect(failed).toHaveBeenCalledWith("temporarily unavailable"));
    expect(overview).toHaveBeenCalledTimes(1);
    stopStats(); stopOverview();
  });

  it.each([200, 503])("cancels a hidden page and rejects its late response (%s) after re-entry", async (status) => {
    const old = pending();
    const fetch = vi.fn().mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(Response.json({ rating: 5 }));
    vi.stubGlobal("fetch", fetch);
    const guard = createLatestRequestGuard();
    const apply = vi.fn();
    const fail = vi.fn();
    const leave = resourceRequest("/api/statistics", true, guard, apply, fail);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    leave();
    resourceRequest("/api/statistics", false, guard, apply, fail)();
    const returned = resourceRequest("/api/statistics", true, guard, apply, fail);
    await vi.waitFor(() => expect(apply).toHaveBeenCalledWith({ rating: 5 }));
    old.resolve(Response.json({ rating: 1, detail: "obsolete failure" }, { status }));
    await old.promise;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(apply).toHaveBeenCalledTimes(1);
    expect(fail.mock.calls.every(([message]) => message === null)).toBe(true);
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(fetch.mock.calls[1][1].cache).toBe("no-store");
    returned();
  });

  it("clears a previous read error and accepts a successful explicit retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({ detail: "retry me" }, { status: 503 }))
      .mockResolvedValueOnce(Response.json({ count: 4 })));
    const guard = createLatestRequestGuard();
    const apply = vi.fn();
    const fail = vi.fn();
    const first = resourceRequest("/api/library/filters", true, guard, apply, fail);
    await vi.waitFor(() => expect(fail).toHaveBeenLastCalledWith("retry me"));
    first();
    const retry = resourceRequest("/api/library/filters", true, guard, apply, fail);
    expect(fail).toHaveBeenLastCalledWith(null);
    await vi.waitFor(() => expect(apply).toHaveBeenCalledWith({ count: 4 }));
    retry();
  });
});
