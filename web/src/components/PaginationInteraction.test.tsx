// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { Pagination } from "./Navigation";

it("keeps both controls synchronized and hides the footer when only one page remains", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  const root = createRoot(host);
  function Example() {
    const [offset, setOffset] = useState(0);
    const [limit, setLimit] = useState(40);
    return <>
      <Pagination count={81} limit={limit} offset={offset} onChange={setOffset} onLimitChange={(size) => { setLimit(size); setOffset(0); }} />
      <Pagination compact count={81} limit={limit} offset={offset} onChange={setOffset} />
    </>;
  }
  try {
    await act(() => root.render(<Example />));
    const footer = () => host.querySelector("nav")!;
    expect(footer().querySelector("input,select")).toBeNull();
    expect(footer().querySelectorAll("button")[0].disabled).toBe(true);
    await act(() => footer().querySelectorAll("button")[1].click());
    expect(host.querySelector("input")!.value).toBe("2");
    await act(() => host.querySelector<HTMLButtonElement>('[aria-label="最后一页"]')!.click());
    expect(footer().textContent).toContain("第 3 / 3 页");
    expect(footer().querySelectorAll("button")[1].disabled).toBe(true);
    await act(() => {
      const select = host.querySelector("select")!;
      select.value = "120";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.querySelector("nav")).toBeNull();
    expect(host.querySelector("input")!.value).toBe("1");
  } finally { await act(() => root.unmount()); }
});

it("hides compact pagination for empty results", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  try {
    await act(() => root.render(<Pagination compact count={0} limit={40} offset={0} onChange={() => undefined} />));
    expect(host.innerHTML).toBe("");
  } finally { await act(() => root.unmount()); }
});
