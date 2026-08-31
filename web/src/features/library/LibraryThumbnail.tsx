import { useEffect, useRef, useState } from "react";
import { scheduleThumbnail } from "./thumbnailQueue";

export function LibraryThumbnail({ src, alt }: { src: string; alt: string }) {
  const element = useRef<HTMLSpanElement>(null);
  const [loaded, setLoaded] = useState<{ source: string; url: string } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let started = false;
    setLoaded(null);
    setFailed(false);
    const load = () => {
      if (started || controller.signal.aborted) return;
      started = true;
      void scheduleThumbnail(async (signal) => {
        const response = await fetch(src, { signal });
        if (!response.ok) throw new Error(`Thumbnail ${response.status}`);
        return response.blob();
      }, controller.signal).then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({ source: src, url: objectUrl });
      }).catch((error: Error) => {
        if (!controller.signal.aborted && error.name !== "AbortError") setFailed(true);
      });
    };
    // Unlike native lazy loading's large look-ahead, enqueue only visible or
    // nearly visible cards. Unmounting a page cancels both queued and active work.
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) { load(); observer?.disconnect(); }
    }, { rootMargin: "160px" });
    if (observer && element.current) observer.observe(element.current); else load();
    return () => {
      observer?.disconnect();
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);
  return <span className="library-thumbnail" ref={element}>
    {loaded?.source === src ? <img src={loaded.url} decoding="async" alt={alt} onError={() => { setLoaded(null); setFailed(true); }} /> : <span className="library-thumbnail-status" role="img" aria-label={alt}>{failed ? "缩略图不可用 · 点击查看" : "加载中…"}</span>}
  </span>;
}
