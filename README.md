# TangerinePhotoAssistant

> macOS 功能测试：项目提供隔离的四张缩小样片、独立配置和一条启动命令。Mac clone 后运行 `bash start-mac-test.sh`；完整说明见 [docs/MAC_TEST.md](docs/MAC_TEST.md)。Windows 本机仍是长期正式运行环境，Mac 测试不会连接正式图库、数据库、Lightroom 或本地 8B 模型。

一个面向个人摄影资料库的本地优先助手。它负责照片审计、JPG/RAW 配对、事件与题材分类、连拍选优、质量分级、拍摄复盘、修图建议、统计分析，以及与 Lightroom Classic 的 XMP 工作流衔接。

项目已完成活动图库迁移与保护基线，并支持增量扫描、SQLite 建库、批量 EXIF、JPG/RAW 配对、事件建议、元数据连拍候选、JPEG 视觉指纹、相似连拍拆分、精确重复确认、技术质量分析和本地 Qwen3-VL 任务。任何照片删除、原文件元数据写入和 XMP 写入仍默认关闭。

## 当前资料库

- 历史原片：`D:\Photo`，25,085 个文件，只用于长期保存和完整性检查
- 活动图库：`D:\PhotoLibrary\Photos`，24,964 个已复制并校验的文件
- 当前索引、分析、统计和 Lightroom 准备清单均使用活动图库
- 主要格式：约 13,901 个 JPG、11,136 个 RAF，另有少量 DNG、CR2、PSD 和视频
- 顶层目录：`100_FUJI`、`MyPhoto`、`素材`
- 工作方式：Lightroom Classic 为主，Photoshop 为辅，尚未导入 Lightroom

## 核心原则

1. 原片不可变：分析阶段不移动、不删除、不改写原文件。
2. 本地离线：人脸、质量和审美分析不上传云端。
3. JPG/RAW 是一个拍摄单元：评分、标签、移动和选片结果保持同步。
4. 目录表达事件，标签表达内容：避免把“女朋友”和“风景”硬拆到不同目录。
5. AI 只提出建议：闭眼、模糊、姿势和审美判断都需要可解释、可撤销、可人工复核。
6. 先生成清单：移动和 XMP 写入必须来自经过确认的 manifest。
7. 不删除：低质量与近似照片只标记为待淘汰，当前版本不提供删除能力。

## 最终使用形态

程序以 Windows 本地应用启动，并自动打开网页式界面。后端与照片分析只在本机运行，服务仅监听 `127.0.0.1`，不依赖云端。网页式界面用于事件管理、连拍同步对比、照片详情、拍摄复盘、修图建议和统计图表；后续可封装为独立桌面窗口，但不会改变本地离线架构。

## 存储安排

| 位置 | 内容 | 策略 |
|---|---|---|
| `D:\Photo` | 原始照片 | 长期保存；初期只读 |
| `D:\PhotoLibrary` | 数据库、报告、模型、XMP 备份、Lightroom 目录备份 | 持久数据 |
| `C:\PhotoLibraryFastCache` | 解码缓存、临时缩略图、推理缓存 | 可重建；总上限 40 GB，缩略图独立上限 8 GB |
| `C:\LightroomCatalog\TangerinePhoto` | Lightroom 目录和活动预览 | NVMe 加速；定期备份到 D 盘 |

迁移完成后的日常活动图库为 `D:\PhotoLibrary\Photos`。`D:\Photo` 随后冻结为历史原始档案，只做完整性检查；新照片进入活动图库的 `待整理`，分类、质量分析、模型分析、统计与 Lightroom 均使用活动图库。首次迁移采用“复制、逐文件校验、确认后切换”，不移动或删除旧档案。

C 盘缓存采用 LRU 清理，不允许无上限增长。Lightroom 仅生成标准预览，1:1 预览设置定期丢弃；智能预览按需生成。

网页缩略图不会预先复制整个图库。打开相似组或照片详情时才从对应 JPG 生成 320、640 或 1280 像素缓存；缓存文件名绑定源文件大小和修改时间，源照片变化后会生成新版本。达到 8 GB 后只删除最久未查看的生成缩略图，不触碰 `D:\Photo`。

## 目标目录模型

物理目录以事件为主，最终结构在审计后确认：

```text
D:\PhotoLibrary\Photos
├─ 旅行\2025\2025-10-03_地点
├─ 回家\2025\2025-02-01_春节
├─ 日常\2025\2025-06-18_主题
└─ 待整理
```

人物、题材、状态和问题使用标签表示，例如：`女朋友`、`父亲`、`母亲`、`宠物`、`风景`、`星空`、`待选`、`闭眼`、`失焦`。一张照片可以同时拥有多个标签。

完整实施方案见 [docs/PRODUCT_PLAN.md](docs/PRODUCT_PLAN.md)，模型分工与本地部署策略见 [docs/MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md)，当前器材与相关分析规则见 [docs/EQUIPMENT_PROFILE.md](docs/EQUIPMENT_PROFILE.md)。

