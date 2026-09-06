import { getJson } from "./api";
import type { LatestRequestGuard } from "./requestGuard";

/** Independent reads settle independently; cancellation also guards late mock/transport results. */
export function resourceRequest<T>(url: string, enabled: boolean, guard: LatestRequestGuard,
  apply: (data: T) => void, fail: (message: string | null) => void) {
  if (!enabled) return () => {};
  const token = guard.begin();
  const controller = new AbortController();
  fail(null);
  void getJson<T>(url, { signal: controller.signal, cache: "no-store" })
    .then((data) => { if (guard.isCurrent(token)) apply(data); })
    .catch((reason: Error) => {
      if (reason.name !== "AbortError" && guard.isCurrent(token)) fail(reason.message);
    });
  return () => {
    if (guard.isCurrent(token)) guard.invalidate();
    controller.abort();
  };
}
