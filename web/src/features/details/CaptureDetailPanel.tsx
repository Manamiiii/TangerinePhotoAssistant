import { useEffect, useRef, useState } from "react";
import { formatDate, formatExposure, formatFileSize } from "../../formatters";
import type { ReviewPayload } from "../analysis/types";
import type { CaptureDetail, CaptureTagDimension } from "./types";

const tagDimensionLabels: Record<CaptureTagDimension, string> = {
  subject: "题材",
  status: "工作状态",
  problem: "人工问题",
  location: "地点",
};

function ReviewHelp() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [open]);
  return <span ref={rootRef} className="review-help"><button type="button" aria-label="解释评价规则" aria-expanded={open} onClick={() => setOpen((current) => !current)}>?</button>{open && <span className="review-help-popover" role="note"><span><strong>人工评价怎么分工</strong><button type="button" aria-label="关闭评价说明" onClick={() => setOpen(false)}>×</button></span><b>星级</b><small>表示你对照片长期价值的判断：1 星明显较弱，2 星有记录价值，3 星合格，4 星优秀，5 星代表作。</small><b>入选 / 排除</b><small>表示本轮选片结论，与星级独立；入选和排除互斥，排除只做标记，不删除照片。</small><b>工作状态</b><small>只表示待复核、待修、已修、待导出等流程阶段，不代替星级或选片结论。</small></span>}</span>;
}

function TagEditor({ detail, saveTags }: {
  detail: CaptureDetail;
  saveTags: (captureId: number, tags: Array<{ dimension: CaptureTagDimension; name: string }>) => Promise<void>;
}) {
  const manualTags = detail.tags.filter((tag) => tag.source === "manual");
  const [selected, setSelected] = useState<Array<{ dimension: CaptureTagDimension; name: string }>>(
    manualTags.map(({ dimension, name }) => ({ dimension, name })),
  );
  const [customDimension, setCustomDimension] = useState<CaptureTagDimension>("subject");
  const [customName, setCustomName] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => setSelected(
    detail.tags.filter((tag) => tag.source === "manual").map(({ dimension, name }) => ({ dimension, name })),
  ), [detail.id, detail.tags]);
  const selectedKey = (dimension: CaptureTagDimension, name: string) => `${dimension}:${name.toLocaleLowerCase()}`;
  const selectedKeys = new Set(selected.map((tag) => selectedKey(tag.dimension, tag.name)));
  const toggle = (dimension: CaptureTagDimension, name: string) => setSelected((current) => {
    const key = selectedKey(dimension, name);
    if (current.some((tag) => selectedKey(tag.dimension, tag.name) === key)) {
      return current.filter((tag) => selectedKey(tag.dimension, tag.name) !== key);
    }
    const withoutOldStatus = dimension === "status" ? current.filter((tag) => tag.dimension !== "status") : current;
    return [...withoutOldStatus, { dimension, name }];
  });
  const addCustom = () => {
    const name = customName.trim().replace(/\s+/g, " ");
    if (!name) return;
    if (!selectedKeys.has(selectedKey(customDimension, name))) toggle(customDimension, name);
    setCustomName("");
  };
  const dirty = JSON.stringify(selected.map((tag) => selectedKey(tag.dimension, tag.name)).sort()) !==
    JSON.stringify(manualTags.map((tag) => selectedKey(tag.dimension, tag.name)).sort());
  return <details className="detail-section detail-tags"><summary><span><strong>标签与流程</strong><small>{manualTags.length ? manualTags.map((tag) => tag.name).join(" · ") : "尚未设置人工标签"}</small></span><em>编辑</em></summary><div className="tag-editor-body"><div className="detail-section-heading"><p>题材和问题可以多选；工作状态只保留一个，并且不代替星级或选片结论。标签附着在 JPG+RAW 拍摄单元上，不写入照片。</p><button disabled={!dirty || saving} onClick={async () => { setSaving(true); try { await saveTags(detail.id, selected); } finally { setSaving(false); } }}>{saving ? "保存中…" : "保存标签"}</button></div>
    {(Object.keys(tagDimensionLabels) as CaptureTagDimension[]).map((dimension) => {
      const catalog = detail.tag_catalog.filter((tag) => tag.dimension === dimension);
      const selectedCustom = selected.filter((tag) => tag.dimension === dimension && !catalog.some((item) => item.name === tag.name));
      return <div className="tag-dimension" key={dimension}><strong>{tagDimensionLabels[dimension]}</strong><div>{[...catalog, ...selectedCustom.map((tag, index) => ({ ...tag, id: -index - 1, built_in: 0 }))].map((tag) => <button key={`${dimension}:${tag.name}`} className={selectedKeys.has(selectedKey(dimension, tag.name)) ? "selected" : ""} onClick={() => toggle(dimension, tag.name)}>{tag.name}</button>)}{!catalog.length && !selectedCustom.length && <small>尚无标签，可在下方添加</small>}</div></div>;
    })}
    <div className="tag-custom"><select value={customDimension} onChange={(event) => setCustomDimension(event.target.value as CaptureTagDimension)}>{(Object.entries(tagDimensionLabels) as Array<[CaptureTagDimension, string]>).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={customName} maxLength={40} placeholder="添加自定义标签" onChange={(event) => setCustomName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCustom(); } }} /><button disabled={!customName.trim()} onClick={addCustom}>添加</button></div>
  </div></details>;
}

