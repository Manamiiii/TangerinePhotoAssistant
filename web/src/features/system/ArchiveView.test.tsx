// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import { ArchiveView, type ArchiveStatus } from "./ArchiveView";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
let root: Root;
let host: HTMLDivElement;
const baseline: ArchiveStatus = {
  baseline: { id: 1, name: "baseline", created_at: "2026-09-22", file_count: 1, total_bytes: 1 },
  comparison: { missing: 1, changed: 0, new: 0, healthy: false, samples: [{ relative_path: "a.jpg", status: "missing" }] },
};
const button = (name: string) => [...host.querySelectorAll("button")].find((item) => item.textContent === name)!;
const render = () => root.render(<ArchiveView archive={baseline} activeLibrary={null} createBaseline={vi.fn()} createActiveBaseline={vi.fn()} checkIntegrity={vi.fn()} saveInvestigation={vi.fn()} />);
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getJson).mockResolvedValue({ count: 0, items: [], directories: [] });
});
afterEach(async () => { await act(() => root.unmount()); host.remove(); vi.resetAllMocks(); });

it("does not replace a new incident filter with a late response", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(getJson).mockImplementation((url) => url === "/api/task-incidents?workflow=open"
    ? new Promise((resolve) => { finish = resolve; })
    : Promise.resolve({ count: 0, items: [], directories: [] }) as never);
  await act(render);
  const select = host.querySelector<HTMLSelectElement>('[aria-label="任务异常状态"]')!;
  await act(() => { select.value = "all"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(() => finish({ count: 1, items: [{ task_kind: "scan", task_label: "扫描", message: "旧请求内容", workflow_status: "new", occurrence_count: 1 }] }));
  expect(host.textContent).not.toContain("旧请求内容");
  expect(host.textContent).toContain("当前状态下没有后台任务异常");
});

it("shows difference errors and retries the same request", async () => {
  await act(render);
  vi.mocked(getJson).mockRejectedValueOnce(new Error("差异请求失败"));
  await act(() => button("调查差异").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("差异请求失败");
  await act(() => button("重试差异").click());
  expect(host.textContent).toContain("完整差异清单");
  expect(host.querySelector('[role="alert"]')).toBeNull();
});

it("does not reopen differences after the panel is closed", async () => {
  await act(render);
  let finish!: (value: unknown) => void;
  vi.mocked(getJson).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(() => button("调查差异").click());
  await act(() => button("关闭").click());
  await act(() => finish({ count: 0, items: [], limit: 50, offset: 0 }));
  expect(host.textContent).not.toContain("完整差异清单");
});
