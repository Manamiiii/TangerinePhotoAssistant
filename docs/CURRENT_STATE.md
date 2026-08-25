# 当前状态与新 Session 交接

更新日期：2026-08-25。本文只记录当前可执行状态，不保存逐次开发日志；现场仍以代码、Git、
数据库和服务接口为准。

## 代码与运行状态

- 正式分支：`main`；Python 3.12+、FastAPI、SQLite、React/Vite/TypeScript。
- 当前代码 schema：32。
- Windows 正式数据库最近一次只读核对为 schema 26、13,809 个 Capture，
  `PRAGMA integrity_check=ok`。首次用当前代码启动时会先创建并校验升级前备份，再升级到 32。
- 2026-08-25 本地服务未运行；桌面和开始菜单快捷方式已安装，并使用项目内多尺寸品牌图标。
- 启动壳最多等待 15 分钟完成大库升级，使用项目互斥锁和已校验 PID 避免重复启动；不会结束
  占用端口的其他进程。
- 当前自动门禁：Python 94 项、前端 6 项、Ruff、前端生产构建；GitHub Actions 覆盖 Linux 与
  Windows，Mac 隔离样例为手动冒烟。

## 已实现的产品闭环

- 本地只读索引、增量扫描、批量 EXIF、JPG/RAW Capture 配对和相册管理。
- 元数据连拍候选、JPEG 视觉指纹、相似组拆分、推荐排序、人工选片、历史恢复、低风险批量
  预览/撤销和稳定抽检。
- 技术检测、本地模型批次、模型风险审计、固定基准集、人工可信度复核和版本扩大门禁。
- 题材、工作状态、人工问题、地点、保留理由和相册附件；人工、分析和导入来源隔离。
- 照片详情分层信息、扩展 EXIF、JPG 亮度直方图、沉浸查看、参数解释和参数化修图预览历史。
- 摄影统计、条件性问题关联、成长趋势、选片会话与修图采用反馈。
- 图库常用视图、分页、折叠相似组、逐页最多 500 张的批量管理，以及 JPG/RAW 隔离导出。
- Lightroom 目录只读预检和 CSV/JSON 准备清单；不打开目录数据库、不生成 XMP。
- 历史/活动图库完整性基线、差异调查、后台任务异常队列、脱敏诊断和便携人工数据备份恢复。
- 设备库存 CRUD、图库 EXIF 使用量、相册附件关联和开放授权的内置器材图片。
- Windows 点击启动壳、首次设置向导、Mac 隔离样例和 10k/50k/100k 合成性能基线。

## 大图库设计结论

万张级使用不依赖人工逐条查看全量结果。默认流程是“聚合 → 风险排序/稳定抽样 → 人工队列 →
相册或单张下钻”：

- 首页按每日预算展示建议量和总积压，不把全部历史问题包装成当天任务。
- 技术、模型、完整性和任务异常均有稳定状态、重新出现语义与可找回历史。
- 图库和相似组在 SQLite 中完成筛选、折叠和分页；前端不加载全部 ID 执行隐式批量写入。
- 文本搜索防抖，分页请求可取消并带请求代次保护；写后只失效相关领域。
- 100k 合成库基线已建立；正式库当前 schema 仍低于代码，升级后再运行只读实测。

## 当前代码结构评价

数据安全边界、稳定 `capture_id`、领域服务和查询模块是可靠主体。维护热点按优先级为：

1. `webapp.py` 仍约 140 KB，应继续拆 router、请求模型和任务编排，领域写入不再回流路由。
2. `web/src/main.tsx` 仍约 63 KB，应把剩余加载和写操作迁入 feature controller/hook。
3. `web/src/styles.css` 仍约 184 KB，应按 feature 拆分并建立响应式/视觉回归后再批量整理。
4. TypeScript 契约仍手工维护；公共发布前应由 OpenAPI 生成，减少前后端漂移。

2026-08-25 已清理无调用方的旧 events/bursts/duplicates/phone-share API 别名、一次性 AI 截止
守护脚本和被现行路线图取代的历史计划文档。数据库表和迁移恢复能力没有删除。

## 正式数据安全边界

- 不修改 `D:\Photo` 中任何文件。
- 未明确授权不复制、移动、删除、重命名或覆盖真实照片。
- 不自动写 XMP，不自动操作 Lightroom 目录。
- 不干扰 ComfyUI 或其他 GPU 任务，不自动启动全量技术或模型分析。
- 设置可随时修改路径，但只在重启后生效；不自动搬运旧工作区、数据库或缓存。
- schema 升级必须在任务空闲时通过正常服务启动，并核对升级前备份、完整性与健康接口。

## 下一次 Windows 验收

1. 启动前读取 `/api/tasks/current`；若存在 running/paused 任务，不重启或中断。
2. 通过桌面快捷方式启动，等待正式库从 schema 26 安全升级到 32。
3. 核对 `Backups/AnalysisDatabase` 中唯一的新升级前备份，正式库和备份的
   `PRAGMA integrity_check`，以及 `/api/health` 的 `status=ok`、`mode=local-only`、
   `schema_version=32`。
4. 完成 [WINDOWS_ACCEPTANCE.md](WINDOWS_ACCEPTANCE.md) 的当前回归项；不运行全量模型。
5. 服务空闲时按 [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md) 对 schema 32 正式库执行
   只读查询基线。

## 新会话启动检查

```powershell
cd D:\IdeaProjects\TangerinePhotoAssistant
git status --short --branch
git log -5 --oneline --decorate
git fetch origin
try { Invoke-RestMethod http://127.0.0.1:8765/api/health } catch { "service not running" }
try { Invoke-RestMethod http://127.0.0.1:8765/api/tasks/current } catch { "task endpoint unavailable" }
```

修改后运行 Python 测试、Ruff、前端测试和生产构建；提交前检查 diff 与暂存文件，不 force push。
