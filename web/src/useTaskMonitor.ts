import { useCallback, useEffect, useRef, useState } from "react";
import { getJson } from "./api";
import { taskForDisplay, taskReceipt, type Task } from "./components/TaskCard";
import { createTaskMonitor } from "./taskMonitor";

export function useTaskMonitor(refresh: () => void, reportError: (url: string, message: string | null) => void) {
  const [task, setTask] = useState<Task | null>(null);
  const monitor = useRef<ReturnType<typeof createTaskMonitor> | null>(null);
  useEffect(() => {
    const current = createTaskMonitor({
      read: (signal) => getJson<Task>("/api/tasks/current", { signal, cache: "no-store" }),
      visible: () => document.visibilityState === "visible",
      apply: (next) => setTask(taskForDisplay(next)),
      refresh,
      error: (message) => reportError("/api/tasks/current", message),
    });
    monitor.current = current;
    const sync = () => current.sync();
    const visibility = () => current.visibilityChanged();
    window.addEventListener("focus", sync);
    window.addEventListener("online", sync);
    document.addEventListener("visibilitychange", visibility);
    current.sync();
    return () => {
      current.stop();
      window.removeEventListener("focus", sync);
      window.removeEventListener("online", sync);
      document.removeEventListener("visibilitychange", visibility);
      reportError("/api/tasks/current", null);
    };
  }, [refresh, reportError]);
  useEffect(() => {
    if (!task || !["complete", "cancelled"].includes(task.status)) return;
    const receipt = taskReceipt(task);
    const timer = window.setTimeout(() => {
      window.localStorage.setItem("tangerine-task-receipt", receipt);
      setTask((current) => current && taskReceipt(current) === receipt
        ? { ...current, status: "idle", stage: "idle", message: "等待任务" } : current);
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [task?.id, task?.status]);
  const acceptTask = useCallback((next: Task) => monitor.current?.accept(next), []);
  const syncTask = useCallback(() => monitor.current?.sync(), []);
  return { task, acceptTask, syncTask };
}
