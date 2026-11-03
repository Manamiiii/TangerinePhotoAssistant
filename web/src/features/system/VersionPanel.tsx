import { useEffect, useState } from "react";
import { getJson } from "../../api";
import licenseText from "../../../../LICENSE?raw";

type HealthVersion = {
  app_version?: string;
  schema_version: number;
  build?: { version?: string; revision?: string | null; dirty?: boolean };
};

export function VersionPanel() {
  const [health, setHealth] = useState<HealthVersion | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getJson<HealthVersion>("/api/health", { signal: controller.signal })
      .then(setHealth).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);
  return <section className="panel settings-section version-panel">
    <div className="panel-heading"><h3>版本与更新</h3></div>
    <div className="version-body">
      <div className="version-summary">
        <span>后台版本 <b>{health?.build?.version ?? health?.app_version ?? "—"}</b></span>
        <span>构建 <b>{health?.build?.revision?.slice(0, 8) ?? "未记录"}{health?.build?.dirty ? "（含本地改动）" : ""}</b></span>
        <span>数据库 <b>{health ? `schema ${health.schema_version}` : "—"}</b></span>
      </div>
      {error && <p role="status">暂时无法读取后台版本，请稍后重新进入设置。</p>}
      <p>Windows 窗口顶部：应用 → 版本与更新；检查安装包请选择“检查本地安装包”。浏览器内没有此菜单。</p>
      <small>当前支持离线安装包检查，不会联网下载或自动更新。源码版更新代码、构建前端后，后端改动需安全重启才生效。</small>
      <details>
        <summary>开源许可 · GPL v3</summary>
        <p>Copyright © 2026 Manamiiii。本项目自有代码按 GNU GPL 第 3 版（GPL-3.0-only）授权，允许依许可使用、修改和再分发，不提供任何担保。第三方组件和图片保留各自许可。</p>
        <p><a href="https://github.com/Manamiiii/TangerinePhotoAssistant" target="_blank" rel="noreferrer">项目源码</a> · 下方为可离线阅读的完整许可文本。</p>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto" }}>{licenseText}</pre>
      </details>
    </div>
  </section>;
}
