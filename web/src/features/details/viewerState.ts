export type ViewerTransform = { zoom: number; x: number; y: number };
export const fittedTransform: ViewerTransform = { zoom: 1, x: 0, y: 0 };

export function changeZoom(current: ViewerTransform, delta: number): ViewerTransform {
  const zoom = Math.max(1, Math.min(6, current.zoom + delta));
  return zoom === 1 ? { ...fittedTransform } : { ...current, zoom };
}

export function previewUrl(url: string, attempt: number): string {
  return attempt === 0 ? url : `${url}${url.includes("?") ? "&" : "?"}retry=${attempt}`;
}

export function imageIsReady(image: Pick<HTMLImageElement, "complete" | "naturalWidth">): boolean {
  return image.complete && image.naturalWidth > 0;
}

export async function toggleFullscreen(element: Pick<HTMLElement, "requestFullscreen"> | null,
  fullscreenDocument: Pick<Document, "fullscreenElement" | "exitFullscreen" | "fullscreenEnabled"> = document): Promise<void> {
  if (element && fullscreenDocument.fullscreenElement === element) {
    await fullscreenDocument.exitFullscreen();
  } else {
    if (!element?.requestFullscreen || fullscreenDocument.fullscreenEnabled === false) {
      throw new Error("当前浏览器不支持页面全屏，请使用沉浸查看。");
    }
    await element.requestFullscreen();
  }
}
