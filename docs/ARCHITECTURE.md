# 代码结构与维护边界

本文记录当前实现的模块边界、写入边界和后续重构顺序。它描述代码现状，不是产品页面文案。

## 运行结构

```text
React/Vite (`web/src`)
        │ HTTP / JSON
FastAPI (`webapp.py`)
        │
        ├─ 图库索引：inventory / metadata / pairing / structure
        ├─ 照片分析：visual / quality / ai_analysis / ai_worker
        ├─ 人工管理：grouping / equipment / statistics / exports
        ├─ 安全设施：archive / migration / ai_safety / lightroom
        └─ SQLite：database.py
```

正式数据只在 Windows 主机使用。Mac 启动脚本创建独立的演示图库、缓存和数据库，不读取正式路径。

公共化基础使用同一套 `Settings` 数据模型。CLI 初始化器只生成安全配置，
`/api/system/capabilities` 则向网页或未来桌面壳报告操作系统、可选工具和当前安全开关；
安装器或图形向导不应创建第二套配置格式。ExifTool、本地模型、RAW 与 Lightroom
均作为可选能力降级，不作为浏览和人工选片的启动前提。

设置 API 只编辑启动配置，不直接改变当前进程捕获的 `Settings`，也不承担目录迁移。
写入顺序为临时配置、完整验证、旧配置备份、同目录原子替换；后台任务运行或暂停时
拒绝保存。照片目录、工作区或缓存变化均在重启后生效，旧目录内容原地保留。
迁移过的历史数据库可能记录独立的活动图库根目录，界面必须同时展示配置路径与
当前实际路径，不能暗示编辑文本等同于迁移数据。

## 稳定数据身份

- `files` 表示磁盘文件；迁移切换时保留其数据库 ID。
- `captures` 表示一次拍摄单元，JPG、RAW 与附属文件通过 `capture_files` 关联。
- 相册、人工星级、连拍入选、视觉指纹、质量指标和模型结果都关联 `capture_id`，不以可变化的绝对路径作为身份。
- 手工相似分组以 `manual_batch_key` 表示一次确认操作，以 `manual_group_key` 表示其中的子组；恢复操作删除完整批次。

## 写入边界

- `inventory`、`visual`、`quality` 和模型分析只读取照片，结果写入 SQLite 或可重建缓存。
- `exports` 只在报告目录产生无 EXIF 的派生 JPEG/ZIP。
- `lightroom` 当前只产生 CSV/JSON 清单。
- 只有 `migration` 能复制原片；它要求计划、确认文字、临时文件、SHA-256 和全库审计。
- 没有照片删除、原片元数据写入或 XMP 写入代码路径。

## 数据库升级

`database.connect` 在任何建表或补列之前只读检查版本。旧版本升级前使用 SQLite backup API 生成一致备份并执行 `PRAGMA integrity_check`；备份失败会阻止升级。正式库备份位于：

```text
D:\PhotoLibrary\Backups\AnalysisDatabase
```

高于当前程序版本的数据库会在任何结构写入前被拒绝，避免旧程序修改新数据库。

## 当前结构评价

领域算法已经按职责拆分，照片安全边界清晰，SQLite 外键和稳定 `capture_id` 设计适合当前单机规模。迁移、模型任务和完整性检查均有独立模块，这是合理的主体结构。

目前最大的维护热点是：

1. `webapp.py` 同时包含任务调度、查询和路由，文件偏大。
2. `web/src/main.tsx` 集中了类型、状态与所有页面组件。
3. 已完成的迁移仍保留后台 API、任务恢复和审计数据；不可达的旧迁移前端已经移除。
4. 部分旧只读接口（例如 `/api/events`、`/api/bursts`、`/api/duplicates`）已没有当前页面调用，暂时保留给 CLI、测试和兼容用途。