function LuminanceHistogram({ histogram, shadowClip, highlightClip }: {
  histogram: number[];
  shadowClip: number | null;
  highlightClip: number | null;
}) {
  const width = 256;
  const height = 72;
  const max = Math.max(1, ...histogram);
  const barWidth = width / histogram.length;
  return (
    <div className="detail-histogram">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="亮度直方图">
        <rect x="0" y="0" width={barWidth * 2} height={height} className="histogram-clip-zone" />
        <rect x={width - barWidth * 2} y="0" width={barWidth * 2} height={height} className="histogram-clip-zone" />
        {histogram.map((value, index) => {
          const barHeight = Math.max(value > 0 ? 1 : 0, (value / max) * height);
          return <rect key={index} x={index * barWidth} y={height - barHeight} width={Math.max(0.5, barWidth - 0.6)} height={barHeight} className="histogram-bar" />;
        })}
      </svg>
      <small>基于 JPG 亮度，不代表 RAW 动态余量 · 暗部剪切 {shadowClip == null ? "—" : `${shadowClip.toFixed(1)}%`} · 高光剪切 {highlightClip == null ? "—" : `${highlightClip.toFixed(1)}%`}</small>
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score: number | null }) {
  return (
    <div className="score-bar">
      <span>{label}</span>
      <div className="score-bar-track"><i style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} className={score != null && score < 60 ? "low" : ""} /></div>
      <b>{score == null ? "—" : Math.round(score)}</b>
    </div>
  );
}

