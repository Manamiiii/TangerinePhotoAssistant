export async function getJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function similarityGroupsUrl(
  limit: number,
  offset: number,
  reviewFilter: "all" | "pending" | "completed" | "adjusted",
  albumId: string,
) {
  const parameters = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    review_filter: reviewFilter,
  });
  if (albumId) parameters.set("album_id", albumId);
  return `/api/similarity-groups?${parameters}`;
}
