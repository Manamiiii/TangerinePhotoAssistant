import { describe, expect, it } from "vitest";
import { createLatestRequestGuard } from "./requestGuard";

describe("latest request guard", () => {
  it("rejects an older response after a newer request starts", () => {
    const guard = createLatestRequestGuard();
    const older = guard.begin();
    const newer = guard.begin();

    expect(guard.isCurrent(older)).toBe(false);
    expect(guard.isCurrent(newer)).toBe(true);
  });

  it("rejects a response after its domain is invalidated", () => {
    const guard = createLatestRequestGuard();
    const request = guard.begin();
    guard.invalidate();

    expect(guard.isCurrent(request)).toBe(false);
  });
});