type ParameterHelpEntry = { title: string; meaning: string; options: Array<readonly [string, string]>; note?: string };
const parameterHelp = {
  shutter: { title: "快门速度", meaning: "控制曝光持续时间。它是连续数值，不存在有限的全部选项。", options: [["1/1000 秒及更快", "凝固运动、飞鸟和体育"], ["1/125–1/500 秒", "一般手持和日常动作"], ["1/30–1/100 秒", "静止主体可尝试手持，需留意防抖和焦距"], ["1 秒及更慢", "记录流水、车轨等运动，通常需要支撑"], ["Bulb / Time", "由摄影者控制超长曝光时长"]] },
  aperture: { title: "光圈", meaning: "控制进光量和景深，是由镜头决定范围的连续档位。f 数越小，光圈越大。", options: [["f/1.0–f/2.0", "大进光量、浅景深"], ["f/2.8–f/4", "主体分离与清晰范围的平衡"], ["f/5.6–f/8", "常见最佳画质区间"], ["f/11–f/22", "扩大景深，但过小可能出现衍射"]] },
  iso: { title: "ISO 感光度", meaning: "表示传感器信号增益，是连续档位；提高 ISO 通常会增加噪点并降低动态范围。", options: [["原生低 ISO", "通常有最佳画质和动态范围"], ["自动 ISO", "相机按快门下限等规则自动选择"], ["高 ISO", "弱光下换取快门速度"], ["扩展 ISO（L/H）", "机内推拉值，画质或高光余量可能受限"]] },
  focal: { title: "焦距", meaning: "影响视角和画面透视呈现，是镜头提供的连续或固定数值。", options: [["24mm 以下（等效）", "超广角"], ["24–35mm", "广角"], ["40–60mm", "标准视角"], ["70–200mm", "中长焦到长焦"], ["200mm 以上", "超长焦"]] },
  compensation: { title: "曝光补偿", meaning: "在自动测光结果上主动增亮或压暗，是连续档位。", options: [["0 EV", "采用相机测光结果"], ["正补偿", "整体增亮，常用于雪景或逆光人物"], ["负补偿", "整体压暗，常用于保护高光"], ["自动包围曝光", "连续拍摄不同补偿值以便选择或合成"]] },
  film: { title: "胶片模拟", meaning: "相机对 JPG 色彩、对比度和色调的预设，不等同于 RAW 的全部可调空间。", options: [["Provia / Standard", "自然、通用"], ["Velvia / Vivid", "高饱和、高反差，常用于风景"], ["Astia / Soft", "较柔和的人像色调"], ["Classic Chrome", "低饱和、纪实感"], ["Classic Neg.", "较强色彩层次和负片感"], ["Nostalgic Neg.", "暖高光与柔和怀旧色调"], ["ETERNA / Cinema", "低反差、电影感"], ["ETERNA Bleach Bypass", "低饱和、高反差"], ["Acros / Monochrome", "黑白；可带黄/红/绿滤镜"], ["Sepia", "棕褐色单色"]], note: "胶片模拟是厂商专有枚举；此处列出当前图库富士设备的常见全集，新机型可能增加选项。" },
  program: { title: "曝光程序与模式", meaning: "决定快门、光圈和 ISO 中哪些由摄影者控制。", options: [["Auto / 全自动", "相机决定主要曝光参数"], ["P / Program AE", "相机组合快门与光圈，可程序偏移"], ["A / Av", "摄影者设光圈，相机决定快门"], ["S / Tv", "摄影者设快门，相机决定光圈"], ["M / Manual", "摄影者设快门和光圈"], ["Bulb / Time", "超长曝光"], ["Scene / 场景模式", "针对人像、运动、夜景等的自动策略"]] },
  shutterType: { title: "快门类型", meaning: "不同快门的静音、最高速度、闪光同步和运动畸变特性不同。", options: [["机械快门（Mechanical Shutter）", "实体帘幕曝光；闪光兼容好，运动畸变较少，但有声音和机械震动"], ["电子前帘（Electronic Front Curtain / EFCS）", "电子开始、机械结束；震动较小，但高速大光圈可能影响焦外或曝光均匀"], ["电子快门（Electronic Shutter）", "完全静音、可达更高速度；快速运动可能滚动变形，频闪灯下可能有条纹"], ["机械 + 电子（Mechanical + Electronic）", "相机按速度或条件自动切换"], ["电子前帘 + 机械", "相机在 EFCS 和机械之间自动切换"], ["自动（Auto）", "由机身根据当前功能选择"]], note: "部分机型还提供全局快门或特殊高速模式；实际选项以相机型号为准。" },
  metering: { title: "测光模式", meaning: "决定相机用画面哪些区域估算曝光。", options: [["多区 / 评价（Multi-segment / Evaluative）", "综合全画面与主体信息，最通用"], ["中央重点（Center-weighted）", "全画面测光但提高中央区域权重"], ["点测光（Spot）", "只测很小区域，适合精确控制主体亮度"], ["局部测光（Partial）", "测量中央较小区域，范围大于点测光"], ["平均测光（Average）", "平均考虑整个画面"], ["高光重点（Highlight-weighted）", "优先避免亮部过曝"]] },
  whiteBalance: { title: "白平衡", meaning: "校正不同光源的色温和色偏，也可用于创造冷暖氛围。", options: [["自动（Auto / AWB）", "相机判断中性色；部分机型可选保留白色或保留暖色"], ["日光（Daylight）", "晴天日光"], ["阴影（Shade）", "增加暖色以修正阴影偏蓝"], ["阴天（Cloudy）", "比日光略暖"], ["钨丝灯（Tungsten）", "修正暖色白炽灯"], ["荧光灯（Fluorescent）", "修正不同类型荧光灯偏色"], ["闪光灯（Flash）", "匹配机顶闪光灯"], ["色温 K 值", "直接指定色温"], ["自定义 / Custom", "使用灰卡或已测量白点"]] },
  focus: { title: "对焦模式", meaning: "决定相机锁定一次焦点，还是持续跟随主体变化。", options: [["AF-S / Single", "半按后锁定，适合静止主体"], ["AF-C / Continuous", "持续更新焦点，适合运动主体"], ["AF-A / Automatic", "相机在单次和连续之间判断"], ["MF / Manual", "手动对焦"], ["DMF", "自动对焦后允许手动微调"]] },
  afArea: { title: "AF 区域", meaning: "决定相机可从多大范围内选择对焦点。", options: [["单点 / Single Point", "精确指定一个对焦点"], ["区域 / Zone", "在一组对焦点内识别主体"], ["宽域 / Wide", "相机在大范围内自动选择"], ["全域 / All", "使用整个对焦覆盖区"], ["追踪 / Tracking", "识别并持续跟随指定主体"], ["人脸 / 眼睛识别", "优先人物面部或眼睛"], ["动物 / 鸟类 / 交通工具识别", "机型支持的专用主体识别"]] },
  stabilization: { title: "防抖", meaning: "补偿手持抖动，不能冻结主体自身运动。", options: [["关闭（Off）", "不进行光学或传感器补偿"], ["持续（Continuous / Mode 1）", "持续稳定取景与曝光"], ["仅拍摄时（Shooting Only）", "曝光前后启用，较省电"], ["摇摄（Panning / Mode 2）", "保留一个方向的主动移动"], ["机身防抖（IBIS）", "移动传感器补偿"], ["镜头防抖（OIS / VR / OSS）", "移动镜片组补偿"], ["协同防抖", "机身和镜头配合"]] },
  dynamicRange: { title: "动态范围设置", meaning: "通过曝光和 JPG 曲线保护高光或抬升阴影，主要影响机内 JPG。", options: [["DR100", "标准基准，不额外压缩高光"], ["DR200", "约增加 1 档高光保护，通常要求较高最低 ISO"], ["DR400", "约增加 2 档高光保护，最低 ISO 要求更高"], ["Auto DR", "相机根据场景选择 DR100/200/400"], ["D-Range Priority", "综合调整高光与阴影曲线；部分配方参数会被限制"]], note: "其他品牌可能称 Active D-Lighting、DRO、Highlight Tone Priority 等，机制并不完全相同。" },
} satisfies Record<string, ParameterHelpEntry>;

