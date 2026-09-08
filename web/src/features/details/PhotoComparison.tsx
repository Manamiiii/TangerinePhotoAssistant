import { useCallback, useEffect, useRef, useState } from "react";
import { imageIsReady, previewUrl } from "./viewerState";

export type ComparePhoto = { id: number; stem?: string; album_name?: string | null };
export type CompareTransform = { zoom: number; x: number; y: number };
export const comparisonFit: CompareTransform = { zoom: 1, x: 0, y: 0 };
export function clampComparison(value: CompareTransform): CompareTransform {
  const zoom = Math.max(1, Math.min(6, value.zoom));
  const bound = (zoom - 1) / 2;
  return { zoom, x: Math.max(-bound, Math.min(bound, value.x)), y: Math.max(-bound, Math.min(bound, value.y)) };
}

function CompareImage({ photo, transform }: { photo: ComparePhoto; transform: CompareTransform }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const src = previewUrl(`/api/thumbnails/${photo.id}?size=1280`, attempt);
  const ref = useCallback((image: HTMLImageElement | null) => { if (image && imageIsReady(image)) setStatus("ready"); }, [src]);
  useEffect(() => {
    if (status !== "loading") return;
    const timer = window.setTimeout(() => setStatus("error"), 15_000);
    return () => window.clearTimeout(timer);
  }, [status, attempt]);
  return <>
    <img key={src} ref={ref} src={src} draggable={false} alt={photo.stem ?? `照片 ${photo.id}`}
      style={{ transform: `translate(${transform.x * 100}%, ${transform.y * 100}%) scale(${transform.zoom})` }}
      onLoad={() => setStatus("ready")} onError={() => setStatus("error")} />
    {status !== "ready" && <div className="comparison-image-notice" role={status === "error" ? "alert" : "status"}>
      {status === "error" ? "预览不可用" : "正在加载预览…"}
      {status === "error" && <button onClick={() => { setAttempt((value) => value + 1); setStatus("loading"); }}>重试这张</button>}
    </div>}
  </>;
}

export function PhotoComparison({ photos, back, backLabel = "返回已选清单" }: { photos: [ComparePhoto, ComparePhoto]; back: () => void; backLabel?: string }) {
  const [layout, setLayout] = useState<"side" | "stack" | "single">("side");
  const [active, setActive] = useState(0);
  const [transform, setTransform] = useState(comparisonFit);
  const backButton = useRef<HTMLButtonElement>(null);
  useEffect(() => backButton.current?.focus(), []);
  const surface = useRef<HTMLDivElement>(null);
  const drag = useRef<{ element: HTMLDivElement; pointer: number; startX: number; startY: number; width: number; height: number; x: number; y: number } | null>(null);
  const release = useCallback(() => {
    const current = drag.current; drag.current = null;
    if (current?.element.hasPointerCapture(current.pointer)) current.element.releasePointerCapture(current.pointer);
  }, []);
  const zoom = useCallback((delta: number) => { release(); setTransform((value) => clampComparison({ ...value, zoom: value.zoom + delta })); }, [release]);
  useEffect(() => {
    const element = surface.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || !event.deltaY || (event.target as HTMLElement).closest("button")) return;
      event.preventDefault(); zoom(event.deltaY < 0 ? .25 : -.25);
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => { element.removeEventListener("wheel", wheel); release(); };
  }, [zoom, release]);
  const changeLayout = (next: typeof layout) => { release(); setTransform(comparisonFit); setLayout(next); };
  return <div className={`photo-comparison layout-${layout}`}>
    <div className="comparison-toolbar"><button ref={backButton} onClick={back}>{backLabel}</button><button onClick={() => { release(); setTransform(comparisonFit); }}>适应窗口</button>
      <button aria-label="同步缩小" disabled={transform.zoom <= 1} onClick={() => zoom(-.25)}>−</button><span>适应尺寸 × {transform.zoom.toFixed(2)}</span><button aria-label="同步放大" disabled={transform.zoom >= 6} onClick={() => zoom(.25)}>＋</button></div>
    <div className="comparison-layout-toolbar"><div className="section-tabs comparison-layout-options" role="group" aria-label="对比布局">{([['side', '左右并排'], ['stack', '上下排列'], ['single', '单图切换']] as const).map(([value, label]) => <button key={value} className={layout === value ? "active" : ""} aria-pressed={layout === value} onClick={() => changeLayout(value)}>{label}</button>)}</div>{layout === "single" && <div className="section-tabs comparison-photo-options" role="group" aria-label="当前对比照片">{photos.map((photo, index) => <button key={photo.id} className={active === index ? "active" : ""} aria-pressed={active === index} onClick={() => { release(); setActive(index); }}>{index === 0 ? "A" : "B"} · {photo.stem ?? photo.id}</button>)}</div>}</div>
    <p>两张同步缩放与移动；放大后拖动，或聚焦图片后用方向键移动。使用最长边 1280px 的 JPG 预览，非原片像素级对比；不同构图不会自动对齐主体。</p>
    <div ref={surface} className="photo-comparison-panes">{photos.map((photo, index) => <section key={photo.id} hidden={layout === "single" && index !== active}>
      <header><strong>{photo.stem ?? `照片 ${photo.id}`}</strong><small>{photo.album_name ?? "未归入相册"}</small></header>
      <div className="photo-comparison-image" tabIndex={0} aria-label={`${photo.stem ?? photo.id} 对比预览，方向键同步移动`}
        onKeyDown={(event) => {
          if (event.ctrlKey || event.altKey || event.metaKey || event.target !== event.currentTarget) return;
          const moves: Record<string, [number, number]> = { ArrowLeft: [-.05, 0], ArrowRight: [.05, 0], ArrowUp: [0, -.05], ArrowDown: [0, .05] };
          const delta = moves[event.key]; if (!delta) return;
          event.preventDefault(); release(); setTransform((value) => clampComparison({ ...value, x: value.x + delta[0], y: value.y + delta[1] }));
        }}
        onPointerDown={(event) => {
          if (drag.current || transform.zoom <= 1 || event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
          const rect = event.currentTarget.getBoundingClientRect(); if (!rect.width || !rect.height) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = { element: event.currentTarget, pointer: event.pointerId, startX: event.clientX, startY: event.clientY, width: rect.width, height: rect.height, x: transform.x, y: transform.y };
        }}
        onPointerMove={(event) => {
          const current = drag.current; if (!current || current.pointer !== event.pointerId) return;
          setTransform((value) => clampComparison({ ...value, x: current.x + (event.clientX - current.startX) / current.width, y: current.y + (event.clientY - current.startY) / current.height }));
        }} onPointerUp={release} onPointerCancel={release} onLostPointerCapture={() => { drag.current = null; }}>
        <CompareImage photo={photo} transform={transform} />
      </div>
    </section>)}</div>
  </div>;
}
