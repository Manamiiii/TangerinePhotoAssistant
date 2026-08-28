import { describe, expect, it } from "vitest";
import { adjacentLibraryOffset, captureContext } from "./detailNavigation";
import type { LibraryCapture } from "../library/types";

describe("detail navigation", () => {
  it("keeps every member of a collapsed similarity group in browsing order", () => {
    const items = [
      { selection_capture_ids: [10] },
      { selection_capture_ids: [20, 21, 22] },
      { selection_capture_ids: [30] },
    ] as LibraryCapture[];

    expect(captureContext(items)).toEqual([10, 20, 21, 22, 30]);
  });

  it("moves across page boundaries without exceeding the result set", () => {
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 0 }, -1)).toBeNull();
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 0 }, 1)).toBe(40);
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 40 }, -1)).toBe(0);
    expect(adjacentLibraryOffset({ count: 95, limit: 40, offset: 80 }, 1)).toBeNull();
  });
});