function ParameterHelp({ kind }: { kind: keyof typeof parameterHelp }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const help: ParameterHelpEntry = parameterHelp[kind];
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [open]);
  return <span ref={rootRef} className="parameter-help">
    <button type="button" aria-label={`解释${help.title}`} aria-expanded={open} onClick={() => setOpen((current) => !current)}>?</button>
    {open && <span className="parameter-help-popover" role="note"><span className="parameter-help-heading"><strong>{help.title}</strong><button type="button" aria-label="关闭解释" onClick={() => setOpen(false)}>×</button></span><span>{help.meaning}</span><b>可能的选项与含义</b><span className="parameter-help-options">{help.options.map(([value, meaning]) => <span key={value}><strong>{value}</strong><small>{meaning}</small></span>)}</span>{help.note && <em>{help.note}</em>}</span>}
  </span>;
}

const metadataValueTranslations: Record<string, string> = {
  "auto": "自动", "automatic": "自动", "manual": "手动", "normal": "标准", "standard": "标准",
  "on": "开启", "off": "关闭", "yes": "是", "no": "否", "none": "无", "unknown": "未知",
  "mechanical": "机械快门", "mechanical shutter": "机械快门", "electronic": "电子快门", "electronic shutter": "电子快门",
  "electronic front curtain": "电子前帘", "electronic front curtain shutter": "电子前帘",
  "mechanical + electronic": "机械 + 电子自动切换", "mechanical + electronic shutter": "机械 + 电子自动切换",
  "program ae": "程序自动曝光（P）", "aperture-priority ae": "光圈优先（A/Av）", "aperture priority": "光圈优先（A/Av）",
  "shutter speed priority ae": "快门优先（S/Tv）", "shutter-priority ae": "快门优先（S/Tv）", "manual exposure": "手动曝光（M）",
  "multi-segment": "多区测光", "multi-zone": "多区测光", "evaluative": "评价测光", "center-weighted average": "中央重点平均测光",
  "center-weighted": "中央重点测光", "spot": "点测光", "partial": "局部测光", "average": "平均测光", "highlight-weighted": "高光重点测光",
  "daylight": "日光", "shade": "阴影", "cloudy": "阴天", "tungsten": "钨丝灯", "incandescent": "白炽灯",
  "fluorescent": "荧光灯", "flash": "闪光灯", "custom": "自定义", "auto white priority": "自动（白色优先）", "auto ambiance priority": "自动（氛围优先）",
  "single": "单次", "single af": "单次自动对焦（AF-S）", "continuous": "连续", "continuous af": "连续自动对焦（AF-C）",
  "manual focus": "手动对焦（MF）", "af-s": "单次自动对焦（AF-S）", "af-c": "连续自动对焦（AF-C）", "af-a": "自动切换对焦（AF-A）",
  "single point": "单点", "single-point": "单点", "zone": "区域", "wide": "宽域", "wide/tracking": "宽域 / 追踪", "tracking": "追踪", "all": "全域",
  "continuous, mode 1": "持续防抖（模式 1）", "shooting only": "仅拍摄时防抖", "panning": "摇摄防抖",
  "sr+": "智能场景识别自动", "fine": "精细", "fine jpeg": "精细 JPEG", "raw + jpeg": "RAW + JPEG",
  "uncompressed": "未压缩", "lossless compressed": "无损压缩", "compressed": "有损压缩",
  "srgb": "sRGB", "adobe rgb": "Adobe RGB", "horizontal (normal)": "横向（正常）",
  "rotate 90 cw": "顺时针旋转 90°", "rotate 270 cw": "顺时针旋转 270°", "high": "高", "low": "低", "strong": "强", "weak": "弱",
  "provia/standard": "Provia / 标准", "velvia/vivid": "Velvia / 鲜艳", "astia/soft": "Astia / 柔和",
  "f0/standard (provia)": "Provia / 标准", "f1/studio portrait": "Studio Portrait / 棚拍人像", "f2/fujichrome": "Fujichrome / 鲜艳",
  "classic chrome": "经典正片", "classic neg": "经典负片", "nostalgic neg": "怀旧负片", "eterna/cinema": "Eterna / 电影",
  "eterna bleach bypass": "Eterna 漂白效果", "acros": "Acros 黑白", "monochrome": "黑白", "sepia": "棕褐色",
  "single frame": "单张拍摄", "continuous low": "低速连拍", "continuous high": "高速连拍", "movie": "视频",
  "no flash": "未闪光", "fired": "已闪光", "fired, compulsory flash mode": "已闪光（强制闪光）", "auto, did not fire": "自动闪光（未触发）",
  "face detection": "人脸识别", "eye detection": "眼睛识别", "subject tracking": "主体追踪",
  "ois lens": "镜头光学防抖", "on (mode 1, continuous)": "开启（模式 1，持续）", "on (mode 2, shooting only)": "开启（模式 2，仅拍摄时）",
};

