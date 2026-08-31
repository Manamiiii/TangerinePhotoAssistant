import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Pagination } from "./Navigation";

describe("requested-page pagination", () => {
  const render = (offset: number, count = 800) => renderToStaticMarkup(<Pagination
    offset={offset} count={count} limit={40} onChange={() => undefined} onLimitChange={() => undefined}
  />);
  it("renders each requested page independently of the last photo response", () => {
    for (const offset of [0, 40, 80, 120, 440]) {
      expect(render(offset)).toContain(`value="${offset / 40 + 1}"`);
    }
  });
  it("keeps next/previous enabled on an intermediate page", () => {
    expect(render(40)).toContain('<button aria-label="下一页">');
    expect(render(40)).toContain('<button aria-label="上一页">');
  });
  it("disables only actual boundaries, including an empty collection", () => {
    expect(render(0)).toContain('<button disabled="" aria-label="上一页">');
    expect(render(760)).toContain('<button disabled="" aria-label="下一页">');
    expect(render(0, 0)).toContain('<button disabled="" aria-label="下一页">');
  });
});
