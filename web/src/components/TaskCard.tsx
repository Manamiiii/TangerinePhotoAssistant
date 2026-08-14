import { useEffect, useState } from "react";
import { formatDuration, numberFormat } from "../formatters";

export type Task = {
  id: string | null;
  status: "idle" | "running" | "paused" | "complete" | "failed" | "cancelled";
  stage: string;
  message: string;
  current: number;
  total: number | null;
  error: string | null;
  bytes_current: number;
  bytes_total: number | null;
  speed_bytes_per_second: number | null;
  items_per_second: number | null;
  eta_seconds: number | null;
  failure_count: number;
  pausable: boolean;
  result: { scan_run_id?: number; album_id?: number; assigned_count?: number } | null;
};

export function taskReceipt(task: Task) {
  return `${task.id ?? "none"}:${task.status}`;
}

export function taskForDisplay(task: Task) {
  if (!["complete", "cancelled"].includes(task.status)) return task;
  return window.localStorage.getItem("tangerine-task-receipt") === taskReceipt(task)
    ? { ...task, status: "idle" as const, stage: "idle" }
    : task;
}

export function TaskCard({ task, cancel, pause }: {
  task: Task | null;
  cancel?: () => void;
  pause?: () => void;
}) {
  const taskSignature = `${task?.id ?? "idle"}:${task?.status ?? "idle"}:${task?.message ?? ""}`;
  const [dismissed, setDismissed] = useState(false);
  const dismiss = () => {
    if (task && ["complete", "cancelled"].includes(task.status)) {
      window.localStorage.setItem("tangerine-task-receipt", taskReceipt(task));
    }
    setDismissed(true);
  };
  useEffect(() => {
    setDismissed(false);
    if (task?.status !== "complete" && task?.status !== "cancelled") return;
    const timer = window.setTimeout(dismiss, 8000);
    return () => window.clearTimeout(timer);
  }, [taskSignature, task?.status]);
  if (!task || task.status === "idle" || dismissed) return null;
  const progress = task.total ? Math.min(100, (task.current / task.total) * 100) : null;
  const itemProgress = task.total
    ? `${numberFormat.format(task.current)} / ${numberFormat.format(task.total)}`
    : null;
  const itemSpeed = task.items_per_second
    ? `${(task.items_per_second * 60).toFixed(1)} 张/分钟`
    : null;
  const detail = task.error ?? (
    [
      itemProgress,
      itemSpeed,
      task.eta_seconds != null ? `预计剩余 ${formatDuration(task.eta_seconds)}` : null,
    ].filter(Boolean).join(" · ") || "所有操作都在本机完成"
  );
  return <section className={`task-card ${task.status}`} aria-live="polite">
    <div>
      <span className="task-icon">
        {task.status === "complete" ? "✓" : task.status === "failed" ? "!" : "↻"}
      </span>
      <div><strong>{task.message}</strong><small>{detail}</small></div>
    </div>
    {task.status === "running" && <div className="task-actions">
      <div className="progress-track"><span style={{ width: `${progress ?? 22}%` }} className={progress === null ? "indeterminate" : ""} /></div>
      {pause && task.pausable && <button onClick={pause}>安全暂停</button>}
      {cancel && <button onClick={cancel}>安全取消</button>}
    </div>}
    {task.status === "paused" && cancel && <div className="task-actions">
      <div className="progress-track"><span style={{ width: `${progress ?? 0}%` }} /></div>
      <button onClick={cancel}>取消剩余任务</button>
    </div>}
    {["complete", "failed", "cancelled"].includes(task.status) && <button className="task-dismiss" onClick={dismiss} aria-label="关闭任务结果">×</button>}
  </section>;
}
