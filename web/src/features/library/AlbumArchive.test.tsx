// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import type { Task } from "../../components/TaskCard";
import { AlbumArchive } from "./AlbumArchive";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
let root: Root;
let host: HTMLDivElement;
const plan = { id: "plan", album_name: "Birthday", target: "photos/纪念/2026/Birthday", capture_count: 1, total_bytes: 10, status: "preview", items: [{ source: "photos/待整理/a.jpg", target: "photos/纪念/2026/Birthday/a.jpg", bytes: 10 }] };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getJson).mockImplementation(async (url) => url.endsWith("/status") ? { file_count: 1, inbox_count: 1, pending: false } : plan as never);
});
afterEach(async () => { await act(() => root.unmount()); host.remove(); vi.resetAllMocks(); });
const button = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
async function confirm() {
  const input = host.querySelector("input")!;
  await act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "归档 Birthday");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("previews cleanup scope and requires exact confirmation before using the system API", async () => {
  const started = vi.fn();
  await act(() => root.render(<AlbumArchive albumId={52} task={{ status: "idle" } as Task} onStarted={started} />));
  await act(() => button("完成归档").click());
  expect(button("确认归档").disabled).toBe(true);
  expect(host.textContent).toContain("清理已校验的待整理源文件");
  await confirm();
  expect(button("确认归档").disabled).toBe(false);
  vi.mocked(getJson).mockResolvedValueOnce({ id: "task", status: "running" });
  await act(() => button("确认归档").click());
  expect(getJson).toHaveBeenLastCalledWith("/api/albums/52/archive/execute", expect.objectContaining({ method: "POST", body: JSON.stringify({ plan_id: "plan", confirmation: "归档 Birthday" }) }));
  expect(started).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});
it("preserves the preview and confirmation when the start fails", async () => {
  await act(() => root.render(<AlbumArchive albumId={52} task={{ status: "idle" } as Task} onStarted={vi.fn()} />));
  await act(() => button("完成归档").click()); await confirm();
  vi.mocked(getJson).mockRejectedValueOnce(new Error("目标冲突"));
  await act(() => button("确认归档").click());
  expect(host.querySelector('[role="alert"]')!.textContent).toBe("目标冲突");
  expect(host.querySelector("input")!.value).toBe("归档 Birthday");
});
it("disables the entry while another task occupies the slot", async () => {
  await act(() => root.render(<AlbumArchive albumId={52} task={{ status: "paused", stage: "ai-analysis" } as Task} onStarted={vi.fn()} />));
  expect(button("完成归档").disabled).toBe(true);
});
