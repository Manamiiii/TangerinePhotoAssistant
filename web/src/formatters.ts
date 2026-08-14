export const numberFormat = new Intl.NumberFormat("zh-CN");

const dateFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatBytes(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function formatFileSize(bytes: number) {
  return bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function formatDuration(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return "计算中";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "尚未完成";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value.replace("T", " ") : dateFormat.format(parsed);
}

export function formatExposure(value: number | null | undefined) {
  if (!value) return "—";
  return value < 1 ? `1/${Math.round(1 / value)}s` : `${value.toFixed(1)}s`;
}

export function technicalGrade(score: number | null | undefined) {
  if (score == null) return "—";
  if (score >= 85) return "A+";
  if (score >= 75) return "A";
  if (score >= 60) return "B";
  if (score >= 45) return "C";
  return "D";
}

export function technicalAdvice(code: string) {
  return ({
    slow_shutter_risk: "下次可提高快门速度、开启防抖或使用三脚架；先确认主体是否有运动。",
    high_iso: "优先增加环境光或使用更大光圈；降噪时注意保留纹理。",
    highlight_clipping: "Lightroom 可先降低高光和白色色阶；下次拍摄可适当负曝光补偿。",
    deep_shadows: "确认是否为有意剪影；需要恢复时先小幅提亮阴影并控制噪点。",
    low_global_detail: "放大检查主体焦点；下次提高快门或缩小一点光圈，避免只靠锐化补救。",
    jpeg_stream_recovered: "检查画面边缘是否完整，并从存储卡重新复制原文件进行比对。",
  } as Record<string, string>)[code] ?? "打开照片查看证据，再结合拍摄意图决定是否调整。";
}
