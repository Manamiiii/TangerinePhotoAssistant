import { afterEach, describe, expect, it, vi } from "vitest";
import { createThumbnailQueue } from "./thumbnailQueue";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

describe("thumbnail download queue", () => {
  afterEach(() => vi.useRealTimers());

  it("waits for foreground to finish and an idle interval before prefetching", async () => {
    vi.useFakeTimers();
    const queue = createThumbnailQueue(2);
    const pending = deferred<number>();
    const visible = queue(() => pending.promise, new AbortController().signal);
    const work = vi.fn(async () => 2);
    const background = queue(work, new AbortController().signal, "prefetch");
    await vi.advanceTimersByTimeAsync(1000);
    expect(work).not.toHaveBeenCalled();
    pending.resolve(1);
    await visible;
    await flush();
    await vi.advanceTimersByTimeAsync(599);
    expect(work).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(background).resolves.toBe(2);
  });

  it("new visible work overtakes queued prefetch and can start beside one active prefetch", async () => {
    vi.useFakeTimers();
    const queue = createThumbnailQueue(2);
    const pending = deferred<number>();
    const active = queue(() => pending.promise, new AbortController().signal, "prefetch");
    const next = vi.fn(async () => 2);
    const queued = queue(next, new AbortController().signal, "prefetch");
    await vi.advanceTimersByTimeAsync(600);
    expect(next).not.toHaveBeenCalled();
    await expect(queue(async () => 3, new AbortController().signal)).resolves.toBe(3);
    expect(next).not.toHaveBeenCalled();
    pending.resolve(1);
    await active;
    await flush();
    await vi.advanceTimersByTimeAsync(600);
    await expect(queued).resolves.toBe(2);
  });

  it("cancels idle timers and old speculative jobs before making requests", async () => {
    vi.useFakeTimers();
    const queue = createThumbnailQueue();
    const controller = new AbortController();
    const work = vi.fn();
    const result = queue(work, controller.signal, "prefetch").catch((error: Error) => error.name);
    controller.abort();
    await expect(result).resolves.toBe("AbortError");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(2000);
    expect(work).not.toHaveBeenCalled();
  });

  it("restarts the quiet interval when visible work arrives", async () => {
    vi.useFakeTimers();
    const queue = createThumbnailQueue();
    const work = vi.fn(async () => 1);
    const result = queue(work, new AbortController().signal, "prefetch");
    await vi.advanceTimersByTimeAsync(500);
    await queue(async () => 2, new AbortController().signal);
    await flush();
    await vi.advanceTimersByTimeAsync(599);
    expect(work).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toBe(1);
  });
  it("bounds downloads and starts the next one when a slot becomes available", async () => {
    const queue = createThumbnailQueue(2);
    const pending = Array.from({ length: 4 }, () => deferred<number>());
    const work = vi.fn((index: number) => pending[index].promise);
    const results = pending.map((_, index) => queue(() => work(index), new AbortController().signal));
    await flush();
    expect(work.mock.calls).toEqual([[0], [1]]);
    pending[0].resolve(0);
    await flush();
    expect(work.mock.calls).toEqual([[0], [1], [2]]);
    pending.forEach((entry, index) => entry.resolve(index));
    await expect(Promise.all(results)).resolves.toEqual([0, 1, 2, 3]);
  });

  it("removes old-page queued requests without downloading them", async () => {
    const queue = createThumbnailQueue(1);
    const first = deferred<number>();
    const active = queue(() => first.promise, new AbortController().signal);
    const controller = new AbortController();
    const staleWork = vi.fn();
    const stale = queue(staleWork, controller.signal).catch((error: Error) => error.name);
    controller.abort();
    const next = queue(async () => 3, new AbortController().signal);
    first.resolve(1);
    await expect(active).resolves.toBe(1);
    await expect(stale).resolves.toBe("AbortError");
    await expect(next).resolves.toBe(3);
    expect(staleWork).not.toHaveBeenCalled();
  });

  it("passes cancellation to active downloads and releases the slot on abort", async () => {
    const queue = createThumbnailQueue(1);
    const controller = new AbortController();
    const result = queue((signal) => new Promise((_, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }), controller.signal).catch((error: Error) => error.name);
    await flush();
    controller.abort();
    await expect(result).resolves.toBe("AbortError");
    await expect(queue(async () => "new page", new AbortController().signal)).resolves.toBe("new page");
  });

  it("does not run an already canceled request or one canceled before work starts", async () => {
    const queue = createThumbnailQueue(1);
    const controller = new AbortController();
    const work = vi.fn();
    const result = queue(work, controller.signal).catch((error: Error) => error.name);
    controller.abort();
    await expect(result).resolves.toBe("AbortError");
    await expect(queue(work, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(work).not.toHaveBeenCalled();
  });

  it("recovers after synchronous or asynchronous errors", async () => {
    const queue = createThumbnailQueue(1);
    await expect(queue(() => { throw new Error("sync"); }, new AbortController().signal)).rejects.toThrow("sync");
    await expect(queue(async () => { throw new Error("async"); }, new AbortController().signal)).rejects.toThrow("async");
    await expect(queue(async () => 4, new AbortController().signal)).resolves.toBe(4);
  });
});
