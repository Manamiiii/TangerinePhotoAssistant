import { useEffect, useRef, useState } from "react";
import { getJson } from "../../api";
import { ModalShell } from "../../components/ModalShell";
import type { Task } from "../../components/TaskCard";
import { formatBytes } from "../../formatters";

type ArchivePlan = {
  id: string; album_id: number; album_name: string; target: string;
  status: "preview" | "pending" | "complete"; capture_count: number; total_bytes: number;
  error?: string | null;
  items: { source: string; target: string; bytes: number }[];
};

export function AlbumArchive({ albumId, task, onStarted }: {
  albumId: number; task: Task | null; onStarted: (task: Task) => void;
}) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<ArchivePlan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState<{ file_count: number; inbox_count: number; pending: boolean } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void getJson<{ file_count: number; inbox_count: number; pending: boolean }>(`/api/albums/${albumId}/archive/status`, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setStatus(value); })
      .catch(() => { if (!controller.signal.aborted) setStatus(null); });
    return () => controller.abort();
  }, [albumId, task?.id, task?.status]);
  const filed = status && !status.pending && status.file_count > 0 && status.inbox_count === 0;
  const blocked = !task || task.status === "running" || (task.status === "paused" && task.stage !== "album-archive");
  const preview = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setOpen(true); setPlan(null); setError(null); setConfirmation(""); setPage(0);
    try { setPlan(await getJson<ArchivePlan>(`/api/albums/${albumId}/archive/preview`, { method: "POST" })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取归档预览"); }
    finally { lock.current = false; setBusy(false); }
  };
  const execute = async () => {
    if (!plan || lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      onStarted(await getJson<Task>(`/api/albums/${albumId}/archive/execute`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: plan.id, confirmation }),
      }));
      setOpen(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "归档未启动，请重新预览核对"); }
    finally { lock.current = false; setBusy(false); }
  };
  return <div className={`album-archive-entry ${filed ? "is-filed" : "needs-filing"}`}>
    <div className="album-archive-copy"><strong>{filed ? "照片已在正式目录" : status?.pending ? "归档尚未完成" : "下一步：完成归档"}</strong><span>{filed ? "待整理源副本已清理或照片原本就在正式目录；可继续评分和选片" : status?.pending ? "请等待当前任务完成；中断后可从此处继续" : "入库完成后，在这里将待整理照片归入正式目录，并清理对应源副本"}</span></div>
    <button className={`toolbar-button ${filed ? "" : "primary"}`} disabled={blocked || busy || Boolean(filed)} onClick={() => void preview()}>
      {filed ? "已在正式目录" : status?.pending ? "继续归档" : "完成归档"}
    </button>
    {open && <ModalShell title="完成归档" close={() => { if (!busy) setOpen(false); }} wide>
      <div className="editor-form">
        {busy && <p role="status">正在处理，请稍候…</p>}
        {error && <p role="alert">{error}</p>}
        {plan && <>
          <p>{plan.capture_count} 张照片 · {plan.items.length} 个文件 · {formatBytes(plan.total_bytes)}</p>
          <p className="archive-target">正式目录：<strong>{plan.target}</strong></p>
          <p>先备份图库、复制并逐文件校验，再更新照片路径，最后清理已校验的待整理源文件。评分、标签和选片结果保留。不触及存储卡；无关文件留在原目录。</p>
          {plan.status === "pending" && <p role="status">上次归档尚未完成。继续会核对已有副本，从记录的状态恢复。</p>}
          {plan.error && <p role="alert">上次未完成原因：{plan.error}</p>}
          <details><summary>查看逐文件清单</summary>
            <ol className="archive-file-list" start={page * 40 + 1}>{plan.items.slice(page * 40, page * 40 + 40).map((item) => <li key={item.source}><span>{item.source}</span><span>→ {item.target}</span></li>)}</ol>
            <div className="archive-list-pages"><button disabled={!page} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.ceil(plan.items.length / 40)}</span><button disabled={(page + 1) * 40 >= plan.items.length} onClick={() => setPage(page + 1)}>下一页</button></div>
          </details>
          <label><span>确认后将清理对应待整理文件。请输入“归档 {plan.album_name}”</span><input value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></label>
        </>}
        <footer><button className="toolbar-button" disabled={busy} onClick={() => setOpen(false)}>返回</button><button className="toolbar-button" disabled={busy} onClick={() => void preview()}>重新预览</button>{plan && <button className="toolbar-button primary" disabled={busy || blocked || confirmation !== `归档 ${plan.album_name}`} onClick={() => void execute()}>{plan.status === "pending" ? "继续归档" : "确认归档"}</button>}</footer>
      </div>
    </ModalShell>}
  </div>;
}
