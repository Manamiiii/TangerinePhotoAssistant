import { useEffect } from "react";
import { nextPagePreviewUrl, prefetchLibraryPage } from "./prefetch";
import type { LibraryCapturesResponse, LibraryQuery, PhotoLayout } from "./types";

export function useLibraryPrefetch(query: LibraryQuery, page: LibraryCapturesResponse | null, layout: PhotoLayout, enabled: boolean) {
  useEffect(() => {
    if (!enabled || !page || document.visibilityState !== "visible") return;
    const url = nextPagePreviewUrl(query, page);
    if (!url) return;
    const controller = new AbortController();
    // Bound even stalled responses. A timeout does not schedule another attempt.
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    const hide = () => { if (document.visibilityState !== "visible") controller.abort(); };
    document.addEventListener("visibilitychange", hide);
    void prefetchLibraryPage(url, layout, controller.signal).finally(() => window.clearTimeout(timeout));
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
      document.removeEventListener("visibilitychange", hide);
    };
  }, [query, page, layout, enabled]);
}
