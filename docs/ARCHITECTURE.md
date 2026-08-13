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

2026-08-13 的主分支已经加入工作流漏斗、照片详情键盘导航、直方图、补充 EXIF、乐观评分和统计钻取。这些功能继续复用稳定 `capture_id` 和现有只读照片边界；schema 18 仅扩充分析衍生数据，不改变原片身份。

schema 17 已有技术结果在升级时不会重新读取整库照片。详情接口发现某张已有技术
结果缺少 `histogram_json` 时，只读该拍摄单元的既有 JPG 并补齐直方图缓存；已有
技术总分和分项评分保持不变。统计查询同时提供相机与镜头维度，并复用图库现有
筛选参数完成钻取。

这些问题不会影响数据正确性，不应在 UI 尚未验收时进行一次性大拆分。推荐的后续顺序是：

1. 先把纯业务写操作从路由抽到独立服务模块；手工分组已完成此步骤。
2. 再把只读 SQL 查询抽到 `queries/`，保持 API 响应不变。
3. UI 验收稳定后，按首页、图库、分析、系统拆分 React feature 模块。
4. 最后确认哪些兼容接口不再需要，再逐项移除，同时保留迁移恢复和数据库审计能力。

## 验证基线

每次修改至少执行：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd web
npm.cmd run build
```

涉及正式数据库结构时，还要检查 `PRAGMA integrity_check`、服务健康状态和两套图库最近一次保护结果。测试不得使用正式照片执行写入。
