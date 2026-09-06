import type { Task } from "./components/TaskCard";

const busy = (task: Task) => task.status === "running" || task.status === "paused";

export function taskNeedsRefresh(previous: Task | null, next: Task): boolean {
  if (!previous) return false;
  if (previous.id !== next.id) return busy(previous) || (next.id !== null && !busy(next) && next.status !== "idle");
  return previous.status !== next.status && (
    (previous.status === "running" && next.status === "paused") ||
    (busy(previous) && !busy(next))
  );
}

/** One in-flight read; even aborting a read does not release its slot before settlement. */
export function createTaskMonitor(options: {
  read: (signal: AbortSignal) => Promise<Task>;
  visible: () => boolean;
  apply: (task: Task) => void;
  refresh: () => void;
  error: (message: string | null) => void;
}) {
  let previous: Task | null = null;
  let generation = 0;
  let stopped = false;
  let active: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending = false;
  let failures = 0;
  const clear = () => { clearTimeout(timer); timer = undefined; };
  const delay = () => failures ? Math.min(30_000, 5_000 * 2 ** Math.min(failures - 1, 3))
    : previous?.status === "running" ? 1200 : previous?.status === "paused" ? 3000 : 5000;
  const apply = (next: Task) => {
    if (previous && JSON.stringify(previous) === JSON.stringify(next)) return;
    const refresh = taskNeedsRefresh(previous, next);
    previous = next; // Raw status is independent of dismissed result cards.
    options.apply(next);
    if (refresh) options.refresh();
  };
  const schedule = () => {
    clear();
    if (!stopped && options.visible()) timer = setTimeout(() => void poll(), delay());
  };
  const poll = async () => {
    if (stopped || !options.visible()) return;
    if (active) { pending = true; return; }
    clear();
    const controller = new AbortController();
    active = controller;
    const token = ++generation;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 10_000);
    try {
      const next = await options.read(controller.signal);
      if (token !== generation || stopped) return;
      if (timedOut) throw new Error("任务状态读取超时");
      failures = 0;
      options.error(null);
      apply(next);
    } catch (reason) {
      if (token !== generation || stopped) return;
      failures += 1;
      options.error(timedOut ? "任务状态读取超时" : reason instanceof Error ? reason.message : "无法读取任务状态");
    } finally {
      clearTimeout(timeout);
      active = null;
      if (pending && !stopped && options.visible()) { pending = false; void poll(); }
      else { pending = false; schedule(); }
    }
  };
  return {
    sync() { void poll(); },
    visibilityChanged() {
      if (options.visible()) { void poll(); return; }
      clear(); pending = false; generation += 1; active?.abort();
    },
    accept(task: Task) {
      if (stopped) return;
      // A task-control response supersedes any earlier status read.
      generation += 1; active?.abort(); clear(); pending = false; failures = 0;
      options.error(null);
      apply(task);
      if (!active) schedule();
    },
    stop() { stopped = true; generation += 1; clear(); pending = false; active?.abort(); },
  };
}
