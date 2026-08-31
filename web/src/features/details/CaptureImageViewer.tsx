import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { changeZoom, fittedTransform, imageIsReady, previewUrl } from "./viewerState";

// The owner keys this component by photo identity. A cached onLoad must never be
// followed by an effect that resets loading=true for the same, already-ready img.
function PreviewImage({ url, alt, style }: { url: string; alt: string; style: CSSProperties }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const src = previewUrl(url, attempt);
  const imageRef = useCallback((image: HTMLImageElement | null) => {
    if (image && imageIsReady(image)) setStatus("ready");
  }, [src]);
  useEffect(() => {
    if (status !== "error" || attempt >= 2) return;
    const timer = window.setTimeout(() => {
      setStatus("loading");
      setAttempt((current) => current + 1);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [attempt, status]);
  const failed = status === "error" && attempt >= 2;
  return <>
    {status !== "ready" && <span className="detail-image-loading" role={failed ? "alert" : "status"}>
      {failed ? "照片预览加载失败" : "正在加载照片…"}
      {failed && <button onClick={() => { setAttempt((current) => current + 1); setStatus("loading"); }}>重试加载</button>}
    </span>}
    <img key={src} ref={imageRef} draggable={false} className={status === "ready" ? "" : "loading"}
      style={style} src={src} alt={alt} onLoad={() => setStatus("ready")} onError={() => setStatus("error")} />
  </>;
}

export function CaptureImageViewer({ url, name, immersive, paired, controls }: {
  url: string; name: string; immersive: boolean; paired: boolean;
  controls: ReactNode;
}) {
  const [transform, setTransform] = useState(fittedTransform);
  const container = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ pointerId: number; startX: number; startY: number; x: number; y: number } | null>(null);
  const releaseDrag = useCallback(() => {
    const pointer = drag.current?.pointerId;
    drag.current = null;
    if (pointer != null && container.current?.hasPointerCapture(pointer)) container.current.releasePointerCapture(pointer);
  }, []);
  const fit = useCallback(() => { releaseDrag(); setTransform(fittedTransform); }, [releaseDrag]);
  useEffect(fit, [immersive, fit]);
  useEffect(() => {
    const element = container.current;
    if (!element || !immersive) return;
    // React's delegated wheel listeners may be passive; bind locally so wheel
    // zoom cannot also scroll the page or emit preventDefault warnings.
    const wheel = (event: WheelEvent) => {
      if ((event.target as HTMLElement).closest("button, .detail-view-controls") || event.deltaY === 0) return;
      event.preventDefault();
      releaseDrag();
      setTransform((current) => changeZoom(current, event.deltaY < 0 ? .25 : -.25));
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [immersive, releaseDrag]);
  const zoom = (delta: number) => { releaseDrag(); setTransform((current) => changeZoom(current, delta)); };
  return <div ref={container} className={`detail-image ${transform.zoom > 1 ? "zoomed" : ""}`}
    onPointerDown={(event) => {
      if (transform.zoom <= 1 || event.button !== 0 || (event.target as HTMLElement).closest("button, .detail-view-controls")) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, x: transform.x, y: transform.y };
    }}
    onPointerMove={(event) => {
      const current = drag.current;
      if (!current || current.pointerId !== event.pointerId) return;
      setTransform((value) => ({ ...value, x: current.x + event.clientX - current.startX, y: current.y + event.clientY - current.startY }));
    }}
    onPointerUp={releaseDrag} onPointerCancel={releaseDrag} onLostPointerCapture={() => { drag.current = null; }}>
    <PreviewImage key={url} url={url} alt={`${name} 大图预览`} style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})` }} />
    {paired && <span className="raw-badge">JPG + RAW</span>}
    <div className="detail-view-controls">
      {immersive && <><button onClick={fit}>适应</button><button aria-label="缩小" disabled={transform.zoom <= 1} onClick={() => zoom(-.25)}>−</button>
        <span className="detail-zoom-value" aria-label="缩放比例">{Math.round(transform.zoom * 100)}%</span>
        <button aria-label="放大" disabled={transform.zoom >= 6} onClick={() => zoom(.25)}>＋</button></>}
      {controls}
    </div>
  </div>;
}
