import { useEffect, useMemo, useState } from "react";
import type { CaptureDetail, EditParameters, EditRecipe } from "./types";

const emptyParameters: EditParameters = {
  exposure_ev: 0, contrast: 0, highlights: 0, shadows: 0,
  temperature: 0, tint: 0, saturation: 0, sharpness: 0,
};

const controls: Array<{ key: keyof EditParameters; label: string; min: number; max: number; step: number }> = [
  { key: "exposure_ev", label: "曝光", min: -2, max: 2, step: .1 },
  { key: "contrast", label: "对比度", min: -100, max: 100, step: 1 },
  { key: "highlights", label: "高光", min: -100, max: 100, step: 1 },
  { key: "shadows", label: "阴影", min: -100, max: 100, step: 1 },
  { key: "temperature", label: "色温", min: -100, max: 100, step: 1 },
  { key: "tint", label: "色调", min: -100, max: 100, step: 1 },
  { key: "saturation", label: "饱和度", min: -100, max: 100, step: 1 },
  { key: "sharpness", label: "锐化", min: 0, max: 100, step: 1 },
];

function modelParameters(detail: CaptureDetail): EditParameters | null {
  if (detail.ai_analyses[0]?.user_verdict === "inaccurate") return null;
  const raw = detail.ai_analyses[0]?.result?.edit_parameters;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const values = raw as Partial<Record<keyof EditParameters, unknown>>;
  return Object.fromEntries(Object.keys(emptyParameters).map((key) => {
    const value = values[key as keyof EditParameters];
    return [key, typeof value === "number" ? value : 0];
  })) as EditParameters;
}

function formatValue(key: keyof EditParameters, value: number) {
  if (key === "exposure_ev") return `${value > 0 ? "+" : ""}${value.toFixed(1)} EV`;
  return `${value > 0 ? "+" : ""}${value}`;
}

export function EditRecipePanel({ detail, saveRecipe, restoreRecipe }: {
  detail: CaptureDetail;
  saveRecipe: (captureId: number, parameters: EditParameters, status: EditRecipe["status"], sourceAnalysisId: number | null, note: string | null) => Promise<void>;
  restoreRecipe: (captureId: number, revisionId: number) => Promise<void>;
}) {
  const latest = detail.edit_recipes[0];
  const suggested = useMemo(() => modelParameters(detail), [detail]);
  const [parameters, setParameters] = useState<EditParameters>(latest?.parameters ?? suggested ?? emptyParameters);
  const [showOriginal, setShowOriginal] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [note, setNote] = useState(latest?.note ?? "");
  useEffect(() => {
    setParameters(latest?.parameters ?? suggested ?? emptyParameters);
    setNote(latest?.note ?? "");
  }, [detail.id, latest?.id, suggested]);
  const filter = showOriginal ? "none" : [
    `brightness(${Math.pow(2, parameters.exposure_ev)})`,
    `contrast(${Math.max(.2, 1 + parameters.contrast / 100)})`,
    `saturate(${Math.max(0, 1 + parameters.saturation / 100)})`,
  ].join(" ");
  const overlay = showOriginal ? "transparent" : `linear-gradient(rgba(${parameters.temperature >= 0 ? "255,145,45" : "55,120,255"},${Math.abs(parameters.temperature) / 500}), rgba(${parameters.tint >= 0 ? "255,70,190" : "60,220,130"},${Math.abs(parameters.tint) / 600}))`;
  const sourceAnalysisId = suggested ? detail.ai_analyses[0]?.id ?? null : null;
  return <div className="edit-recipe-panel">
    <div className="edit-preview">
      <img src={detail.thumbnail_url} alt={`${detail.stem} 参数预览`} style={{ filter }} />
      <span style={{ background: overlay }} />
      <button onPointerDown={() => setShowOriginal(true)} onPointerUp={() => setShowOriginal(false)} onPointerLeave={() => setShowOriginal(false)}>{showOriginal ? "原图" : "按住看原图"}</button>
    </div>
    <div className="edit-parameter-grid">{controls.map((control) => <label key={control.key}><span>{control.label}<b>{formatValue(control.key, parameters[control.key])}</b></span><input type="range" min={control.min} max={control.max} step={control.step} value={parameters[control.key]} onChange={(event) => setParameters((current) => ({ ...current, [control.key]: Number(event.target.value) }))} /></label>)}</div>
    <label className="edit-recipe-note"><span>方案备注 / 暂不采用原因（可选）</span><textarea value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} placeholder="例如：肤色偏暖，暂时不采用；或记录本次调整意图" /></label>
    <div className="edit-recipe-actions">
      <button onClick={() => setParameters(suggested ?? emptyParameters)} disabled={!suggested}>载入模型起点</button>
      <button onClick={() => setParameters(emptyParameters)}>全部归零</button>
      <button onClick={() => void saveRecipe(detail.id, parameters, "dismissed", sourceAnalysisId, note || null)}>暂不采用</button>
      <button className="primary" onClick={() => void saveRecipe(detail.id, parameters, "draft", sourceAnalysisId, note || null)}>保存草稿</button>
      <button className="primary" onClick={() => void saveRecipe(detail.id, parameters, "accepted", sourceAnalysisId, note || null)}>标记采用</button>
    </div>
    <small>快速预览是通用近似效果；高光、阴影与锐化会保存，但此处不会冒充 Lightroom 的精确渲染。不会写入照片或 XMP。</small>
    {detail.edit_recipes.length > 0 && <details open={historyOpen} onToggle={(event) => setHistoryOpen(event.currentTarget.open)}><summary>方案历史 · {detail.edit_recipes.length} 个最近版本</summary><div className="edit-recipe-history">{detail.edit_recipes.map((recipe) => <button key={recipe.id} disabled={recipe.id === latest?.id} onClick={() => void restoreRecipe(detail.id, recipe.id)}><span>版本 {recipe.id} · {{ draft: "草稿", accepted: "已采用", dismissed: "暂不采用" }[recipe.status]}</span><small>{recipe.created_at.replace("T", " ")}{recipe.note ? ` · ${recipe.note}` : ""}</small></button>)}</div></details>}
  </div>;
}
