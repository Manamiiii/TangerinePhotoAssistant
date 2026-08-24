import { describe, expect, it } from "vitest";
import { defaultLibraryQuery, navigationHash, readNavigationState } from "./navigationState";

describe("navigation state", () => {
  it("round-trips a filtered album and open capture", () => {
    const state = {
      view: "library" as const,
      librarySection: "photos" as const,
      libraryOffset: 80,
      libraryQuery: {
        ...defaultLibraryQuery,
        pageSize: 80,
        albumId: "12",
        category: "旅行",
        selection: "picked",
        dateFrom: "2026-08-01",
        search: "海边 日落",
        sort: "rating",
        collapseGroups: true,
      },
      captureId: 345,
    };

    expect(readNavigationState(navigationHash(state))).toEqual(state);
  });

  it("rejects unsafe enum, date, offset and identifier values", () => {
    const state = readNavigationState(
      "#library?section=unknown&offset=-2&limit=999&album=1%20OR%201%3D1&rating=9&selection=deleted&from=2026-99-99&sort=random&capture=-4",
    );

    expect(state.librarySection).toBe("photos");
    expect(state.libraryOffset).toBe(0);
    expect(state.libraryQuery.pageSize).toBe(40);
    expect(state.libraryQuery.albumId).toBe("");
    expect(state.libraryQuery.rating).toBe("");
    expect(state.libraryQuery.selection).toBe("");
    expect(state.libraryQuery.dateFrom).toBe("");
    expect(state.libraryQuery.sort).toBe("newest");
    expect(state.captureId).toBeNull();
  });

  it("does not carry library filters into another workspace", () => {
    const state = readNavigationState("#analysis?album=12&search=test&capture=8");

    expect(state.view).toBe("analysis");
    expect(state.libraryQuery).toEqual(defaultLibraryQuery);
    expect(state.captureId).toBe(8);
  });
});
