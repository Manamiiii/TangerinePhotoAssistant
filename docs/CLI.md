# 命令行参考

从仓库按 README 安装后，使用 `.venv\Scripts\tangerine-photo.exe --help` 查看完整命令。
以下命令中的 `config.toml` 指你自己生成的配置。CLI 与网页共享数据库，不应在网页任务运行或暂停时启动其他写操作。

| 命令 | 用途 |
|---|---|
| `init --config config.toml --photos <绝对路径> --workspace <绝对路径> --cache <绝对路径>` | 生成配置，不覆盖已有文件，不创建照片目录 |
| `doctor --config config.toml` | 检查配置与可选工具，不扫描照片 |
| `serve --config config.toml --no-open` | 启动回环地址服务，不自动打开浏览器 |
| `scan --config config.toml --metadata off` | 更新文件索引，不读取 EXIF；不等同于独立来源导入 |
| `metadata --config config.toml` | 补充元数据并重建配对和报告 |
| `report --config config.toml` | 根据现有数据库重建配对和报告 |
| `structure --config config.toml` | 重建相册建议与连拍候选 |
| `visual --config config.toml --limit 100` | 本地视觉预筛，不加载大模型 |
| `quality --config config.toml --limit 100` | 技术质量指标，不加载大模型 |
| `ai --config config.toml --mode benchmark --limit 10` | 手动启动已配置的本地模型；运行前核对资源和备份 |
| `ai-report --config config.toml --run-id <编号>` | 导出已有模型任务 CSV/JSON |
| `archive-baseline --config config.toml --name <名称>` | 建立历史原片逻辑基线，不是复制备份 |
| `archive-check --config config.toml` | 核对历史基线差异，不自动修复 |
| `active-baseline --config config.toml --name <名称>` | 建立活动图库逻辑基线 |
| `active-check --config config.toml` | 核对活动图库基线 |
| `lightroom-manifest --config config.toml` | 生成准备清单，不写 Lightroom 目录或 XMP |

这些是功能参考，不是要求顺序执行的初始化脚本。日常导入建议用独立“导入新照片”页面，
可以看到来源范围、重复检查、确认和任务进度。AI、全量分析与完整性扫描均按实际需要手动启动。

运行数据位置由配置与数据库活动根决定：数据库在工作目录的 `AnalysisDatabase`，报告在 `Reports`，
归档凭据和相关备份在 `AlbumArchive`；升级备份在 `Backups/AnalysisDatabase`。
