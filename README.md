# TangerinePhotoAssistant · 本地照片整理与选片

把存储卡里的照片整理成相册，将 JPG/RAW 成对管理，对比相似照片，并保留你的评分、标签和选片决定。

**适合谁：** 使用 Windows、经常一次拍摄几十到几百张照片，希望在修图前完成整理和选片的摄影爱好者。基础流程不需要显卡模型、ComfyUI、Lightroom 或账号；照片留在本机。

**当前状态：** 个人维护的早期工具，Windows 优先。核心流程有自动化回归，但尚未完成陌生用户在干净机器上的安装验收。项目自有代码以 **GNU GPL v3（GPL-3.0-only）** 分享。详见 [License](#license)。

## 它能帮你做什么

- **从存储卡到相册**：检查文件与完整重复组，创建或选择相册，复制、SHA-256 校验、入库，最后显式确认归档。视频和 XMP/LRF 等附属文件可一起保存。
- **从一组连拍中选照片**：JPG/RAW 作为同一个拍摄单元；相似照片支持左右、上下和单图切换对比，可人工拆分分组、撤销和恢复历史。
- **把决定留住**：评分、标签、备注、选片结论写入本地数据库；按相册、器材、时间和评价筛选，再导出 JPG/RAW 副本。
- **按需复盘**：查看 EXIF、直方图、摄影统计和技术质量提示。本地模型建议是可选实验能力，不能代替你的判断。

它不替代 RAW 冲洗软件、视频编辑器或独立照片备份。Lightroom 衔接目前只做只读预检与准备清单，不自动导入目录或写 XMP。

## 快速开始：Windows 源码方式

当前推荐可核对的源码安装流程。仓库中的 Windows 打包脚本用于构建未签名内测包，本文不提供未经核验的“稳定版下载”。

需要 **Git、Python 3.12、Node.js 22.12+（22.x）**。首次安装依赖需要网络；安装完成后，核心照片管理在本机离线运行。以下命令在 PowerShell 执行，不需要激活虚拟环境或管理员权限。

```powershell
git clone https://github.com/Manamiiii/TangerinePhotoAssistant.git
cd TangerinePhotoAssistant
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements-tested.txt -e .
npm.cmd ci --prefix web
npm.cmd run build --prefix web
```

为应用创建自己的照片目录，避免直接把整个硬盘或唯一一份照片存储卡作为活动图库。下面的路径位于当前用户目录；可改到有足够空间的其他磁盘。

```powershell
$libraryBase = Join-Path $env:LOCALAPPDATA "TangerinePhotoAssistant"
$photoRoot = Join-Path $libraryBase "Photos"
$workRoot = Join-Path $libraryBase "Workspace"
$cacheRoot = Join-Path $libraryBase "Cache"
New-Item -ItemType Directory -Force -Path $photoRoot | Out-Null

.\.venv\Scripts\tangerine-photo.exe init --config config.toml --photos "$photoRoot" --workspace "$workRoot" --cache "$cacheRoot"
.\.venv\Scripts\tangerine-photo.exe doctor --config config.toml
.\.venv\Scripts\tangerine-photo.exe serve --config config.toml --no-open
```

保留启动终端，在浏览器打开 **http://127.0.0.1:8765**。`init` 不覆盖已有配置；工作目录与缓存由应用按需创建。普通 `pip install` 生成的 wheel 不包含完整网页/器材资源，这里必须从仓库执行 `-e .`，并完成前端构建。

首次任务：

1. 进入 **导入新照片**，选择存储卡中的一个拍摄目录，点击“检查这批文件”。此步只读。
2. 核对照片、RAW、视频、附属文件和跳过清单，新建“日期 · 主题”相册，或加入已有相册。
3. 确认后点击“复制并导入”，等待校验和入库。入库后停留本页，由你选择查看相册或继续归档。
4. 点击“完成归档”，核对目标和逐文件清单，输入确认文字。归档只清理校验成功的本批待整理副本，**不清理存储卡**。
5. 进入相册浏览、评分和对比；相似分析、技术检测与模型分析均需另行启动。

更详细的路径选择、已有图库接入和故障恢复见 [首次使用与常见问题](docs/GETTING_STARTED.md)。独立窗口需要可选的 pywebview 与 WebView2，见 [Windows 窗口和打包说明](docs/WINDOWS_APP.md)。macOS/Linux 的部分底层逻辑有测试，不代表已经验证了桌面使用体验。

## 数据会发生什么变化

| 操作 | 对文件和数据的影响 |
|---|---|
| 浏览、评分、标签、分析 | 不改原片；结果写入工作目录，缩略图写缓存 |
| 检查导入来源 | 只读来源和已有索引，尚不复制照片 |
| 确认复制并导入 | 复制到活动图库的待整理批次，保留来源原片 |
| 确认归档 | 备份数据库、复制并校验、更新索引，然后清理对应待整理副本 |
| 导出照片 | 在报告目录生成新的 ZIP；原尺寸 JPG/RAW 可能保留 EXIF/GPS |
| 导出人工数据 JSON | 保存部分人工决定，不包含照片、相册定义或成员关系，不能替代完整备份 |

不要把照片或工作目录放进缓存目录。不要在任务运行时手工移动应用正在使用的文件。归档完成也不等于已经有独立磁盘备份。

## 已知边界

- **图库预览以 JPG/JPEG 为主。** RAW 可配对和保存，不提供 RAW 解码；其他图片可以保存，但不承诺可在图库中预览。视频和附属文件有分页清单，不提供播放、剪辑或视频分析。
- ExifTool 可选；未配置时用 Pillow 读取支持图片的基础 EXIF，RAW 和厂商扩展信息可能无法解析。配置官方 ExifTool 后可补充元数据。
- 相似识别主要针对同次拍摄的连拍，不能承诺找到所有相似画面。模型和技术评分都是辅助建议，不会自动删片。
- 单批导入最多 10,000 个支持文件。完整重复组跳过；JPG/RAW/sidecar 同组有新增成员时整组保留，避免拆散配对。
- 中断的导入/归档会保留资料并占用任务槽。恢复原来源路径和存储条件后继续；当前没有“放弃并自动清理未完成批次”的入口。
- 报告、导入记录和数据库备份不会自动按日期清理。磁盘容量仍需关注。
- 只支持可信本机单用户使用。不要把服务反向代理到公网或局域网；没有多用户登录与权限系统。

## 开发与反馈

技术栈：Python/FastAPI/SQLite + React/TypeScript/Vite。不要在正式照片库上做写入或恢复实验。

```powershell
.\.venv\Scripts\python.exe -m pip install -c requirements-tested.txt -e ".[test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m ruff check src tests scripts
npm.cmd test --prefix web
npm.cmd run build --prefix web
```

回归使用自动清理的临时目录，不启动真实模型。CI 覆盖 Windows/Linux；这不是所有相机格式或干净机器安装的兼容性保证。完整测试通过后再考虑更新实际使用环境；运行或暂停的任务不应被重启打断。

报告问题时，说明系统、启动方式、失败步骤和错误信息；可附系统维护生成的脱敏诊断包。请勿公开照片、GPS、完整配置、数据库或运行目录内的控制凭据。见 [问题反馈模板](.github/ISSUE_TEMPLATE/bug_report.md)。

更多文档：[命令行参考](docs/CLI.md) · [架构](docs/ARCHITECTURE.md) · [路线图](docs/ROADMAP.md) · [公开发布准备](docs/PUBLIC_RELEASE.md) · [导入验收](docs/IMPORT_ACCEPTANCE.md)

## License

Copyright © 2026 Manamiiii.

项目自有代码依据 **GNU General Public License version 3 only**（SPDX：`GPL-3.0-only`）授权，完整条款见 [LICENSE](LICENSE)。
你可以依许可使用、修改和再分发，包括商用；分发受 GPL 约束的版本时，需要保留相关声明并按 GPL 提供对应源码。
不要求将个人自用的修改上传到本仓库，也不承诺任何担保；具体权利与义务以完整许可为准。

应用设置的“版本与更新 → 开源许可”可离线阅读条款。用户自己的照片、数据库和其他私人资料不因使用本工具而变为 GPL 作品。

内置器材照片有独立的开放许可与署名，见 [THIRD_PARTY_ASSETS.md](THIRD_PARTY_ASSETS.md)。第三方依赖也继续适用各自的许可证，本项目不重新授权第三方内容。
