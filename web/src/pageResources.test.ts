import { describe, expect, it } from "vitest";
import { initialResourceRevisions, invalidateResources, visibleResources } from "./pageResources";

describe("page loading and mutation boundaries", () => {
  it("opens the photo library without queries for hidden feature pages", () => {
    expect([...visibleResources("library", false, "photos")].sort()).toEqual(["filters", "library", "overview"]);
    expect([...visibleResources("settings", false, "photos")].sort()).toEqual(["overview", "settings"]);
  });

  it("loads albums and their editable equipment only in the album list", () => {
    const list = visibleResources("library", false, "albums");
    expect(list.has("albums")).toBe(true);
    expect(list.has("equipment")).toBe(true);
    expect(list.has("library")).toBe(false);
    const detail = visibleResources("library", true, "albums");
    expect(detail.has("library")).toBe(true);
    expect(detail.has("albums")).toBe(false);
    expect(detail.has("qualitySummary")).toBe(true);
    expect(detail.has("similaritySummary")).toBe(true);
  });

  it("keeps home summaries independent of library pagination and group filters", () => {
    const home = visibleResources("home", false, "photos");
    expect(home.has("homePhotos")).toBe(true);
    expect(home.has("similaritySummary")).toBe(true);
    expect(home.has("library")).toBe(false);
    expect(home.has("similarity")).toBe(false);
    expect(home.has("statistics")).toBe(true);
    expect(home.has("quality")).toBe(false);
    expect(home.has("preflight")).toBe(false);
  });

  it("reuses each visible list's album summary instead of duplicating it", () => {
    const bursts = visibleResources("bursts", true, "photos");
    expect(bursts.has("similarity")).toBe(true);
    expect(bursts.has("similaritySummary")).toBe(false);
    expect(bursts.has("qualitySummary")).toBe(true);
    const analysis = visibleResources("analysis", true, "photos");
    expect(analysis.has("qualitySummary")).toBe(false);
    expect(analysis.has("similaritySummary")).toBe(true);
  });

  it("rating edits invalidate hidden statistics without fetching them in the library", () => {
    const before = initialResourceRevisions();
    const after = invalidateResources(before, "review");
    const active = visibleResources("library", false, "photos");
    expect([...active].filter((name) => after[name] !== before[name]).sort()).toEqual(["library", "overview"]);
    expect(after.statistics).toBe(1);
    expect(before.statistics).toBe(0);
    expect(after.settings).toBe(0);
    expect(after.equipment).toBe(0);
    expect(after.archive).toBe(0);
    expect(after.preflight).toBe(0);
    expect(visibleResources("statistics", false, "photos").has("statistics")).toBe(true);
  });

  it("tags update filter counts while work queue decisions avoid unrelated lists", () => {
    const before = initialResourceRevisions();
    const tags = invalidateResources(before, "tags");
    expect(tags.filters).toBe(1);
    expect(tags.analysis).toBe(1); // Includes the synchronized model-tag summary.
    expect(tags.library).toBe(1);
    expect(tags.albums).toBe(0);
    expect(tags.similarity).toBe(0);
    const queue = invalidateResources(before, "workQueue");
    expect(Object.keys(queue).filter((name) => queue[name as keyof typeof queue] > 0).sort())
      .toEqual(["analysis", "overview", "quality"]);
  });

  it("task completion invalidates data and protection results without reloading configuration", () => {
    const after = invalidateResources(initialResourceRevisions(), "task");
    expect(after.library).toBe(1);
    expect(after.homePhotos).toBe(1);
    expect(after.archive).toBe(1);
    expect(after.activeBaseline).toBe(1);
    expect(after.preflight).toBe(1);
    expect(after.settings).toBe(0);
    expect(after.capabilities).toBe(0);
  });
});
