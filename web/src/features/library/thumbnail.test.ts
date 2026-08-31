import { describe, expect, it } from "vitest";
import { libraryThumbnailUrl } from "./thumbnail";

describe("library thumbnail sizing", () => {
  it("uses smaller images only for list and small layouts", () => {
    for (const layout of ["list", "small"]) {
      expect(libraryThumbnailUrl("/api/thumbnails/5?size=640", layout)).toBe("/api/thumbnails/5?size=320");
    }
    for (const layout of ["medium", "large"]) {
      expect(libraryThumbnailUrl("/api/thumbnails/5?size=320", layout)).toBe("/api/thumbnails/5?size=640");
    }
  });
  it("preserves other cache parameters and leaves non-API images alone", () => {
    expect(libraryThumbnailUrl("/api/thumbnails/5?v=3&size=640", "list")).toBe("/api/thumbnails/5?v=3&size=320");
    expect(libraryThumbnailUrl("/demo.jpg", "list")).toBe("/demo.jpg");
  });
});