2026-08-13 的主分支已经加入照片详情键盘导航、直方图、版本化扩展 EXIF、乐观评分、统计钻取、沉浸查看、紧凑图库筛选和轻量首页。这些功能继续复用稳定 `capture_id` 和现有只读照片边界；schema 19 扩充分析衍生数据和元数据采集版本，schema 20 只增加人工分组历史快照，不改变原片身份。

schema 17 已有技术结果在升级时不会自动重算。schema 19 的详情数据补全任务按
`metadata_profile_version` 精确选择旧文件，通过 ExifTool 只读拍摄参数，并单独补齐缺失
`histogram_json`；已有技术总分和分项评分保持不变。详情接口仍保留单张直方图惰性补全
作为兼容兜底。统计查询同时提供相机与镜头维度，并复用图库现有筛选参数完成钻取。
schema 20 的 `similarity_group_revisions` 保存一次分组写入的前后 JSON 快照，`similarity_group_revision_captures` 负责按稳定照片 ID 查询历史。即时撤销恢复前快照，历史恢复应用目标版本的后快照，恢复自动识别则清除人工覆盖；三者都会调用现有分组重建，不读取或修改照片文件。

这些问题不会影响数据正确性，不应在 UI 尚未验收时进行一次性大拆分。推荐的后续顺序是：

1. 先把纯业务写操作从路由抽到独立服务模块；手工分组已完成此步骤。
2. 再把只读 SQL 查询抽到 `queries/`，保持 API 响应不变。
3. UI 验收稳定后，按首页、图库、分析、系统拆分 React feature 模块。
4. 最后确认哪些兼容接口不再需要，再逐项移除，同时保留迁移恢复和数据库审计能力。

2026-08-14 在正式 UI 验收完成后开始按上述顺序小步整理：质量照片/相册、图库列表与
筛选、相似组列表与详情、相册列表、首页概览与最近入库查询已移入 `queries/`；
`webapp.py` 保留兼容包装和原 API 返回。前端已抽离无状态的
`api.ts`、`formatters.ts`，以及分页、范围切换和相册工作区头部等共享导航组件。
后台任务的数据类型、完成回执和跨页面复用的任务卡也已集中到 `components/TaskCard.tsx`。
系统维护与 Lightroom 后期清单已开始按 feature 拆分到 `features/system/`，相关响应类型随
视图模块维护，`main.tsx` 仅保留请求和跨页面状态编排。
应用设置页及系统能力/配置契约也已迁入该 feature；通用编辑弹层位于
`components/ModalShell.tsx`。设备管理及摄影统计主视图与数据契约已分别移入
`features/equipment/` 和 `features/statistics/`，入口文件只负责加载数据和页面编排。
质量分析主视图及技术检测/本地模型结果契约位于 `features/analysis/`；任务归属、结果分页
和分析页内部浏览状态由该 feature 自己维护，不再依赖入口文件内部实现。
相似组选片、人工拖拽分组编辑器及相似组契约位于 `features/similarity/`；图库中的组内选片
弹层复用同一编辑器，撤销和恢复语义保持一致。
照片详情面板、扩展 EXIF 翻译、参数解释、直方图和评分展示位于 `features/details/`，详情
接口契约与入口层的加载/导航状态分离。
页面业务状态和接口契约均未改变，后续模块继续使用同样的“小范围迁移 + 现有回归测试”
方式推进。

人工评分写入已集中到 `reviews.py`，单张旧式相似组覆盖的校验、持久化和重建也已收归
`grouping.py`。Web 路由只负责后台任务冲突检查、HTTP 状态映射和连接生命周期。

旧 `/api/bursts`、`/api/duplicates` 仍作为兼容查询保留在 `webapp.py`；照片详情还承担
扩展 EXIF 解释，分析概览还组合任务和模型运行状态。这些边界应在对应领域接口确认后再
拆，不为了减少文件行数进行机械迁移。

## 验证基线

每次修改至少执行：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd web
npm.cmd run build
```

涉及正式数据库结构时，还要检查 `PRAGMA integrity_check`、服务健康状态和两套图库最近一次保护结果。测试不得使用正式照片执行写入。
