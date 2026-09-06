import { useCallback, useEffect, useState } from "react";
import { imageIsReady, previewUrl } from "./viewerState";

/** Keyed by source URL by the caller so stale image events cannot update a new preview. */
export function EditPreviewImage({ url, name, pending }: { url: string; name: string; pending: boolean }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const src = previewUrl(url, attempt);
  const ref = useCallback((image: HTMLImageElement | null) => {
    if (image && imageIsReady(image)) setStatus("ready");
  }, [src]);
  useEffect(() => {
    if (status !== "loading") return;
    const timer = window.setTimeout(() => setStatus("error"), 15_000);
    return () => window.clearTimeout(timer);
  }, [status, attempt]);
  return <>
    <img key={src} ref={ref} src={src} alt={`${name} 参数预览`}
      onLoad={() => setStatus("ready")} onError={() => setStatus("error")} />
    {status === "error" ? <span className="edit-preview-error" role="alert">预览加载失败，参数已保留。
      <button onClick={() => { setAttempt((current) => current + 1); setStatus("loading"); }}>重试预览</button>
    </span> : (pending || status === "loading") && <span className="edit-preview-loading" role="status">正在更新预览…</span>}
  </>;
}
