import { useState } from "react";
import { ModalShell } from "../../components/ModalShell";
import { numberFormat } from "../../formatters";
import type { EquipmentCatalog, EquipmentDraft, EquipmentItem, EquipmentKind } from "./types";

export function EquipmentView({ equipment, changeOwnership, saveItem, deleteItem, changeVisibility }: {
  equipment: EquipmentCatalog | null;
  changeOwnership: (kind: EquipmentKind, key: string, owned: boolean) => Promise<void>;
  saveItem: (draft: EquipmentDraft) => Promise<void>;
  deleteItem: (kind: EquipmentKind, item: EquipmentItem) => Promise<void>;
  changeVisibility: (kind: EquipmentKind, item: EquipmentItem, visible: boolean) => Promise<void>;
}) {
  const [cameraFilter, setCameraFilter] = useState<"owned" | "all" | "detected" | "unowned">("owned");
  const [lensFilter, setLensFilter] = useState<"all" | "owned" | "unowned">("owned");
  const [lensSearch, setLensSearch] = useState("");
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [editor, setEditor] = useState<EquipmentDraft | null>(null);
  const [editorSaving, setEditorSaving] = useState(false);
  const accessoryLabels: Record<string, string> = {
    supports: "支撑设备",
    remotes: "快门控制",
    lighting: "闪光与引闪",
    filters: "滤镜",
    adapters: "转接环",
    accessories: "其他配件",
  };
  const categoryLabels: Record<string, string> = { prime: "定焦", zoom: "变焦", macro: "微距", teleconverter: "增距镜", cinema: "电影镜头" };
  const commonBrands = ["Fujifilm", "Sony", "Canon", "Nikon", "Panasonic / LUMIX", "OM System", "Olympus", "Leica", "Ricoh", "Pentax", "Hasselblad", "DJI", "Sigma", "Tamron"];
  const emptyDraft = (kind: EquipmentKind): EquipmentDraft => ({ kind, brand: kind === "lens" ? "Fujifilm" : "", model: "", display_name: "", category: kind === "lens" ? "prime" : "", section: kind === "accessory" ? "accessories" : "", notes: "", image_path: "", filter_thread_mm: "", thread_mm: "", owned: true });
  const editDraft = (kind: EquipmentKind, item: EquipmentItem): EquipmentDraft => ({ kind, key: item.inventory_key, brand: item.brand ?? "", model: item.model ?? "", display_name: item.display_name ?? "", category: item.category ?? "", section: item.section ?? "", notes: item.notes ?? "", image_path: item.image_source === "bundled" ? "" : item.image_path ?? "", filter_thread_mm: item.filter_thread_mm ? String(item.filter_thread_mm) : "", thread_mm: item.thread_mm ? String(item.thread_mm) : "", owned: item.owned, source: item.source });
  const imageUrl = (kind: EquipmentKind, item: EquipmentItem) => `/api/equipment/image?${new URLSearchParams({ kind, key: item.inventory_key })}`;
  const imageCredit = (item: EquipmentItem) => item.image_attribution?.source_url ? <span className="equipment-image-credit" title={item.image_attribution.changes}><a href={item.image_attribution.source_url} target="_blank" rel="noreferrer">图片：{item.image_attribution.creator ?? "来源页"}</a>{item.image_attribution.license_url && <> · <a href={item.image_attribution.license_url} target="_blank" rel="noreferrer">{item.image_attribution.license_name ?? "授权信息"}</a></>} ↗</span> : null;
  const visibleLenses = (equipment?.lenses ?? []).filter((item) => {
    if (lensFilter === "owned" && !item.owned) return false;
    if (lensFilter === "unowned" && item.owned) return false;
    const query = lensSearch.trim().toLocaleLowerCase();
    return !query || `${item.display_name ?? ""} ${item.model ?? ""}`.toLocaleLowerCase().includes(query);
  });
  const visibleCameras = (equipment?.cameras ?? []).filter((item) => {
    if (cameraFilter === "owned") return item.owned;
    if (cameraFilter === "unowned") return !item.owned;
    if (cameraFilter === "detected") return (item.capture_count ?? 0) > 0;
    return true;
  });
  const toggle = async (kind: EquipmentKind, item: EquipmentItem) => {
    setSavingKey(`${kind}:${item.inventory_key}`);
    try { await changeOwnership(kind, item.inventory_key, !item.owned); }
    finally { setSavingKey(null); }
  };
  const actions = (kind: EquipmentKind, item: EquipmentItem) => <div className="equipment-row-actions">
    <button className={`ownership-button ${item.owned ? "owned" : ""}`} disabled={savingKey === `${kind}:${item.inventory_key}`} onClick={() => void toggle(kind, item)}>{item.owned ? "已拥有" : "标记拥有"}</button>
    <details><summary aria-label="更多设备操作">···</summary><div><button onClick={() => setEditor(editDraft(kind, item))}>编辑信息</button>{item.source === "custom" ? <button className="danger" onClick={() => { if (window.confirm(`删除手工添加的“${item.display_name ?? item.model}”？不会影响照片和 EXIF。`)) void deleteItem(kind, item); }}>删除</button> : <button onClick={() => void changeVisibility(kind, item, false)}>隐藏</button>}</div></details>
  </div>;
  const submitEditor = async () => {
    if (!editor) return;
    setEditorSaving(true);
    try { await saveItem(editor); setEditor(null); } finally { setEditorSaving(false); }
  };
  return (
    <>
      <section className="compact-summary">
        <div><span className="section-kicker">器材档案</span><h2>设备管理</h2></div>
        <div className="compact-actions"><span>库存保存在当前工作目录</span><strong>{equipment?.profile_file ?? "读取中"}</strong></div>
      </section>
      <section className="metric-grid">
        <article><span>已拥有相机</span><strong>{equipment?.summary.camera_count ?? "—"}</strong><small>{equipment?.summary.detected_camera_count ?? "—"} 种出现在 EXIF</small></article>
        <article><span>已拥有镜头</span><strong>{equipment?.summary.lens_count ?? "—"}</strong><small>官方目录共 {equipment?.summary.catalog_lens_count ?? "—"} 款</small></article>
        <article><span>附件</span><strong>{equipment?.summary.accessory_count ?? "—"}</strong><small>灯光、滤镜与支撑设备</small></article>
        <article><span>未拥有镜头</span><strong>{equipment?.summary.unowned_lens_count ?? "—"}</strong><small>可作为选购和了解目录</small></article>
      </section>
      <section className="panel equipment-panel equipment-camera-panel">
          <div className="panel-heading"><div><span className="section-kicker">我的相机</span><h3>机身</h3></div><div className="panel-heading-actions"><div className="section-tabs" role="group" aria-label="机身拥有状态">{([['owned', '已拥有'], ['all', '全部'], ['detected', 'EXIF 发现'], ['unowned', '未拥有']] as const).map(([value, label]) => <button key={value} className={cameraFilter === value ? "active" : ""} onClick={() => setCameraFilter(value)}>{label}</button>)}</div><button className="toolbar-button" onClick={() => setEditor(emptyDraft("camera"))}>＋ 添加机身</button></div></div>
          <div className="equipment-list equipment-camera-list">
            {visibleCameras.map((item) => (
              <article className={`equipment-row ${item.owned ? "" : "unowned"}`} key={item.inventory_key}>
                <div className={`equipment-icon ${item.image_path ? "with-image" : ""}`}>{item.image_path ? <img src={imageUrl("camera", item)} alt="" /> : "C"}</div>
                <div><strong>{item.display_name ?? item.model}</strong><span>{item.brand ?? "未知品牌"} · {numberFormat.format(item.capture_count ?? 0)} 个拍摄单元{item.status === "detected" ? " · EXIF 发现" : ""}{item.notes ? ` · ${item.notes}` : ""}</span>{imageCredit(item)}</div>
                {actions("camera", item)}
              </article>
            ))}
            {!visibleCameras.length && <div className="empty-state">当前条件下没有机身。</div>}
          </div>
      </section>
      <section className="equipment-layout equipment-main-layout">
        <section className="panel equipment-panel">
          <div className="panel-heading"><div><span className="section-kicker">我的镜头</span><h3>镜头</h3></div><button className="toolbar-button" onClick={() => setEditor(emptyDraft("lens"))}>＋ 添加镜头</button></div>
          <div className="equipment-catalog-tools">
            <div className="section-tabs" role="group" aria-label="镜头拥有状态">
              {([['owned', '已拥有'], ['all', '全部'], ['unowned', '未拥有']] as const).map(([value, label]) => <button key={value} className={lensFilter === value ? "active" : ""} onClick={() => setLensFilter(value)}>{label}</button>)}
            </div>
            <input aria-label="搜索镜头" placeholder="搜索型号" value={lensSearch} onChange={(event) => setLensSearch(event.target.value)} />
          </div>
          <div className="equipment-list">
            {visibleLenses.map((item) => <article className={`equipment-row ${item.owned ? "" : "unowned"}`} key={item.inventory_key}>
              <div className={`equipment-icon ${item.image_path ? "with-image" : ""}`}>{item.image_path ? <img src={imageUrl("lens", item)} alt="" /> : "L"}</div>
              <div><strong>{item.display_name ?? item.model}</strong><span>{categoryLabels[item.category ?? ""] ?? "镜头"}{item.filter_thread_mm ? ` · ${item.filter_thread_mm}mm` : ""}{item.capture_count ? ` · ${numberFormat.format(item.capture_count)} 个拍摄单元` : ""}{item.source === "catalog" ? " · 官方目录" : item.status === "detected" ? " · EXIF 发现" : ""}{item.notes ? ` · ${item.notes}` : ""}</span>{imageCredit(item)}</div>
              {actions("lens", item)}
            </article>)}
            {!visibleLenses.length && <div className="empty-state">当前条件下没有镜头。</div>}
          </div>
          <div className="equipment-source equipment-panel-source"><span>官方目录核对 {equipment?.catalog.checked_at ?? "—"}</span>{equipment?.catalog.source_url && <a href={equipment.catalog.source_url} target="_blank" rel="noreferrer">查看富士官方页面 ↗</a>}</div>
        </section>
        <section className="panel equipment-panel">
          <div className="panel-heading"><div><span className="section-kicker">我的附件</span><h3>灯光、滤镜与辅助设备</h3></div><button className="toolbar-button" onClick={() => setEditor(emptyDraft("accessory"))}>＋ 添加附件</button></div>
          <div className="equipment-list accessory-list">
            {(equipment?.accessories ?? []).map((item) => (
              <article className="equipment-row" key={item.inventory_key}>
                <div className={`equipment-icon accessory ${item.image_path ? "with-image" : ""}`}>{item.image_path ? <img src={imageUrl("accessory", item)} alt="" /> : String(accessoryLabels[item.section ?? ""] ?? "附件").slice(0, 1)}</div>
                <div><strong>{item.display_name ?? item.model ?? item.kind}</strong><span>{accessoryLabels[item.section ?? ""] ?? "附件"}{item.thread_mm ? ` · ${item.thread_mm}mm` : ""}{item.stops ? ` · ${item.stops} 档` : ""}{item.album_count ? ` · 用于 ${numberFormat.format(item.album_count)} 个相册` : ""}{item.notes ? ` · ${item.notes}` : ""}</span>{imageCredit(item)}</div>
                {actions("accessory", item)}
              </article>
            ))}
          </div>
        </section>
      </section>
      <section className="equipment-note">
        <strong>目录与个人库存彼此分开。</strong>
        <span>可以新增、编辑和删除自定义设备；官方目录条目始终保留，可编辑个人名称、备注和拥有状态。所有修改只保存在当前工作目录。</span>
      </section>
      {!!equipment && Object.values(equipment.hidden).some((items) => items.length) && <section className="panel equipment-hidden-panel">
        <div className="panel-heading"><div><span className="section-kicker">可恢复</span><h3>已隐藏设备</h3></div></div>
        <div className="equipment-hidden-list">{(Object.entries(equipment.hidden) as Array<[EquipmentKind, EquipmentItem[]]>).flatMap(([kind, items]) => items.map((item) => <div key={`${kind}:${item.inventory_key}`}><span>{item.display_name ?? item.model}</span><button onClick={() => void changeVisibility(kind, item, true)}>恢复显示</button></div>))}</div>
      </section>}
      {editor && <ModalShell title={`${editor.key ? "编辑" : "添加"}${editor.kind === "camera" ? "机身" : editor.kind === "lens" ? "镜头" : "附件"}`} close={() => setEditor(null)}>
        <div className="equipment-editor-form">
          <label><span>品牌</span><input list="equipment-brand-options" value={editor.brand} onChange={(event) => setEditor({ ...editor, brand: event.target.value })} /><datalist id="equipment-brand-options">{commonBrands.map((brand) => <option key={brand} value={brand} />)}</datalist></label>
          <label><span>型号{editor.key && editor.source !== "custom" ? "（用于关联 EXIF）" : ""}</span><input value={editor.model} disabled={Boolean(editor.key && editor.source !== "custom")} onChange={(event) => setEditor({ ...editor, model: event.target.value })} /></label>
          <label className="wide"><span>显示名称</span><input value={editor.display_name} onChange={(event) => setEditor({ ...editor, display_name: event.target.value })} placeholder="可留空，默认显示型号" /></label>
          {editor.kind === "lens" && <><label><span>镜头类型</span><select value={editor.category} onChange={(event) => setEditor({ ...editor, category: event.target.value })}><option value="prime">定焦</option><option value="zoom">变焦</option><option value="macro">微距</option><option value="teleconverter">增距镜</option><option value="cinema">电影镜头</option></select></label><label><span>滤镜口径 mm</span><input type="number" min="1" value={editor.filter_thread_mm} onChange={(event) => setEditor({ ...editor, filter_thread_mm: event.target.value })} /></label></>}
          {editor.kind === "accessory" && <><label><span>附件类型</span><select value={editor.section} onChange={(event) => setEditor({ ...editor, section: event.target.value })}>{Object.entries(accessoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>口径 mm</span><input type="number" min="1" value={editor.thread_mm} onChange={(event) => setEditor({ ...editor, thread_mm: event.target.value })} /></label></>}
          <label className="wide"><span>个人备注</span><textarea value={editor.notes} onChange={(event) => setEditor({ ...editor, notes: event.target.value })} /></label>
          <label className="wide"><span>本地设备图片</span><input value={editor.image_path} onChange={(event) => setEditor({ ...editor, image_path: event.target.value })} placeholder="可选：JPG、PNG 或 WebP 的本机绝对路径" /><small>本地图片优先于内置开放授权素材；清空后使用内置图片，没有素材时显示字母图标。</small></label>
          <label className="equipment-owned-check"><input type="checkbox" checked={editor.owned} onChange={(event) => setEditor({ ...editor, owned: event.target.checked })} /><span>已拥有</span></label>
        </div>
        <footer className="editor-footer"><button onClick={() => setEditor(null)}>取消</button><button className="primary" disabled={editorSaving || (!editor.model.trim() && !editor.display_name.trim())} onClick={() => void submitEditor()}>{editorSaving ? "保存中…" : "保存"}</button></footer>
      </ModalShell>}
    </>
  );
}
