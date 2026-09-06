import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { createLatestRequestGuard } from "./requestGuard";
import { resourceRequest } from "./resourceRequest";

export function usePageResource<T>(url: string, enabled: boolean, revision: string,
  reportError: (url: string, message: string | null) => void): [T | null, Dispatch<SetStateAction<T | null>>] {
  const [data, setData] = useState<T | null>(null);
  const guard = useRef(createLatestRequestGuard());
  const cancel = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!enabled) setData(null);
    cancel.current = resourceRequest<T>(url, enabled, guard.current, setData,
      (message) => reportError(url, message));
    return () => { cancel.current?.(); reportError(url, null); };
  }, [url, enabled, revision, reportError]);
  // A mutation response must not be overwritten by a read begun before that mutation.
  const update = useCallback<Dispatch<SetStateAction<T | null>>>((value) => {
    cancel.current?.();
    setData(value);
  }, []);
  return [data, update];
}
