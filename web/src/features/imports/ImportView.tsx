import { useEffect, useRef, useState } from "react";
import { getJson } from "../../api";
import { Pagination } from "../../components/Navigation";
import { TaskCard, type Task } from "../../components/TaskCard";
import { formatBytes } from "../../formatters";
import { AlbumFiles } from "./AlbumFiles";
import { AlbumArchive } from "../library/AlbumArchive";
import type { LibraryFilters } from "../library/types";
import "./imports.css";

type ImportItem = { relative: string; kind: string; bytes: number; skip?: boolean; duplicate_path?: string };
type ImportJob = {
  id: string; state: string; source: string; destination?: string; album_id: number | null;
  in_place?: boolean;
  album_name?: string; file_count: number; copy_count: number; duplicate_count?: number;
  ignored_count: number; total_bytes?: number; counts: Record<string, number>;
  capture_count?: number; metadata_errors?: number; remaining_files?: number; error?: string;
  items?: ImportItem[]; ignored?: string[];
};
const labels: Record<string, string> = { checking: "检查来源中", preview: "等待确认", copying: "复制与校验", indexing: "入库中", ready: "已入库", check_failed: "检查未完成" };
const kindLabels: Record<string, string> = { image: "图片", raw: "RAW", video: "视频", other: "附属文件" };
const post = <T,>(url: string, body: object) => getJson<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function ImportView({ filters, task, acceptTask, openAlbum }: {
  filters: LibraryFilters | null; task: Task | null; acceptTask: (task: Task) => void; openAlbum: (id: number) => void;
}) {
  const [source, setSource] = useState(() => sessionStorage.getItem("import-source") ?? "");
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [count, setCount] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ImportJob | null>(null);
  const [offset, setOffset] = useState(0);
  const [target, setTarget] = useState("new");
  const [name, setName] = useState(() => sessionStorage.getItem("import-name") ?? "");
  const [category, setCategory] = useState("日常");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => { sessionStorage.setItem("import-source", source); }, [source]);
  useEffect(() => { sessionStorage.setItem("import-name", name); }, [name]);
  const lock = useRef(false);
  const active = !task || task.status === "running" || task?.status === "paused";
  const job = jobs.find((value) => value.id === selected);
  const step = !job || job.state === "check_failed" || job.state === "checking" ? 1 : job.state === "preview" ? 2 : job.state === "ready" ? 4 : 3;
  useEffect(() => {
    const controller = new AbortController();
    void getJson<{items: ImportJob[]; count: number}>(`/api/imports?limit=20&offset=${historyOffset}`, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) { setJobs(result.items); setCount(result.count); setSelected((previous) => previous ?? result.items[0]?.id ?? null); } })
      .catch((reason) => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, [task?.id, task?.status, historyOffset, revision]);
  useEffect(() => {
    setDetail(null);
    if (!selected) return;
    const controller = new AbortController();
    void getJson<ImportJob>(`/api/imports/${selected}?offset=${offset}&limit=40`, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setDetail(result); })
      .catch((reason) => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, [selected, offset, task?.status, revision]);
  const action = async (work: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try { await work(); } catch (reason) { setError(reason instanceof Error ? reason.message : "操作未完成，请重试"); }
    finally { lock.current = false; setBusy(false); setRevision((n) => n + 1); }
  };
  const check = () => action(async () => {
    const next = await post<Task>("/api/imports/check", {source: source.trim()});
    setSelected(next.id); setOffset(0); setHistoryOffset(0); setConfirmed(false); setTarget("new");
    acceptTask(next);
  });
  const start = () => action(async () => {
    if (!job) return;
    acceptTask(await post<Task>(`/api/imports/${job.id}/start`, { confirmed: true,
      album_id: target === "new" ? null : Number(target), name, category }));
    setHistoryOffset(0);
    setConfirmed(false);
  });
  const choose = () => action(async () => {
    const result = await post<{path?: string; cancelled: boolean}>("/api/system/directory-picker", {initial_path: source, title: "选择存储卡照片目录或待整理批次"});
    if (!result.cancelled && result.path) setSource(result.path);
  });
  return <div className="import-workspace">
    <section className="panel import-intro"><div><span className="section-kicker">从存储卡到正式相册</span><h2>导入新照片</h2><p>照片、RAW、视频和附属文件一起整理。存储卡原片保留，分析与选片由你另行启动。</p></div>
      <ol className="import-steps" aria-label="导入流程">{["选择来源", "核对与选相册", "复制校验并入库", "完成归档"].map((label, index) => <li key={label} aria-current={step === index + 1 ? "step" : undefined}>{index + 1} {label}</li>)}</ol>
    </section>
    {error && <div className="error-banner" role="alert">{error}<button onClick={() => {setError(null); setRevision((n) => n + 1);}}>重新读取</button></div>}
    <TaskCard task={task} />
    {task?.stage === "import-workflow" && task.status === "running" && !!task.bytes_total && <p role="status">已处理 {formatBytes(task.bytes_current)} / {formatBytes(task.bytes_total)}</p>}
    <section className="panel import-source"><h3>开始一次新导入</h3><p>选择一批照片所在的文件夹，包含子目录。无需先创建待整理文件夹；已经复制好的照片可直接选择待整理中的单个批次目录。</p>
      <form onSubmit={(event) => {event.preventDefault(); void check();}}>
        <label>来源目录<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="例如 J:\DCIM\101_FUJI" disabled={busy || active} /></label>
        <div className="import-actions"><button type="button" className="toolbar-button" disabled={busy || active} onClick={() => void choose()}>选择来源目录</button><button className="toolbar-button primary" disabled={busy || active || !source.trim()}>检查这批文件</button></div>
      </form><small>此步只读来源并检查重复，不复制文件。XMP、LRF 等只原样保存，不修改其内容。</small>
    </section>
    <section className="panel"><h3>导入批次与进度</h3><p>关闭页面不会停止后台任务。刷新后可以从这里查看结果或继续中断的导入。</p>
      {jobs.length === 0 && <p>还没有导入批次。请先选择来源目录。</p>}
      <div className="import-batches">{jobs.map((item) => <button key={item.id} aria-pressed={selected === item.id} onClick={() => { setSelected(item.id); setOffset(0); setConfirmed(false); }}><strong>{item.album_name ?? item.source}</strong><span>{item.state === "ready" && item.remaining_files === 0 ? "已归档" : labels[item.state] ?? item.state} · {item.file_count} 个文件</span></button>)}</div>
      <Pagination compact count={count} limit={20} offset={historyOffset} onChange={(value) => {setHistoryOffset(value);setSelected(null);setOffset(0);}} />
    </section>
    {job && <section className="panel import-detail" key={job.id}><h3>{job.album_name ?? "核对本批文件"}</h3><p className="import-path">来源：{job.source}</p>{job.destination && <p className="import-path">待整理目录：{job.destination}</p>}
      <div className="import-counts">{Object.entries(job.counts).map(([kind,n]) => <span key={kind}>{kindLabels[kind]} <strong>{n}</strong></span>)}<span>{formatBytes(job.total_bytes ?? 0)}</span></div>
      <p>完整重复的文件组跳过 {job.duplicate_count ?? 0} 个文件；本次处理 {job.copy_count} 个文件。JPG 与 RAW 同组有新增内容时整组保留，避免拆散配对。</p>
      {!!job.ignored_count && <p role="status">有 {job.ignored_count} 个不支持的文件不会复制，请展开清单核对。</p>}
      {job.error && <p role="alert">{job.error}</p>}
      {!!job.metadata_errors && <p role="status">{job.metadata_errors} 个文件未能解析拍摄参数，原文件已保留；可核对后归档。</p>}
      {job.state === "preview" && <form className="editor-form" onSubmit={(event) => {event.preventDefault(); void start();}}>
        <fieldset disabled={busy || active}><legend>新增内容放到哪个相册？</legend><div className="import-actions"><label><input type="radio" checked={target === "new"} onChange={() => setTarget("new")} />新建相册</label><label><input type="radio" checked={target !== "new"} disabled={!filters?.albums.length} onChange={() => setTarget(String(filters?.albums[0]?.id ?? ""))} />加入已有相册</label></div>
        {target === "new" ? <div className="import-album-fields"><label>相册名称<input required maxLength={180} value={name} placeholder="例如 2026-10-01 至 2026-10-03 · 国庆回老家" onChange={(e) => setName(e.target.value)} /></label><label>类型<select value={category} onChange={(e) => setCategory(e.target.value)}>{filters?.album_types.map((type) => <option key={type.name}>{type.name}</option>)}</select></label></div> : <label>已有相册<select value={target} onChange={(e) => setTarget(e.target.value)}>{filters?.albums.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}
        <label className="import-consent"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />{job.in_place ? "确认本批范围和相册；校验现有待整理文件并入库，正式归档时再清理这些副本" : "确认本批范围和相册；保留来源原片，复制校验后入库"}</label>
        <button className="toolbar-button primary" disabled={!confirmed || !job.copy_count || (target === "new" && !name.trim())}>{job.in_place ? "校验并入库" : "复制并导入"}</button></fieldset>
      </form>}
      {["checking", "copying", "indexing"].includes(job.state) && task?.status !== "running" && <button className="toolbar-button primary" disabled={busy || (active && task?.id !== job.id)} onClick={() => void start()}>继续此批导入</button>}
      {job.state === "ready" && job.album_id !== null && <><div className="import-actions"><button className="toolbar-button" onClick={() => openAlbum(job.album_id!)}>查看相册照片（{job.capture_count ?? 0} 张）</button><span>视频和附属文件不计入照片张数，归档时会一并处理。</span></div><AlbumArchive albumId={job.album_id} task={task} onStarted={acceptTask} /><AlbumFiles albumId={job.album_id} task={task} /></>}
      <details><summary>逐文件清单与跳过原因</summary>{!detail ? <p>正在读取清单…</p> : <><Pagination compact count={detail.file_count} limit={40} offset={offset} onChange={setOffset}/><ul className="import-files">{detail.items?.map((item) => <li key={item.relative}><span>{item.relative}</span><span>{kindLabels[item.kind]} · {formatBytes(item.bytes)} · {item.skip ? "已入库完整重复组，跳过" : "本次处理"}</span></li>)}</ul><Pagination compact count={detail.file_count} limit={40} offset={offset} onChange={setOffset}/>{!!detail.ignored?.length && <p>未复制（最多展示 100 条）：{detail.ignored.join("、")}</p>}</>}</details>
    </section>}
  </div>;
}
