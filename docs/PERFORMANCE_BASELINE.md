# 大图库性能基线

本基线只生成 SQLite 元数据，不生成、读取或修改任何照片，不启动模型，也不使用 GPU。
合成路径以 `SYNTHETIC:` 开头，不能作为真实文件操作输入。默认覆盖 10k、50k 和 100k
Capture，并为每种规模记录 P50/P95、Python 分配峰值、进程工作集峰值和
`EXPLAIN QUERY PLAN`。

## 运行

先选择一个与正式图库、工作目录和缓存目录完全分开的临时目录。Windows 示例：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m tangerine_photo_assistant.large_library_benchmark `
  --workspace D:\TangerineSyntheticBenchmark `
  --sizes 10000 50000 100000 `
  --iterations 5
```

macOS 示例：

```bash
PYTHONPATH=src .venv/bin/python -m tangerine_photo_assistant.large_library_benchmark \
  --workspace /tmp/tangerine-synthetic-benchmark \
  --sizes 10000 50000 100000 \
  --iterations 5
```

目录中会保存每个规模的可复用 SQLite 数据库和 `large-library-benchmark.json`。再次运行时，
只有数据库 Capture 数与请求规模一致才会复用；工具不会覆盖已有数据库。需要重建时应由操作者
明确删除整个隔离基准目录，程序不提供自动删除参数。工具会写入
`.tangerine-synthetic-benchmark` 标记；若目标目录非空且没有该标记，会直接拒绝运行，避免把
基准文件混入照片、工作数据或其他已有目录。

## 场景

- 图库第一页：验证常用默认排序。
- 图库深页：使用接近末尾的 OFFSET，暴露深页退化。
- 大相册折叠：验证相似组代表图、汇总大小与分页。
- 模型问题筛选：覆盖当前 JSON 问题条件。
- AI 高风险队列：覆盖 schema 27 的物化风险字段。
- 摄影统计概览：覆盖多项聚合和条件性复盘。

每个场景先预热一次，再在独立子进程中测量，避免前一个场景抬高后一个场景的进程峰值。
报告保留完整查询计划，以便代码或 SQLite 版本变化后比较索引使用情况。

## 判定方式

第一轮只建立基线，不凭单次开发机数字直接修改查询。至少比较 Windows 正式运行环境与一台
Mac 隔离环境，并关注随 10k → 50k → 100k 的增长曲线。只有 P95、内存或查询计划表现出稳定
退化时才进入优化；优化前后必须使用相同数据规模、迭代次数、Python 和 SQLite 版本复测。

## 正式库只读测量

正式库完成当前版本备份升级和健康验收后，可把报告写入已经存在的本地运行目录：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m tangerine_photo_assistant.large_library_benchmark `
  --existing-database D:\PhotoLibrary\AnalysisDatabase\catalog.sqlite3 `
  --output runtime\formal-library-benchmark.json `
  --iterations 5
```

该模式要求数据库 schema 与代码完全一致，只使用只读连接，不运行完整性检查，不读取照片，
也不会创建、升级或修改数据库。报告不包含数据库路径；输出目录必须已经存在，并且拒绝覆盖
同名报告。需要复测时应显式选择新的报告文件名，以保留前后对照。

## 2026-08-24 Windows 开发机基线

环境为 Windows 11、Python 3.12.10、schema 27；每项预热一次后测量 3 次。数字是合成元数据
的工程基线，不替代正式图库实机验收。

| 场景 | 10k P95 | 50k P95 | 100k P95 |
| --- | ---: | ---: | ---: |
| 图库第一页 | 42 ms | 182 ms | 423 ms |
| 图库深页 | 63 ms | 460 ms | 1,005 ms |
| 大相册折叠 | 45 ms | 213 ms | 388 ms |
| 模型问题筛选 | 32 ms | 125 ms | 227 ms |
| AI 高风险队列 | 6 ms | 17 ms | 28 ms |
| 摄影统计概览 | 337 ms | 1,731 ms | 3,471 ms |

统计最初在 100k 下出现约 171 MB 进程峰值。将条件复盘改为流式读取、只关联已有模型结果的
题材后，正式三档复测的所有场景进程峰值均约为 27–35 MB，统计结果未改变。100k 统计耗时仍
超过 3 秒，因此后续应先评估按版本增量汇总；当前图库查询尚不需要引入外部数据库或服务。

## 2026-08-25 正式库升级前只读检查

Windows 正式配置指向的分析库仍为 schema 26，共 13,809 个 Capture。服务关闭时执行完整
`PRAGMA integrity_check` 约耗时 4 分 30 秒，结果为 `ok`；该过程没有升级或写入数据库，也没有
读取照片或启动模型。schema 32 的工作队列和相似组规模化查询依赖后续表结构，因此正式库查询
延迟必须在首次启动完成备份升级并验收健康状态后再测，不能用 schema 26 数字冒充当前版本基线。
