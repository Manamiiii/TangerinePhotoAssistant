import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Task } from "./components/TaskCard";
import { createTaskMonitor, taskNeedsRefresh } from "./taskMonitor";

function task(status: Task["status"], id: string | null = "a"): Task {
  return { id, status, stage: status, message: status, current: 0, total: null,
    error: null, bytes_current: 0, bytes_total: null, speed_bytes_per_second: null,
    items_per_second: null, eta_seconds: null, failure_count: 0, pausable: false, result: null };
}
function pending() {
  let resolve!: (task: Task) => void;
  const promise = new Promise<Task>((done) => { resolve = done; });
  return { promise, resolve };
}
function fixture(read = vi.fn<(signal: AbortSignal) => Promise<Task>>().mockResolvedValue(task("idle", null))) {
  const apply = vi.fn(); const refresh = vi.fn(); const error = vi.fn();
  let visible = true;
  const monitor = createTaskMonitor({ read, apply, refresh, error, visible: () => visible });
  return { monitor, read, apply, refresh, error, hide: () => { visible = false; monitor.visibilityChanged(); },
    show: () => { visible = true; monitor.visibilityChanged(); } };
}
beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

describe("task status monitoring", () => {
  it("serializes slow reads and coalesces repeated wakeups", async () => {
    const first = pending();
    const f = fixture(vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(task("running")));
    f.monitor.sync();
    await vi.advanceTimersByTimeAsync(4000);
    f.monitor.sync(); f.monitor.sync(); f.monitor.sync();
    expect(f.read).toHaveBeenCalledTimes(1);
    first.resolve(task("running"));
    await vi.advanceTimersByTimeAsync(0);
    expect(f.read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1199);
    expect(f.read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(f.read).toHaveBeenCalledTimes(3);
    f.monitor.stop();
  });

  it("discovers a task started elsewhere even when initially idle", async () => {
    const f = fixture(vi.fn().mockResolvedValueOnce(task("idle", null))
      .mockResolvedValueOnce(task("running", "other-window"))
      .mockResolvedValue(task("paused", "other-window")));
    f.monitor.sync();
    await vi.advanceTimersByTimeAsync(5000);
    expect(f.apply).toHaveBeenLastCalledWith(task("running", "other-window"));
    await vi.advanceTimersByTimeAsync(1200);
    expect(f.apply).toHaveBeenLastCalledWith(task("paused", "other-window"));
    expect(f.refresh).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(f.read).toHaveBeenCalledTimes(4);
    expect(f.refresh).toHaveBeenCalledTimes(1);
    expect(f.apply).toHaveBeenCalledTimes(3);
    f.monitor.stop();
  });

  it("stops reads while hidden and ignores old responses on returning", async () => {
    const old = pending();
    const f = fixture(vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue(task("complete")));
    f.monitor.sync(); f.hide();
    expect(f.read.mock.calls[0][0].aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(f.read).toHaveBeenCalledTimes(1);
    f.show(); f.monitor.sync();
    expect(f.read).toHaveBeenCalledTimes(1);
    old.resolve(task("running"));
    await vi.advanceTimersByTimeAsync(0);
    expect(f.apply).toHaveBeenCalledExactlyOnceWith(task("complete"));
    expect(f.error.mock.calls.every(([value]) => value === null)).toBe(true);
    f.monitor.stop();
  });

  it("does not let a read started before a control response overwrite it", async () => {
    const old = pending();
    const f = fixture(vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue(task("running", "new")));
    f.monitor.sync();
    f.monitor.accept(task("running", "new"));
    expect(f.read.mock.calls[0][0].aborted).toBe(true);
    old.resolve(task("idle", null));
    await vi.advanceTimersByTimeAsync(0);
    expect(f.apply).toHaveBeenCalledExactlyOnceWith(task("running", "new"));
    await vi.advanceTimersByTimeAsync(1200);
    expect(f.read).toHaveBeenCalledTimes(2);
    expect(f.apply).toHaveBeenCalledTimes(1);
    f.monitor.stop();
  });

  it("refreshes completed or cancelled work once, including local cancellation", async () => {
    const f = fixture(vi.fn().mockResolvedValue(task("complete")));
    f.monitor.accept(task("running"));
    f.monitor.sync();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(f.refresh).toHaveBeenCalledTimes(1);
    // A paused task can be cancelled directly, without another running poll.
    f.monitor.accept(task("paused", "b"));
    f.monitor.accept(task("cancelled", "b"));
    expect(f.refresh).toHaveBeenCalledTimes(2);
    f.monitor.stop();
  });

  it("backs off failures, preserves the last known task and clears the error on recovery", async () => {
    const f = fixture(vi.fn().mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(task("running")));
    f.monitor.accept(task("paused"));
    f.monitor.sync();
    await vi.advanceTimersByTimeAsync(0);
    expect(f.error).toHaveBeenLastCalledWith("offline");
    expect(f.apply).toHaveBeenLastCalledWith(task("paused"));
    await vi.advanceTimersByTimeAsync(5000);
    expect(f.read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(9999);
    expect(f.read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(f.error).toHaveBeenLastCalledWith(null);
    expect(f.apply).toHaveBeenLastCalledWith(task("running"));
    f.monitor.stop();
  });

  it("times out stalled fetches and releases all timers on stop", async () => {
    const read = vi.fn((signal: AbortSignal) => new Promise<Task>((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    const f = fixture(read);
    f.monitor.sync();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(f.error).toHaveBeenLastCalledWith("任务状态读取超时");
    await vi.advanceTimersByTimeAsync(5000);
    expect(read).toHaveBeenCalledTimes(2);
    f.monitor.stop();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("refreshes missed transitions and service restarts without treating dismissal as server state", () => {
    expect(taskNeedsRefresh(task("idle", null), task("complete", "missed"))).toBe(true);
    expect(taskNeedsRefresh(task("running", "old"), task("running", "new"))).toBe(true);
    expect(taskNeedsRefresh(task("running"), task("idle", null))).toBe(true);
    expect(taskNeedsRefresh(task("complete"), task("complete"))).toBe(false);
    expect(taskNeedsRefresh(task("paused"), task("running"))).toBe(false);
    expect(taskNeedsRefresh(null, task("complete"))).toBe(false);
  });
});
