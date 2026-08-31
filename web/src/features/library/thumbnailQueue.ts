/** Leave browser connections available for navigation and detail requests. */
export function createThumbnailQueue(concurrency = 4) {
  if (!Number.isInteger(concurrency) || concurrency < 1) throw new Error("Invalid concurrency");
  type Job = { start: () => void; cancel: () => void };
  const waiting: Job[] = [];
  let active = 0;
  const pump = () => {
    while (active < concurrency && waiting.length) waiting.shift()!.start();
  };
  return function schedule<T>(work: (signal: AbortSignal) => Promise<T>, signal: AbortSignal): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      if (signal.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
      let started = false;
      const job: Job = {
        cancel: () => {
          // Started work observes the same abort signal; do not release its slot
          // until it settles, even when a new page immediately queues more work.
          if (started) return;
          const index = waiting.indexOf(job);
          if (index >= 0) waiting.splice(index, 1);
          signal.removeEventListener("abort", job.cancel);
          reject(new DOMException("Aborted", "AbortError"));
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
      waiting.push(job);
      pump();
    });
  };
}

export const scheduleThumbnail = createThumbnailQueue();
