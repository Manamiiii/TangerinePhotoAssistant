import type { LibraryQuery, LibrarySection } from "./features/library/types";

export type AppView = "home" | "library" | "bursts" | "analysis" | "statistics" | "equipment" | "lightroom" | "archive" | "settings";

export const appViews: AppView[] = ["home", "library", "bursts", "analysis", "statistics", "equipment", "lightroom", "archive", "settings"];

export const defaultLibraryQuery: LibraryQuery = {
  pageSize: 40, albumId: "", category: "", camera: "", lens: "",
  rating: "", selection: "", quality: "", tagSubject: "", tagStatus: "",
  tagProblem: "", tagLocation: "", selectionReason: "", modelProblem: "",
  reviewCondition: "", dateFrom: "", dateTo: "", search: "", sort: "newest",
  collapseGroups: false,
};

export type NavigationState = {
  view: AppView;
  librarySection: LibrarySection;
  libraryOffset: number;
  libraryQuery: LibraryQuery;
  captureId: number | null;
};

const pageSizes = new Set([20, 40, 80, 120, 200]);
const sorts = new Set(["newest", "oldest", "name", "rating"]);
const selections = new Set(["", "picked", "rejected", "unreviewed"]);
const qualities = new Set(["", "problems", "low", "high", "unanalyzed"]);

function positiveInteger(value: string | null): number | null {
  if (!value || !/^[1-9]\d*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function nonNegativeInteger(value: string | null): number {
  if (!value || !/^\d+$/.test(value)) return 0;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : 0;
}

function text(parameters: URLSearchParams, name: string): string {
  return (parameters.get(name) ?? "").slice(0, 500);
}

function choice(parameters: URLSearchParams, name: string, allowed: Set<string>, fallback = ""): string {
  const value = parameters.get(name) ?? fallback;
  return allowed.has(value) ? value : fallback;
}

export function readNavigationState(hash = window.location.hash): NavigationState {
  const [rawView, rawQuery = ""] = hash.replace(/^#/, "").split("?", 2);
  const view = appViews.includes(rawView as AppView) ? rawView as AppView : "home";
  const parameters = new URLSearchParams(rawQuery);
  const requestedPageSize = positiveInteger(parameters.get("limit"));
  const pageSize = requestedPageSize && pageSizes.has(requestedPageSize) ? requestedPageSize : 40;
  const albumValue = parameters.get("album");
  const albumId = albumValue === "__unassigned__" || positiveInteger(albumValue) ? albumValue ?? "" : "";
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  const dateFrom = text(parameters, "from");
  const dateTo = text(parameters, "to");
  const section = parameters.get("section") === "albums" ? "albums" : "photos";

  return {
    view,
    librarySection: view === "library" ? section : "photos",
    libraryOffset: view === "library" ? nonNegativeInteger(parameters.get("offset")) : 0,
    libraryQuery: view === "library" ? {
      pageSize,
      albumId,
      category: text(parameters, "category"),
      camera: text(parameters, "camera"),
      lens: text(parameters, "lens"),
      rating: choice(parameters, "rating", new Set(["", "1", "2", "3", "4", "5"])),
      selection: choice(parameters, "selection", selections),
      quality: choice(parameters, "quality", qualities),
      tagSubject: text(parameters, "subject"),
      tagStatus: text(parameters, "status"),
      tagProblem: text(parameters, "problem"),
      tagLocation: text(parameters, "location"),
      selectionReason: text(parameters, "reason"),
      modelProblem: text(parameters, "model"),
      reviewCondition: text(parameters, "condition"),
      dateFrom: datePattern.test(dateFrom) ? dateFrom : "",
      dateTo: datePattern.test(dateTo) ? dateTo : "",
      search: text(parameters, "search"),
      sort: choice(parameters, "sort", sorts, "newest"),
      collapseGroups: albumId !== "" && parameters.get("collapsed") === "1",
    } : { ...defaultLibraryQuery },
    captureId: positiveInteger(parameters.get("capture")),
  };
}

export function navigationHash(state: NavigationState): string {
  const parameters = new URLSearchParams();
  if (state.view === "library") {
    const query = state.libraryQuery;
    if (state.librarySection === "albums") parameters.set("section", "albums");
    if (state.libraryOffset) parameters.set("offset", String(state.libraryOffset));
    if (query.pageSize !== defaultLibraryQuery.pageSize) parameters.set("limit", String(query.pageSize));
    const values: Array<[string, string]> = [
      ["album", query.albumId], ["category", query.category], ["camera", query.camera],
      ["lens", query.lens], ["rating", query.rating], ["selection", query.selection],
      ["quality", query.quality], ["subject", query.tagSubject], ["status", query.tagStatus],
      ["problem", query.tagProblem], ["location", query.tagLocation],
      ["reason", query.selectionReason], ["model", query.modelProblem],
      ["condition", query.reviewCondition], ["from", query.dateFrom], ["to", query.dateTo],
      ["search", query.search], ["sort", query.sort === "newest" ? "" : query.sort],
    ];
    values.forEach(([name, value]) => { if (value) parameters.set(name, value); });
    if (query.albumId && query.collapseGroups) parameters.set("collapsed", "1");
  }
  if (state.captureId) parameters.set("capture", String(state.captureId));
  const queryString = parameters.toString();
  return `#${state.view}${queryString ? `?${queryString}` : ""}`;
}
