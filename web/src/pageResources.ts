import type { AppView } from "./navigationState";
import type { LibrarySection } from "./features/library/types";

export const resourceNames = ["overview", "filters", "analysis", "preflight", "statistics",
  "equipment", "archive", "activeBaseline", "lightroom", "capabilities", "settings",
  "homePhotos", "similaritySummary", "qualitySummary", "library", "albums", "quality", "similarity"] as const;
export type PageResource = typeof resourceNames[number];
export type ResourceRevisions = Record<PageResource, number>;

export function initialResourceRevisions(): ResourceRevisions {
  return Object.fromEntries(resourceNames.map((name) => [name, 0])) as ResourceRevisions;
}

/** Hidden pages keep their revision but do not issue requests. Re-entry always reloads. */
export function visibleResources(view: AppView, albumContext: boolean, section: LibrarySection) {
  const resources = new Set<PageResource>(["overview"]); // Shared last-scan header.
  const pages: Record<AppView, PageResource[]> = {
    home: ["statistics", "filters", "archive", "activeBaseline", "capabilities", "homePhotos", "similaritySummary"],
    library: ["filters"],
    bursts: ["filters", "similarity"],
    analysis: ["filters", "analysis", "preflight", "quality"],
    statistics: ["statistics"], equipment: ["equipment"],
    lightroom: ["lightroom", "filters", "capabilities"],
    archive: ["archive", "activeBaseline"], settings: ["settings"],
  };
  for (const resource of pages[view]) resources.add(resource);
  if (view === "library") {
    if (albumContext || section === "photos") resources.add("library");
    else { resources.add("albums"); resources.add("equipment"); }
  }
  if (albumContext) {
    if (view !== "bursts") resources.add("similaritySummary");
    if (view !== "analysis") resources.add("qualitySummary");
  }
  return resources;
}

const mutationResources = {
  review: ["overview", "statistics", "lightroom", "library", "quality", "similarity", "similaritySummary", "homePhotos"],
  tags: ["overview", "filters", "analysis", "statistics", "lightroom", "library", "homePhotos"],
  grouping: ["overview", "filters", "analysis", "statistics", "lightroom", "library", "albums", "similarity", "similaritySummary", "homePhotos"],
  albums: ["overview", "filters", "statistics", "lightroom", "library", "albums", "quality", "qualitySummary", "similarity", "similaritySummary", "homePhotos", "equipment"],
  workQueue: ["overview", "analysis", "quality"],
  aiReview: ["overview", "analysis", "quality", "filters", "statistics", "library", "homePhotos"],
  editing: ["statistics"],
  integrity: ["overview", "archive", "activeBaseline"],
  catalog: resourceNames.filter((name) => !["settings", "capabilities", "archive", "activeBaseline"].includes(name)),
  task: resourceNames.filter((name) => !["settings", "capabilities"].includes(name)),
} satisfies Record<string, readonly PageResource[]>;
export type ResourceMutation = keyof typeof mutationResources;

export function invalidateResources(current: ResourceRevisions, mutation: ResourceMutation): ResourceRevisions {
  const next = { ...current };
  for (const name of mutationResources[mutation]) next[name] += 1;
  return next;
}
