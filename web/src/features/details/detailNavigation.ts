import type { LibraryCapture, LibraryCapturesResponse } from "../library/types";

export type DetailNavigationScope = "library" | "fixed";

export function captureContext(items: LibraryCapture[]): number[] {
  return items.map((item) => item.id);
}

export function adjacentLibraryOffset(
  page: Pick<LibraryCapturesResponse, "count" | "limit" | "offset">,
  direction: 1 | -1,
): number | null {
  if (direction < 0) return page.offset > 0 ? Math.max(0, page.offset - page.limit) : null;
  const offset = page.offset + page.limit;
  return offset < page.count ? offset : null;
}

export function adjacentCaptureIds(id: number, context: number[]): number[] {
  const index = context.indexOf(id);
  return index < 0 ? [] : [context[index - 1], context[index + 1]].filter((item): item is number => item != null);
}

export function canNavigateDetail(id: number, context: number[], scope: DetailNavigationScope,
  page: LibraryCapturesResponse | null, direction: 1 | -1): boolean {
  const index = context.indexOf(id);
  if (index < 0) return false;
  return context[index + direction] != null || (scope === "library" && page != null && adjacentLibraryOffset(page, direction) != null);
}

// Resolve every read before committing any UI state. Closing/changing context must
// invalidate this operation even while the first (pagination) request is pending.
export async function resolveDetailNavigation<T>(options: {
  id: number; context: number[]; scope: DetailNavigationScope;
  page: LibraryCapturesResponse | null; direction: 1 | -1;
  isCurrent: () => boolean;
  loadPage: (offset: number) => Promise<LibraryCapturesResponse>;
  loadCapture: (id: number) => Promise<T>;
}): Promise<{ detail: T; id: number; context: number[]; page: LibraryCapturesResponse | null } | null> {
  const { id, direction, scope, isCurrent } = options;
  if (!isCurrent()) return null;
  let context = options.context;
  const index = context.indexOf(id);
  if (index < 0) return null;
  let nextId = context[index + direction];
  let page: LibraryCapturesResponse | null = null;
  if (nextId == null && scope === "library" && options.page) {
    const offset = adjacentLibraryOffset(options.page, direction);
    if (offset == null) return null;
    page = await options.loadPage(offset);
    if (!isCurrent()) return null;
    context = captureContext(page.items);
    nextId = direction > 0 ? context[0] : context[context.length - 1];
  }
  if (nextId == null || !isCurrent()) return null;
  // Never cache mutable review/tag/recipe snapshots between navigation actions.
  const detail = await options.loadCapture(nextId);
  return isCurrent() ? { detail, id: nextId, context, page } : null;
}

export function prefetchAdjacentImages(ids: number[], makeImage: () => Pick<HTMLImageElement, "src" | "removeAttribute"> = () => new Image()): () => void {
  const images = [...new Set(ids)].slice(0, 2).map((id) => {
    const image = makeImage();
    image.src = `/api/thumbnails/${id}?size=1280`;
    return image;
  });
  return () => images.forEach((image) => image.removeAttribute("src"));
}
