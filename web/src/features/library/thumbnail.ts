/** List/small cards do not need the same decode/transfer size as large cards. */
export function libraryThumbnailUrl(url: string, layout: string): string {
  if (!url.startsWith("/api/thumbnails/")) return url;
  const [path, query = ""] = url.split("?");
  const parameters = new URLSearchParams(query);
  parameters.set("size", layout === "list" || layout === "small" ? "320" : "640");
  return `${path}?${parameters}`;
}
