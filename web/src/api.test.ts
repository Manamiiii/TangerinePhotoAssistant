import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("local write session", () => {
  it("explains validation fields instead of displaying object Object", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:[
      {loc:["body","cache","max_size_gb"],msg:"Input should be greater than or equal to 1",input:"private-value"},
    ]}), {status:422})));
    const { getJson } = await import("./api");
    await expect(getJson("/api/settings")).rejects.toThrow("cache.max_size_gb：Input should be greater than or equal to 1");
  });
  it("handles a nonstandard error payload without leaking it into the message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:{input:"private-value"}}), {status:500})));
    const { getJson } = await import("./api");
    await expect(getJson("/api/settings")).rejects.toThrow("请求失败：500");
  });
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
