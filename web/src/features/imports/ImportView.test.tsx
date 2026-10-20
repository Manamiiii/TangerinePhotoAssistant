// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import type { Task } from "../../components/TaskCard";
import type { LibraryFilters } from "../library/types";
import { ImportView } from "./ImportView";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
let root: Root;
let host: HTMLDivElement;
const job = {id:"batch",state:"preview",source:"J:\\DCIM",album_id:null,file_count:43,copy_count:43,
  ignored_count:1,counts:{image:20,raw:20,video:2,other:1},total_bytes:1234};
const filters = { albums:[{id:7,name:"Existing",category:"日常",capture_count:1,status:"confirmed"}],
  album_types:[{name:"日常",built_in:1}],cameras:[],lenses:[],tags:[],model_problems:[] } satisfies LibraryFilters;
const accept = vi.fn();
const button = (text:string) => [...host.querySelectorAll("button")].find(b=>b.textContent===text)!;
beforeEach(() => {
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});sessionStorage.clear();
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
  vi.mocked(getJson).mockImplementation(async url => {
    if(url.startsWith("/api/imports?"))return {items:[job],count:1} as never;
    return {...job,items:[{relative:"A.JPG",kind:"image",bytes:42}],ignored:["ignore.exe"]} as never;
  });
});
afterEach(async()=>{await act(()=>root.unmount());host.remove();vi.resetAllMocks();});
const render = (task:Partial<Task>={status:"idle"}) => act(()=>root.render(
  <ImportView filters={filters} task={task as Task} acceptTask={accept} openAlbum={vi.fn()}/>));

it("defaults to a new album, requires consent, and submits through the system API",async()=>{
  await render();
  expect((host.querySelector('input[type=radio]') as HTMLInputElement).checked).toBe(true);
  expect(button("复制并导入").disabled).toBe(true);
  const name=host.querySelector('input[maxlength="180"]')!;
  await act(()=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(name,"2026-10-01 · 回家");
    name.dispatchEvent(new Event("input",{bubbles:true}));
    (host.querySelector('input[type=checkbox]') as HTMLInputElement).click();
  });
  expect(button("复制并导入").disabled).toBe(false);
  await act(()=>button("复制并导入").click());
  expect(getJson).toHaveBeenCalledWith("/api/imports/batch/start",expect.objectContaining({method:"POST",
    body:JSON.stringify({confirmed:true,album_id:null,name:"2026-10-01 · 回家",category:"日常"})}));
  expect(accept).toHaveBeenCalledOnce();
});

it("does not open a native picker automatically and blocks new work while a task runs",async()=>{
  await render({id:"other",status:"running",stage:"scan",message:"scanning",current:0,total:1});
  expect(button("选择来源目录").disabled).toBe(true);
  expect(button("检查这批文件").disabled).toBe(true);
  expect(host.querySelector("fieldset")!.disabled).toBe(true);
  expect(getJson).not.toHaveBeenCalledWith("/api/system/directory-picker",expect.anything());
});

it("pages file manifests and shows unsupported files without silently importing them",async()=>{
  await render();
  expect(host.textContent).toContain("ignore.exe");
  const next=button("下一页");
  expect(next).toBeDefined();
  await act(()=>next.click());
  expect(getJson).toHaveBeenCalledWith("/api/imports/batch?offset=40&limit=40",expect.anything());
});

it("restores the source and album name draft after leaving and returning",async()=>{
  sessionStorage.setItem("import-source","J:\\DCIM\\101_FUJI");sessionStorage.setItem("import-name","Birthday");
  await render();
  expect((host.querySelector('input[maxlength="180"]') as HTMLInputElement).value).toBe("Birthday");
  expect((host.querySelector('input[placeholder^="例如 J:"]') as HTMLInputElement).value).toBe("J:\\DCIM\\101_FUJI");
  expect(button("复制并导入").disabled).toBe(true);
});

it("exposes a paused batch recovery action and readable failure",async()=>{
  vi.mocked(getJson).mockImplementation(async url => url.startsWith("/api/imports?")
    ? {items:[{...job,state:"copying",error:"存储卡已断开"}],count:1} as never
    : {...job,state:"copying",error:"存储卡已断开"} as never);
  await render({id:"batch",status:"paused",stage:"import-workflow"});
  expect(host.textContent).toContain("存储卡已断开");
  await act(()=>button("继续此批导入").click());
  expect(getJson).toHaveBeenCalledWith("/api/imports/batch/start",expect.objectContaining({method:"POST"}));
});
