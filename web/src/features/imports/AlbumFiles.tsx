import { useEffect, useState } from "react";
import { getJson } from "../../api";
import { Pagination } from "../../components/Navigation";
import type { Task } from "../../components/TaskCard";
import { formatBytes } from "../../formatters";
import "./imports.css";

export function AlbumFiles({albumId, task}: {albumId: number; task: Task | null}) {
  const [data,setData] = useState<{count:number;items:{id:number;file_name:string;path:string;media_kind:string;size_bytes:number;present:number}[]} | null>(null);
  const [offset,setOffset] = useState(0);
  const [error,setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();setData(null);setError("");
    void getJson<NonNullable<typeof data>>(`/api/albums/${albumId}/files?offset=${offset}&limit=40`,{signal:controller.signal}).then((value)=>{if(!controller.signal.aborted)setData(value);}).catch((reason)=>{if(!controller.signal.aborted)setError(String(reason));});
    return ()=>controller.abort();
  },[albumId,offset,task?.status]);
  if(error)return <p role="alert">视频与附属文件读取失败：{error}</p>;
  if(!data?.count)return null;
  return <details className="album-files"><summary>相册视频与附属文件 · {data.count} 个</summary><ul className="import-files">{data.items.map(item=><li key={item.id}><span>{item.file_name} · {formatBytes(item.size_bytes)}{!item.present && " · 文件缺失"}</span><span>{item.path}</span></li>)}</ul><Pagination compact count={data.count} limit={40} offset={offset} onChange={setOffset}/></details>;
}
