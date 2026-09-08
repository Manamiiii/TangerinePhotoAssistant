import { useState } from "react";
import { ModalShell } from "../../components/ModalShell";
import { PhotoComparison } from "../details/PhotoComparison";
import type { SimilarityGroupDetail } from "./types";

/** Key this entry by group ID so candidates cannot leak into another group. */
export function GroupComparison({ group }: { group: SimilarityGroupDetail }) {
  const [open, setOpen] = useState(false);
  const [leftId, setLeftId] = useState(group.items[0]?.capture_id);
  const [rightId, setRightId] = useState(group.items[1]?.capture_id);
  const left = group.items.find((item) => item.capture_id === leftId) ?? group.items[0];
  const right = group.items.find((item) => item.capture_id === rightId && item.capture_id !== left?.capture_id)
    ?? group.items.find((item) => item.capture_id !== left?.capture_id);
  return <>
    <button className="toolbar-button" disabled={!left || !right} onClick={() => setOpen(true)}>双图对比</button>
    {open && left && right && <ModalShell title={`${group.event_name} · 组内双图对比`} expanded close={() => setOpen(false)}>
      <div className="group-comparison-choices">{([
        ["A", left, right, setLeftId], ["B", right, left, setRightId],
      ] as const).map(([label, current, other, update]) => <label key={label}>{label} 照片
        <select aria-label={`${label} 对比照片`} value={current.capture_id} onChange={(event) => update(Number(event.target.value))}>
          {group.items.map((item) => <option key={item.capture_id} value={item.capture_id} disabled={item.capture_id === other.capture_id}>{item.stem}{item.user_pick ? " · 人工保留" : item.auto_pick ? " · 技术推荐" : ""}</option>)}
        </select></label>)}</div>
      <PhotoComparison key={`${left.capture_id}:${right.capture_id}`} photos={[left, right].map((item) => ({ id: item.capture_id, stem: item.stem, album_name: group.event_name })) as [{ id: number; stem: string; album_name: string }, { id: number; stem: string; album_name: string }]}
        backLabel="返回相似组" back={() => setOpen(false)} />
    </ModalShell>}
  </>;
}
