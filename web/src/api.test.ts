import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("local write session", () => {
  it("refreshes a stale token once after the backend restarts", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "old-token" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Invalid session token" }), { status: 403 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "new-token" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ saved: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { getJson } = await import("./api");

    await expect(getJson<{ saved: boolean }>("/api/example", {
      method: "POST",
      body: "{}",
    })).resolves.toEqual({ saved: true });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    const firstWriteHeaders = fetchMock.mock.calls[1][1].headers as Headers;
    const retriedWriteHeaders = fetchMock.mock.calls[3][1].headers as Headers;
    expect(firstWriteHeaders.get("X-Tangerine-Session")).toBe("old-token");
    expect(retriedWriteHeaders.get("X-Tangerine-Session")).toBe("new-token");
  });
});
