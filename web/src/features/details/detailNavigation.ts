import type { LibraryCapture, LibraryCapturesResponse } from "../library/types";

export function captureContext(items: LibraryCapture[]): number[] {
  return items.flatMap((item) => item.selection_capture_ids);
}

export function adjacentLibraryOffset(
  page: Pick<LibraryCapturesResponse, "count" | "limit" | "offset">,
  direction: 1 | -1,
): number | null {
  if (direction < 0) return page.offset > 0 ? Math.max(0, page.offset - page.limit) : null;
  const offset = page.offset + page.limit;
  return offset < page.count ? offset : null;
}
