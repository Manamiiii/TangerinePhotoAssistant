/** Leave browser connections available for navigation and detail requests. */
export function createThumbnailQueue(concurrency = 4, idleDelay = 600) {
  if (!Number.isInteger(concurrency) || concurrency < 1) throw new Error("Invalid concurrency");
  type Job = { start: () => void; cancel: () => void };
  const waiting: Job[] = [];
  const background: Job[] = [];
  let active = 0;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  const pump = () => {
    clearTimeout(idleTimer);
    idleTimer = undefined;
    while (active < concurrency && waiting.length) waiting.shift()!.start();
    // Speculative work gets only one slot, after foreground work is quiet.
    // A new visible image cancels this timer and never waits behind queued prefetches.
    if (active === 0 && background.length) {
      idleTimer = setTimeout(() => {
        idleTimer = undefined;
        if (active === 0 && !waiting.length) background.shift()?.start();
      }, idleDelay);
    }
  };
  return function schedule<T>(work: (signal: AbortSignal) => Promise<T>, signal: AbortSignal, priority: "visible" | "prefetch" = "visible"): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      if (signal.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
      let started = false;
      const queue = priority === "prefetch" ? background : waiting;
      const job: Job = {
        cancel: () => {
          // Started work observes the same abort signal; do not release its slot
          // until it settles, even when a new page immediately queues more work.
          if (started) return;
          const index = queue.indexOf(job);
          if (index >= 0) queue.splice(index, 1);
          signal.removeEventListener("abort", job.cancel);
          reject(new DOMException("Aborted", "AbortError"));
          pump();
        },
        start: () => {
          started = true;
          active += 1;
          Promise.resolve().then(() => {
            if (signal.aborted) throw new DOMException("Aborted", "AbortError");
            return work(signal);
          }).then(resolve, reject).finally(() => {
            active -= 1;
            signal.removeEventListener("abort", job.cancel);
            pump();
          });
        },
      };
      signal.addEventListener("abort", job.cancel, { once: true });
      queue.push(job);
      pump();
    });
  };
}

export const scheduleThumbnail = createThumbnailQueue();
