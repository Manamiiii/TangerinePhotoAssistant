import { getJson, libraryCapturesUrl } from "../../api";
import { libraryThumbnailUrl } from "./thumbnail";
import { scheduleThumbnail } from "./thumbnailQueue";
import type { LibraryCapturesResponse, LibraryQuery, PhotoLayout } from "./types";

export const NEXT_PAGE_PREVIEW_COUNT = 8;

export function nextPagePreviewUrl(query: LibraryQuery, page: LibraryCapturesResponse): string | null {
  const offset = page.offset + page.limit;
  if (offset >= page.count || !page.items.length) return null;
  // Offset uses the real page size, not the small speculative batch size.
  return libraryCapturesUrl({ ...query, pageSize: Math.min(NEXT_PAGE_PREVIEW_COUNT, page.count - offset) }, offset);
}

/** Warm only HTTP/disk image caches. Never retain speculative ratings/group data. */
export async function prefetchLibraryPage(url: string, layout: PhotoLayout, signal: AbortSignal) {
  try {
    const page = await scheduleThumbnail(
      (signal) => getJson<LibraryCapturesResponse>(url, { signal }), signal, "prefetch",
    );
    for (const item of page.items.slice(0, NEXT_PAGE_PREVIEW_COUNT)) {
      if (signal.aborted) return;
      const src = libraryThumbnailUrl(item.thumbnail_url, layout);
      // Restrict speculative requests to local derivatives, never originals/external URLs.
      if (!src.startsWith("/api/thumbnails/")) continue;
      await scheduleThumbnail(async (signal) => {
        const response = await fetch(src, { signal });
        if (!response.ok) throw new Error(`Thumbnail ${response.status}`);
        await response.blob(); // Consume body to populate HTTP cache; no retained object URLs.
      }, signal, "prefetch");
    }
  } catch {
    // Optional work: stop this batch on errors (including 503), with no automatic retry/toast.
  }
}
