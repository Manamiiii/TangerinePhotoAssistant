import type { LibraryQuery } from "./features/library/types";

let sessionToken: Promise<string> | null = null;

function isWrite(options: RequestInit): boolean {
  const method = (options.method ?? "GET").toUpperCase();
  return method !== "GET" && method !== "HEAD" && method !== "OPTIONS";
}

function loadSessionToken(force = false): Promise<string> {
  if (force) sessionToken = null;
  sessionToken ??= fetch("/api/session", { cache: "no-store" })
    .then(async (response) => {
      if (!response.ok) throw new Error(`无法建立本地会话：${response.status}`);
      return (await response.json() as { token: string }).token;
    })
    .catch((reason) => {
      sessionToken = null;
      throw reason;
    });
  return sessionToken;
}

async function writeOptions(options: RequestInit, forceToken = false): Promise<RequestInit> {
  if (!isWrite(options)) return options;
  const headers = new Headers(options.headers);
  headers.set("X-Tangerine-Session", await loadSessionToken(forceToken));
  return { ...options, headers };
}

export async function getJson<T>(url: string, options?: RequestInit): Promise<T> {
  const requestOptions = options ?? {};
  let response = await fetch(url, await writeOptions(requestOptions));
  if (response.status === 403 && isWrite(requestOptions)) {
    const body = await response.clone().json().catch(() => ({})) as { detail?: string };
    if (body.detail === "Invalid session token") {
      response = await fetch(url, await writeOptions(requestOptions, true));
    }
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function libraryCapturesUrl(query: LibraryQuery, offset: number) {
  const parameters = new URLSearchParams({
    limit: String(query.pageSize), offset: String(offset), sort: query.sort,
  });
  if (query.albumId === "__unassigned__") parameters.set("unassigned", "true");
  else if (query.albumId) parameters.set("album_id", query.albumId);
  const filters: Array<[string, string]> = [
    ["category", query.category], ["camera_model", query.camera],
    ["lens_model", query.lens], ["rating", query.rating],
    ["selection", query.selection], ["quality", query.quality],
    ["tag_subject", query.tagSubject], ["tag_status", query.tagStatus],
    ["tag_problem", query.tagProblem], ["tag_location", query.tagLocation],
    ["selection_reason", query.selectionReason], ["model_problem", query.modelProblem],
    ["review_condition", query.reviewCondition], ["date_from", query.dateFrom],
    ["date_to", query.dateTo],
  ];
  for (const [name, value] of filters) if (value) parameters.set(name, value);
  if (query.search.trim()) parameters.set("search", query.search.trim());
  if (query.albumId && query.collapseGroups) parameters.set("collapse_groups", "true");
  return `/api/library/captures?${parameters}`;
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