## 安全检查

复制配置但不要提交本机配置：

```powershell
Copy-Item config.example.toml config.toml
python -m tangerine_photo_assistant doctor --config config.toml
```

该命令只验证路径和安全开关，不创建目录，不扫描照片，不写入任何文件。

## 第一阶段命令

在尚未安装为 Python 包时，从项目目录运行：

```powershell
$env:PYTHONPATH = "src"

# 只建立文件索引，不读取 EXIF
python -m tangerine_photo_assistant scan --config config.toml --metadata off

# 为待处理文件补充 EXIF，并重建报告
python -m tangerine_photo_assistant metadata --config config.toml

# 不扫描照片，仅根据现有数据库重建配对和报告
python -m tangerine_photo_assistant report --config config.toml

# 重建事件建议与元数据连拍候选
python -m tangerine_photo_assistant structure --config config.toml

# 只读视觉预筛：精确重复、JPEG 指纹、相似连拍拆分
python -m tangerine_photo_assistant visual --config config.toml

# 可解释技术质量评分，不加载大模型
python -m tangerine_photo_assistant quality --config config.toml

# 先运行 100 张本地大模型基准；建议在技术质量分析后执行
python -m tangerine_photo_assistant ai --config config.toml --mode benchmark --limit 100

# 将指定模型任务导出为本地 CSV/JSON，不读取或修改照片
python -m tangerine_photo_assistant ai-report --config config.toml --run-id 3
```

视觉预筛无需下载大模型。它优先批量读取连拍 JPG 内嵌的 EXIF 缩略图，生成 64 位画面指纹和平均色彩，再根据相邻画面的差异拆分连拍；缺少内嵌缩略图时才回退到低分辨率解码。指纹及哈希保存在 SQLite 中，新照片再次运行时会自动复用未变化文件的结果。RAW 原片不解码、不改写；JPG/RAW 仍作为同一个拍摄单元处理。

精确重复检测采取保守策略：只对同名且同大小的文件计算完整 SHA-256，因此不会为了查重读取全部 651GB 图库。结果仅供复核，当前程序没有删除入口。

运行数据保存在 `D:\PhotoLibrary\AnalysisDatabase`，报告保存在 `D:\PhotoLibrary\Reports`。ExifTool 使用 `D:\PhotoLibrary\Tools\ExifTool` 中的官方便携版。

## 本地网页

完成一次环境安装和前端构建后，可双击项目根目录的 `start-photo-assistant.cmd`。程序只监听 `127.0.0.1:8765`，并自动打开本地页面。

页面当前提供：

- 当前图库、拍摄单元和空间概览。
- JPG/RAW 配对统计。
- 最近入库拍摄单元。
- 主要镜头识别结果。
- 一键后台增量扫描及实时进度。
- 跨“宝贝/风光”目录合并的事件时间线。
- 按拍摄时间、相机与文件序号生成的连拍候选列表。
- 页面内一键运行本地视觉预筛，并显示相似连拍组。
- 经 SHA-256 确认的精确重复文件及其原始路径。
- 全量曝光、亮暗部、边缘细节和 EXIF 风险评分，以及相似组内技术候选。
- “质量与复盘”页面中的人工星级、保留和待淘汰标记；这些标记只写数据库。
- 可单独启动 10 张快速验证，或按 25/50/100/200/500 张运行推荐批次；接口批次限制为 1–5,000 张，并显示逐张平均耗时、吞吐量、成功率和预计剩余时间。
- 画面相似组的真实缩略图网格、组内逐张对比和大图详情。
- 图库照片网格支持多选，并可生成去除 EXIF、限制长边尺寸的 JPEG 手机分享 ZIP；导出只创建派生副本，不修改 JPG/RAW 原片。
- 在对比页直接设置人工星级、保留或待淘汰，JPG/RAW 仍视为同一拍摄单元。
- “统计与保护”页面按拍摄单元展示题材、镜头、焦段、ISO、光圈和月份分布。
- “新图库迁移”页面支持逐文件计划、安全分批复制、暂停续传、SHA-256 校验、失败清单、全库审计和二次确认切换。
- 原始档案逻辑基线：扫描后报告缺失、变化和新增文件，不自动修复或删除。
- 长任务支持安全取消；模型任务还支持照片边界安全暂停、断点继续、结构化输出重试、启动前数据库备份和重启恢复。
- 模型运行历史保留模型、量化、提示词、速度和失败记录；照片详情可把结果标为准确、部分准确或不准确并保存备注。
- 模型结果页面显示最近完成照片、完整问题证据、拍摄建议、Lightroom/Photoshop 建议，并可按任务导出 UTF-8 CSV 和完整 JSON。
- 模型结果审计按提示词版本统计具体问题、过度自信和人工复核分布；基准抽样会轮换题材与事件，并优先避免同一相似组重复占位。
- 模型结果可按提示词版本和人工复核结论分页浏览；页面同时比较各版本均速、置信度、结构/参数逻辑警告，并在运行时显示本机 GPU 利用率、显存与温度。

