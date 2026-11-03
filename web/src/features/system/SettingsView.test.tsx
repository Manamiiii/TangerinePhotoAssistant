// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import type { Task } from "../../components/TaskCard";
import { SettingsView } from "./SettingsView";
import type { SettingsStatus } from "./types";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
let root: Root;
let host: HTMLDivElement;
const status = {configured:{library:{originals:"C:/Photos",workspace:"C:/Work"},
  cache:{root:"C:/Cache",max_size_gb:20,thumbnail_max_size_gb:4},
  tools:{exiftool:""},models:{python:"",vision_language_model:""}},
  effective:{features:{directory_picker:true}},restart_required:false,backup_path:null} as SettingsStatus;
const button = (name:string) => [...host.querySelectorAll("button")].find(b=>b.textContent===name)!;
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(()=>root.unmount());host.remove();vi.resetAllMocks();});

it("keeps setup drafts and presents a retryable save failure locally",async()=>{
  const save=vi.fn().mockRejectedValueOnce(new Error("缓存不能包含照片目录")).mockResolvedValue(status);
  await act(()=>root.render(<SettingsView status={status} task={{status:"idle"} as Task} save={save} firstRun/>));
  const input=host.querySelector("input")!;
  await act(()=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(input,"C:/MyPhotos");
    input.dispatchEvent(new Event("input",{bubbles:true}));
  });
  await act(()=>button("下一步").click());await act(()=>button("下一步").click());
  await act(()=>button("保存配置").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe("缓存不能包含照片目录");
  expect(host.textContent).toContain("C:/MyPhotos");
  expect(button("保存配置").disabled).toBe(false);
  await act(()=>button("保存配置").click());
  expect(save).toHaveBeenLastCalledWith(expect.objectContaining({library:expect.objectContaining({originals:"C:/MyPhotos"})}));
  expect(host.querySelector('[role="alert"]')).toBeNull();
});

it("shows directory picker errors and retains manual path input",async()=>{
  vi.mocked(getJson).mockRejectedValue(new Error("当前环境没有可用的目录选择器"));
  await act(()=>root.render(<SettingsView status={status} task={{status:"idle"} as Task} save={vi.fn()} firstRun/>));
  await act(()=>button("选择目录").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("目录选择器");
  expect(host.querySelector("input")!.value).toBe("C:/Photos");
  expect(button("选择目录").disabled).toBe(false);
});

it("blocks setup save until the background task status is known",async()=>{
  const save=vi.fn();
  await act(()=>root.render(<SettingsView status={status} task={null} save={save} firstRun/>));
  await act(()=>button("下一步").click());await act(()=>button("下一步").click());
  expect(button("保存配置").disabled).toBe(true);
  expect(host.textContent).toContain("正在确认后台任务状态");
  expect(save).not.toHaveBeenCalled();
});
