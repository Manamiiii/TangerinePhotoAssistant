// @vitest-environment jsdom
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AlbumsView } from "./features/library/LibraryView";
import { EditRecipePanel } from "./features/details/EditRecipePanel";
import { createUnsavedRegistry } from "./unsavedChanges";
import { ignorePhotoShortcut, manageDialogFocus } from "./components/dialogFocus";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(() => root.unmount()); document.body.replaceChildren(); vi.restoreAllMocks(); });
const button = (name: string) => [...host.querySelectorAll("button")].find((item) => item.textContent === name)!;
const click = async (element: HTMLElement) => { await act(() => element.click()); };
const input = async (element: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  await act(() => {
    Object.getOwnPropertyDescriptor(element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

describe("editor safety", () => {
  it("retains an album draft after failure and blocks duplicate submissions while saving", async () => {
    let settle!: (id: number | null) => void;
    const createAlbum = vi.fn(() => new Promise<number | null>((resolve) => { settle = resolve; }));
    const props = { albums: null, filters: { album_types: [{ name: "日常" }] }, equipment: null,
      createAlbum, updateAlbum: vi.fn(), createAlbumType: vi.fn(), renameAlbumType: vi.fn(), deleteAlbumType: vi.fn(), openAlbum: vi.fn(), changePage: vi.fn(), changePageSize: vi.fn() } as unknown as ComponentProps<typeof AlbumsView>;
    await act(() => root.render(<AlbumsView {...props} />));
    await click(button("新建相册"));
    await input(host.querySelector('input[maxlength="180"]')!, "旅行草稿");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await click(button("取消"));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[role="dialog"]')).not.toBeNull();
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    await click(button("保存"));
    expect(button("保存中…").disabled).toBe(true);
    await act(() => { host.querySelector("form.editor-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(createAlbum).toHaveBeenCalledTimes(1);
    await act(() => settle(null));
    expect(host.querySelector('[role="dialog"]')).not.toBeNull();
    expect((host.querySelector('input[maxlength="180"]') as HTMLInputElement).value).toBe("旅行草稿");
    expect(host.textContent).toContain("保存失败");
    await click(button("保存"));
    await act(() => settle(42));
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    const savedUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedUnload);
    expect(savedUnload.defaultPrevented).toBe(false);
  });

  it("keeps recipe edits across unrelated detail refreshes and failed saves", async () => {
    const detail = { id: 1, stem: "photo", thumbnail_url: "/thumb", edit_recipes: [], ai_analyses: [] } as unknown as ComponentProps<typeof EditRecipePanel>["detail"];
    const save = vi.fn().mockRejectedValue(new Error("offline"));
    const render = (value: typeof detail) => root.render(<EditRecipePanel detail={value} saveRecipe={save} restoreRecipe={vi.fn()} />);
    await act(() => render(detail));
    await input(host.querySelector("textarea")!, "保留肤色");
    await act(() => render({ ...detail }));
    expect(host.querySelector("textarea")!.value).toBe("保留肤色");
    await click(button("保存草稿"));
    expect(host.querySelector("textarea")!.value).toBe("保留肤色");
    expect(host.querySelector('[role="alert"]')!.textContent).toBe("offline");
  });

  it("requires confirmation for dirty drafts and never allows departure during a save", () => {
    const registry = createUnsavedRegistry(); const key = {}; const confirm = vi.fn(() => false); const notify = vi.fn();
    expect(registry.canLeave(confirm, notify)).toBe(true);
    registry.set(key, true, false);
    expect(registry.canLeave(confirm, notify)).toBe(false);
    confirm.mockReturnValue(true);
    expect(registry.canLeave(confirm, notify)).toBe(true);
    registry.set(key, false, true);
    expect(registry.canLeave(confirm, notify)).toBe(false);
    expect(notify).toHaveBeenCalledTimes(1);
    registry.remove(key);
    expect(registry.hasChanges()).toBe(false);
  });

  it("wraps focus, recovers removed focus and restores the opener", () => {
    host.innerHTML = '<button id="opener">open</button><section tabindex="-1" aria-modal="true"><button id="first">first</button><button id="last">last</button></section>';
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
    const opener = host.querySelector<HTMLElement>("#opener")!; opener.focus();
    const release = manageDialogFocus(host.querySelector("section")!);
    expect(document.activeElement?.id).toBe("first");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true }));
    expect(document.activeElement?.id).toBe("last");
    host.querySelector("#last")!.remove();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", cancelable: true }));
    expect(document.activeElement?.id).toBe("first");
    release(); expect(document.activeElement).toBe(opener);
  });

  it("does not turn modified keys, composition or editor typing into photo commands", () => {
    for (const modifier of ["ctrlKey", "metaKey", "altKey", "isComposing"]) {
      expect(ignorePhotoShortcut(new KeyboardEvent("keydown", { key: "1", [modifier]: true }), null)).toBe(true);
    }
    expect(ignorePhotoShortcut(new KeyboardEvent("keydown", { key: "1" }), document.createElement("input"))).toBe(true);
    expect(ignorePhotoShortcut(new KeyboardEvent("keydown", { key: "1" }), document.createElement("button"))).toBe(false);
  });
});