function formatMetadataText(value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.map(formatMetadataText).join(" · ");
  if (typeof value !== "string") return String(value);
  const trimmed = value.trim();
  const translated = metadataValueTranslations[trimmed.toLocaleLowerCase()];
  if (!translated && trimmed.includes(";")) {
    const segments = trimmed.split(";").map((item) => item.trim());
    const localized = segments.map((item) => metadataValueTranslations[item.toLocaleLowerCase()] ?? item);
    if (localized.some((item, index) => item !== segments[index])) return `${localized.join("；")}（${value}）`;
  }
  return translated && translated !== value ? `${translated}（${value}）` : value;
}

export function CaptureDetailPanel({ detail, close, saveAiReview, saveReview, saveTags, navigate, hasPrev, hasNext }: {
  detail: CaptureDetail;
  close: () => void;
  saveAiReview: (analysisId: number, verdict: "accurate" | "partial" | "inaccurate" | null, note: string | null) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  saveTags: (captureId: number, tags: Array<{ dimension: CaptureTagDimension; name: string }>) => Promise<void>;
  navigate: (direction: 1 | -1) => void;
  hasPrev: boolean;
  hasNext: boolean;
}) {
  const exif = detail.files.find((file) => file.role === "jpeg") ?? detail.files[0];
  const latestAnalysis = detail.ai_analyses[0];
  const latestAi = latestAnalysis?.result as Record<string, unknown> | undefined;
  const visibleProblems = Array.isArray(latestAi?.visible_problems) ? latestAi.visible_problems as Array<Record<string, unknown>> : [];
  const shootingAdvice = Array.isArray(latestAi?.shooting_advice) ? latestAi.shooting_advice as Array<Record<string, unknown>> : [];
  const lightroomSuggestions = Array.isArray(latestAi?.lightroom_suggestions) ? latestAi.lightroom_suggestions as Array<Record<string, unknown>> : [];
  const [aiNote, setAiNote] = useState(latestAnalysis?.user_note ?? "");
  const [immersive, setImmersive] = useState(false);
  const [showImmersiveInfo, setShowImmersiveInfo] = useState(false);
  const [zoom, setZoom] = useState(0);
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const [informationLevel, setInformationLevel] = useState<"compact" | "standard" | "full">(() => {
    const saved = window.localStorage.getItem("tangerine-detail-information");
    return saved === "compact" || saved === "full" ? saved : "standard";
  });
  useEffect(() => setAiNote(latestAnalysis?.user_note ?? ""), [latestAnalysis?.id, latestAnalysis?.user_note]);
  useEffect(() => window.localStorage.setItem("tangerine-detail-information", informationLevel), [informationLevel]);
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousPaddingRight = document.body.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbarWidth > 0) document.body.style.paddingRight = `${scrollbarWidth}px`;
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousPaddingRight;
    };
  }, []);
  const metadataText = formatMetadataText;
  const review = (changes: Partial<ReviewPayload>) => saveReview(detail.id, {
    user_rating: detail.user_rating,
    user_pick: Boolean(detail.user_pick),
    user_reject: Boolean(detail.user_reject),
    user_note: detail.user_note,
    ...changes,
  });
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const review = (changes: Partial<ReviewPayload>) => saveReview(detail.id, {
        user_rating: detail.user_rating,
        user_pick: Boolean(detail.user_pick),
        user_reject: Boolean(detail.user_reject),
        user_note: detail.user_note,
        ...changes,
      });
      if (event.key === "Escape") { if (immersive) { setImmersive(false); setZoom(0); } else close(); return; }
      if (event.key === "f" || event.key === "F") { setImmersive((current) => !current); setZoom(0); return; }
      if (event.key === "ArrowLeft") { event.preventDefault(); navigate(-1); return; }
      if (event.key === "ArrowRight") { event.preventDefault(); navigate(1); return; }
      if (event.key >= "1" && event.key <= "5") { review({ user_rating: Number(event.key) }); return; }
      if (event.key === "0") { review({ user_rating: null }); return; }
      if (event.key === "p" || event.key === "P") { review({ user_pick: !detail.user_pick, user_reject: false }); return; }
      if (event.key === "x" || event.key === "X") { review({ user_pick: false, user_reject: !detail.user_reject }); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detail, close, immersive, navigate, saveReview]);
  return (
    <div ref={backdropRef} className={`detail-backdrop ${immersive ? "immersive" : ""}`} role="dialog" aria-modal="true" aria-label={`${detail.stem} 照片详情`} onClick={close}>
      {hasPrev && <button className="detail-nav prev" aria-label="上一张" onClick={(event) => { event.stopPropagation(); navigate(-1); }}>‹</button>}
      {hasNext && <button className="detail-nav next" aria-label="下一张" onClick={(event) => { event.stopPropagation(); navigate(1); }}>›</button>}
      <section className={`detail-panel ${showImmersiveInfo ? "show-immersive-info" : ""}`} onClick={(event) => event.stopPropagation()}>
        <button className="detail-close" onClick={close} aria-label="关闭详情">×</button>
        <div className={`detail-image ${zoom ? "zoomed" : ""}`}>
          <img style={zoom ? { width: `${zoom * 100}%`, height: "auto", maxWidth: "none" } : undefined} src={detail.thumbnail_url} alt={`${detail.stem} 大图预览`} />
          {detail.files.some((file) => file.role === "raw") && <span className="raw-badge">JPG + RAW</span>}
          <div className="detail-view-controls">
            <button onClick={() => { setImmersive((current) => !current); setZoom(0); }}>{immersive ? "退出沉浸" : "沉浸查看"}</button>
            {immersive && <><button onClick={() => setZoom(0)}>适应</button><button onClick={() => setZoom((current) => current ? Math.max(1, current - .5) : 1)}>−</button><button onClick={() => setZoom((current) => current ? Math.min(4, current + .5) : 1)}>＋</button><button onClick={() => setShowImmersiveInfo((current) => !current)}>{showImmersiveInfo ? "隐藏信息" : "显示信息"}</button><button onClick={() => void backdropRef.current?.requestFullscreen?.()}>浏览器全屏</button></>}
          </div>
        </div>
        <div className="detail-copy">
          <span className="section-kicker">{detail.category ?? "未分类"}</span>
          <h2>{detail.stem}</h2>
          <p>{detail.event_name ?? detail.parent_relative}</p>
          <div className="detail-review-bar">
            <div className="detail-stars" role="radiogroup" aria-label="人工星级">
              {[1, 2, 3, 4, 5].map((star) => <button key={star} className={detail.user_rating != null && detail.user_rating >= star ? "filled" : ""} aria-label={`${star} 星`} onClick={() => review({ user_rating: detail.user_rating === star ? null : star })}>★</button>)}
            </div>
            <button className={`detail-pick ${detail.user_pick ? "selected" : ""}`} onClick={() => review({ user_pick: !detail.user_pick, user_reject: false })}>入选</button>
            <button className={`detail-reject ${detail.user_reject ? "rejected" : ""}`} onClick={() => review({ user_pick: false, user_reject: !detail.user_reject })}>排除</button>
            <ReviewHelp />
            <small className="detail-shortcut-hint">快捷键：← → 切换 · 1–5 打星 · 0 清除 · P 入选 · X 排除 · Esc 关闭</small>
          </div>
          <TagEditor detail={detail} saveTags={saveTags} />
          <div className="exif-strip">
            <div><strong>{formatExposure(exif?.exposure_time)}</strong><span>快门 <ParameterHelp kind="shutter" /></span></div>
            <div><strong>{exif?.f_number ? `f/${exif.f_number}` : "—"}</strong><span>光圈 <ParameterHelp kind="aperture" /></span></div>
            <div><strong>{exif?.iso ? `ISO ${exif.iso}` : "—"}</strong><span>感光度 <ParameterHelp kind="iso" /></span></div>
            <div><strong>{exif?.focal_length_mm ? `${exif.focal_length_mm}mm` : "—"}</strong><span>焦距{exif?.focal_length_35mm ? ` · 等效${exif.focal_length_35mm}mm` : ""} <ParameterHelp kind="focal" /></span></div>
          </div>
          <div className="detail-section detail-exif-section">
            <div className="detail-section-heading"><h3>拍摄参数</h3><label>信息显示<select value={informationLevel} onChange={(event) => setInformationLevel(event.target.value as "compact" | "standard" | "full")}><option value="compact">精简</option><option value="standard">标准</option><option value="full">完整</option></select></label></div>
            <dl className="exif-grid">
              <div><dt>相机</dt><dd>{exif?.camera_model ?? "—"}</dd></div>
              <div><dt>镜头</dt><dd>{exif?.lens_model ?? "—"}</dd></div>
              <div><dt>拍摄时间</dt><dd>{detail.captured_at ? detail.captured_at.replace("T", " ") : "—"}</dd></div>
              <div><dt>尺寸</dt><dd>{exif?.width && exif?.height ? `${exif.width} × ${exif.height}` : "—"}</dd></div>
              <div><dt>曝光补偿 <ParameterHelp kind="compensation" /></dt><dd>{exif?.exposure_compensation == null ? "—" : `${exif.exposure_compensation > 0 ? "+" : ""}${exif.exposure_compensation} EV`}</dd></div>
              <div><dt>胶片模拟 <ParameterHelp kind="film" /></dt><dd>{metadataText(exif?.film_simulation)}</dd></div>
              <div><dt>GPS</dt><dd>{exif?.gps_latitude != null && exif?.gps_longitude != null ? `${exif.gps_latitude.toFixed(5)}, ${exif.gps_longitude.toFixed(5)}` : "—"}</dd></div>
            </dl>
            {informationLevel !== "compact" && <details className="metadata-details" open={informationLevel === "full"}><summary>拍摄方式与对焦</summary><dl className="exif-grid">
              <div><dt>曝光程序 <ParameterHelp kind="program" /></dt><dd>{metadataText(exif?.exposure_program)}</dd></div><div><dt>曝光模式</dt><dd>{metadataText(exif?.exposure_mode)}</dd></div>
              <div><dt>快门类型 <ParameterHelp kind="shutterType" /></dt><dd>{metadataText(exif?.shutter_type)}</dd></div><div><dt>测光模式 <ParameterHelp kind="metering" /></dt><dd>{metadataText(exif?.metering_mode)}</dd></div>
              <div><dt>白平衡 <ParameterHelp kind="whiteBalance" /></dt><dd>{metadataText(exif?.white_balance)}</dd></div><div><dt>闪光灯</dt><dd>{metadataText(exif?.flash)}</dd></div>
              <div><dt>对焦模式 <ParameterHelp kind="focus" /></dt><dd>{metadataText(exif?.focus_mode ?? exif?.af_mode)}</dd></div><div><dt>AF 区域 <ParameterHelp kind="afArea" /></dt><dd>{metadataText(exif?.af_area_mode)}</dd></div>
              <div><dt>对焦点</dt><dd>{metadataText(exif?.focus_pixel)}</dd></div><div><dt>防抖 <ParameterHelp kind="stabilization" /></dt><dd>{metadataText(exif?.image_stabilization)}</dd></div>
              <div><dt>驱动模式</dt><dd>{metadataText(exif?.drive_mode)}</dd></div><div><dt>连拍速度</dt><dd>{metadataText(exif?.drive_speed)}</dd></div>
              <div><dt>序列编号</dt><dd>{metadataText(exif?.sequence_number)}</dd></div><div><dt>包围曝光</dt><dd>{metadataText(exif?.auto_bracketing)}</dd></div>
              <div><dt>精确时间</dt><dd>{metadataText(exif?.captured_at_precise)}</dd></div><div><dt>时区</dt><dd>{metadataText(exif?.timezone_offset)}</dd></div>
            </dl></details>}
            {informationLevel === "full" && <><details className="metadata-details" open><summary>富士机内配方</summary><dl className="exif-grid">
              <div><dt>动态范围 <ParameterHelp kind="dynamicRange" /></dt><dd>{metadataText(exif?.dynamic_range)}</dd></div><div><dt>自动动态范围</dt><dd>{metadataText(exif?.auto_dynamic_range)}</dd></div>
              <div><dt>白平衡微调</dt><dd>{metadataText(exif?.white_balance_fine_tune)}</dd></div><div><dt>高光色调</dt><dd>{metadataText(exif?.highlight_tone)}</dd></div>
              <div><dt>阴影色调</dt><dd>{metadataText(exif?.shadow_tone)}</dd></div><div><dt>色彩</dt><dd>{metadataText(exif?.saturation)}</dd></div>
              <div><dt>机内锐度</dt><dd>{metadataText(exif?.camera_sharpness)}</dd></div><div><dt>降噪</dt><dd>{metadataText(exif?.noise_reduction)}</dd></div>
              <div><dt>清晰度</dt><dd>{metadataText(exif?.clarity)}</dd></div><div><dt>Color Chrome</dt><dd>{metadataText(exif?.color_chrome_effect)}</dd></div>
              <div><dt>Chrome FX Blue</dt><dd>{metadataText(exif?.color_chrome_fx_blue)}</dd></div><div><dt>颗粒</dt><dd>{[exif?.grain_effect_roughness, exif?.grain_effect_size].filter((value) => value != null).map(String).join(" · ") || "—"}</dd></div>
              <div><dt>镜头优化</dt><dd>{metadataText(exif?.lens_modulation_optimizer)}</dd></div>
            </dl></details><details className="metadata-details"><summary>文件与拍摄诊断</summary><dl className="exif-grid">
              <div><dt>方向</dt><dd>{metadataText(exif?.orientation)}</dd></div><div><dt>色彩空间</dt><dd>{metadataText(exif?.color_space)}</dd></div>
              <div><dt>位深</dt><dd>{metadataText(exif?.bits_per_sample)}</dd></div><div><dt>图像质量</dt><dd>{metadataText(exif?.image_quality)}</dd></div>
              <div><dt>RAW 压缩</dt><dd>{metadataText(exif?.raw_compression)}</dd></div><div><dt>检测人脸</dt><dd>{metadataText(exif?.faces_detected)}</dd></div>
              <div><dt>水平倾角</dt><dd>{metadataText(exif?.roll_angle)}</dd></div><div><dt>俯仰角</dt><dd>{metadataText(exif?.camera_elevation_angle)}</dd></div>
              <div><dt>模糊警告</dt><dd>{metadataText(exif?.blur_warning)}</dd></div><div><dt>对焦警告</dt><dd>{metadataText(exif?.focus_warning)}</dd></div>
              <div><dt>曝光警告</dt><dd>{metadataText(exif?.exposure_warning)}</dd></div>
            </dl></details></>}
          </div>
          <div className="detail-section"><h3>技术面板</h3>
            {detail.histogram && detail.histogram.length > 0 && <LuminanceHistogram histogram={detail.histogram} shadowClip={detail.shadow_clip_pct} highlightClip={detail.highlight_clip_pct} />}
            {detail.technical_score == null ? <p>尚未运行技术质量分析。</p> : <div className="score-bars">
              <ScoreBar label={`总分 ${Math.round(detail.technical_score)}`} score={detail.technical_score} />
              <ScoreBar label="曝光" score={detail.exposure_score} />
              <ScoreBar label="清晰度" score={detail.sharpness_score} />
              <ScoreBar label="参数" score={detail.exif_score} />
            </div>}
          </div>
          <div className="detail-section"><h3>问题证据</h3>{detail.issues.length ? <ul>{detail.issues.map((issue) => <li key={issue.code}>{issue.message}</li>)}</ul> : <p>尚未发现或尚未分析。</p>}</div>
          <div className="detail-section"><h3>本地模型建议</h3><p>{typeof latestAi?.quality_summary === "string" ? latestAi.quality_summary : "尚未运行本地模型分析。"}</p>
            {latestAnalysis && <small className="ai-result-version">{latestAnalysis.model_id} · {latestAnalysis.prompt_version} · {formatDate(latestAnalysis.finished_at)}</small>}
            {!!visibleProblems.length && <div className="ai-advice-block"><strong>可见问题</strong><ul>{visibleProblems.map((problem, index) => <li key={index}><b>{String(problem.name ?? "问题")}</b>：{String(problem.evidence ?? "没有证据说明")}（{String(problem.severity ?? "—")} / {String(problem.confidence ?? "—")}）</li>)}</ul></div>}
            {!!shootingAdvice.length && <div className="ai-advice-block"><strong>下次拍摄</strong><ul>{shootingAdvice.map((advice, index) => <li key={index}><b>{String(advice.suggestion ?? "建议")}</b>：{String(advice.reason ?? "")} <em>{String(advice.exif_basis ?? "")}</em></li>)}</ul></div>}
            {!!lightroomSuggestions.length && <div className="ai-advice-block"><strong>Lightroom</strong><ul>{lightroomSuggestions.map((advice, index) => <li key={index}><b>{String(advice.adjustment ?? "调整")}</b> · {String(advice.direction ?? "")}：{String(advice.reason ?? "")}</li>)}</ul></div>}
            {latestAnalysis && <div className="ai-advice-block"><strong>Photoshop</strong><p>{latestAi?.photoshop_needed === true ? "建议使用" : "不需要"} · {String(latestAi?.photoshop_reason ?? "未说明")}</p></div>}
            {latestAnalysis && <div className="ai-review-controls">
              <span>这条分析是否可信？</span>
              <div>
                <button className={latestAnalysis.user_verdict === "accurate" ? "selected" : ""} onClick={() => saveAiReview(latestAnalysis.id, "accurate", aiNote)}>准确</button>
                <button className={latestAnalysis.user_verdict === "partial" ? "selected" : ""} onClick={() => saveAiReview(latestAnalysis.id, "partial", aiNote)}>部分准确</button>
                <button className={latestAnalysis.user_verdict === "inaccurate" ? "rejected" : ""} onClick={() => saveAiReview(latestAnalysis.id, "inaccurate", aiNote)}>不准确</button>
              </div>
              <textarea value={aiNote} onChange={(event) => setAiNote(event.target.value)} placeholder="可选：记录误判、漏判或参数建议问题" maxLength={2000} />
              <button onClick={() => saveAiReview(latestAnalysis.id, latestAnalysis.user_verdict, aiNote)}>保存备注</button>
            </div>}
          </div>
          <div className="detail-section"><h3>文件</h3><p>{detail.files.map((file) => `${file.file_name} · ${formatFileSize(file.size_bytes)}`).join(" / ")}</p></div>
        </div>
      </section>
    </div>
  );
}