## 质量分析与本地模型

技术质量分析和大模型分析是两个独立阶段。技术阶段使用 Pillow 与 EXIF 计算可解释指标，不加载显卡模型；模型阶段通过现有 ComfyUI Python 环境引用 `Qwen-3-VL-8B-Instruct-heretic` 权重，并在加载时使用 INT8 量化。2026-08-08 的无图片加载测试实测模型占用约 9.35 GB 显存，完整驻留 RTX 5080。v4 默认接收缩小到最长边 960 像素的 JPG、原始 EXIF 和预先换算的快门文本，以降低视觉 token、显存压力和参数换算错误；RAW 不解码。

推荐顺序：先运行 10 张快速验证，人工复核结构化输出、中文建议、速度和显存；通过后按 25/50/100/200/500 张分批分析推荐集。网页会按最近任务的真实平均速度估算所选批次耗时。推荐集优先选择相似组代表、技术问题照片和部分非连拍样本，不会无差别分析全部照片。启动前预检会确认模型完整、备份空间充足并阻止与 ComfyUI 同时占用显卡。

模型输出只保存为建议，不能覆盖人工星级，也不会触发删除、移动、XMP 或 Lightroom 写入。模型日志和可下载任务报告保存在 `D:\PhotoLibrary\Reports`，成功结果逐张提交到 SQLite；单张失败不会丢失已完成结果。v4 会校准过度自信的 1.0 置信度、补全“不需要 Photoshop”的原因、严格检查嵌套建议字段，并拒绝“高光过曝但提高 ISO”“高 ISO 噪点却继续提高 ISO”等方向矛盾的建议；人物或宠物的三脚架建议若未说明主体静止，会标记为优先人工复核。

## 原片保护基线

逻辑基线记录某次扫描中每个文件的相对路径、大小、修改时间，以及已经计算过的少量 SHA-256。它不读取完整照片，也不是照片副本。每次增量扫描结束后，程序会将当前索引与最新基线比较，分别报告缺失、变化和新增；任何差异都只提示人工复核。

```powershell
# 手动建立一份不可覆盖的新基线
python -m tangerine_photo_assistant archive-baseline --config config.toml --name original-archive-2026-08-06

# 检查最新基线
python -m tangerine_photo_assistant archive-check --config config.toml

# 生成只读Lightroom准备清单，不执行导入、复制或XMP写入
python -m tangerine_photo_assistant lightroom-manifest --config config.toml
```

Lightroom准备清单使用UTF-8 BOM CSV和完整JSON两种格式，包含事件状态、JPG/RAW路径、有效星级、人工选择、关键词和建议复制目录。网页允许先确认事件名称与分类，再重新生成清单。当前版本没有执行Lightroom导入或XMP写入的代码路径；新图库复制只能通过下面的独立安全迁移任务执行。

## 新图库安全迁移

数据库 schema 13 提供可断点恢复的迁移任务、活动图库状态、双重保护基线、模型结构化输出尝试次数、模型结果人工复核，以及模型运行前数据库备份审计记录。执行仍必须基于已审查的逐文件计划，并在网页中完整输入计划专属确认文字。任务会先检查全部源文件的大小和修改时间、目标冲突及当前可用空间，未通过时不会创建目标图库。

复制使用目标文件旁的 `.tangerine-part-*` 临时文件，支持暂停、继续和安全取消。任务可以同时设置每批最大文件数、最大数据量和最长运行时间；任一上限先达到，就在当前文件完成校验后自动暂停。默认值为每批 2,000 个文件、100GB、4 小时，服务重启后仍可继续下一批。每个文件完成写入与 `fsync` 后，分别计算源文件和临时目标的 SHA-256；一致后才原子改名，目标已存在时绝不覆盖。单个文件失败不会中断其他文件，失败记录会保存到数据库，并生成 UTF-8 BOM CSV 与 JSON 清单。

全部文件逐项验证后还会重新执行全库审计。只有审计全部通过，网页才显示活动图库切换入口；切换需要输入另一条独立确认文字。切换会保留现有 file/capture 数据库 ID，使事件、人工评分、视觉指纹、技术质量和模型分析继续关联原拍摄单元。旧的 `D:\Photo` 不会移动或删除，并继续通过独立保护基线核对。

切换后，历史原片基线会冻结并继续只核对 `D:\Photo`；活动图库使用另一份独立基线核对 `D:\PhotoLibrary\Photos`。常规增量扫描会复用已有事件与连拍 ID，未变化连拍下的视觉相似组不会因为重建结构而被级联删除。迁移计划明确排除的参考素材仍保留在历史档案，但不再计入活动图库与个人摄影统计。

手动启动方式：

```powershell
.\.venv\Scripts\tangerine-photo.exe serve --config config.toml
```

也可以双击项目根目录的 `start-photo-assistant.cmd`。脚本会复用已经运行的服务；否则在后台启动服务，健康检查通过后自动打开本地页面。

网页构建产物完全本地化，不请求外部字体、图片或分析服务。
