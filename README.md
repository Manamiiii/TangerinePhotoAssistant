<p align="center">
  <img src="assets/tangerine-photo-assistant.png" width="88" height="88" alt="TangerinePhotoAssistant：橘子与相机光圈图标">
</p>

# TangerinePhotoAssistant

**把一次拍摄，从存储卡整理到相册，再选出想留下的照片。**

一款在本机运行的照片整理与选片工具，支持 JPG/RAW 成组管理、相似照片对比、评分标签和复制校验归档。
适合使用 Windows、习惯拍摄 JPG 或 JPG+RAW，希望在修图前整理一批照片的摄影爱好者。

**本地运行 · 无需账号 · 基础流程无需大模型 · GPL v3**

[安装与启动](docs/INSTALL_WINDOWS.md) · [第一次导入](docs/GETTING_STARTED.md) · [功能边界](#支持范围) · [问题反馈](https://github.com/Manamiiii/TangerinePhotoAssistant/issues/new?template=bug_report.md)

> 当前是个人维护的早期版本，Windows x64 优先；提供未签名 Setup/Portable 构建，尚未公开发布安装包或完成干净机器验收。核心流程有自动化回归，日常使用仍请保留独立备份。

## 用在什么场景

| 拍完之后遇到的事 | 可以怎样处理 |
|---|---|
| 存储卡里有 JPG、RAW、视频和附属文件，想一起保存 | 检查一批文件，新建或选择相册，复制并逐文件校验，保留卡内来源 |
| JPG/RAW 总要分别筛选，一组连拍又很难选 | 同次拍摄作为一个单元管理；左右、上下或单图切换对比，人工拆组、选片和撤销 |
| 选完之后，过一阵又找不到当时的决定 | 保存评分、标签、备注和选片历史，按相册、时间、器材或评价筛选 |
| 只想把选好的照片交给后续修图流程 | 导出 JPG/RAW 副本；按需查看 EXIF、直方图、技术质量提示和摄影统计 |

整理、选片和导出不需要配置模型。可选的本地模型用于提供辅助建议，决定仍由你作出。

## 从一批新照片开始

**检查来源 → 复制校验并入库 → 整理选片 → 确认归档 → 按需导出**

1. 打开 **导入新照片**，选择存储卡中的拍摄目录，点击“检查这批文件”。先核对文件、重复组和跳过清单。
2. 新建“日期 · 主题”相册，或加入已有相册，确认后点击“复制并导入”。系统自动建立待整理批次，无需预建文件夹。
3. 入库完成后点击 **查看相册**，浏览照片、评分和对比；相似识别及其他分析需由你另行启动。
4. 回到导入页或相册，点击 **完成归档**，核对正式目录和文件清单，再输入确认文字。
5. 用筛选和选片结果导出需要的 JPG/RAW 副本，交给你习惯的修图软件。

也可以先归档、后选片。**入库完成不等于归档完成**：归档会清理已校验的本批待整理副本，不会清理存储卡。
已有电脑图库的接入方式和失败恢复见 [首次使用指南](docs/GETTING_STARTED.md)。

## 安装与启动

**普通用户**：内测 Setup 按当前用户安装，运行无需 Python 或 Node；当前没有公开下载链接，详见 [安装说明](docs/INSTALL_WINDOWS.md)。

**开发者源码方式**：需要 Git、Python 3.12、Node.js 22.12+（22.x）。首次安装需要联网，基础照片管理可离线运行。

```powershell
git clone https://github.com/Manamiiii/TangerinePhotoAssistant.git
cd TangerinePhotoAssistant
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements-tested.txt -e .
npm.cmd ci --prefix web
npm.cmd run build --prefix web
```

安装依赖后，还需要生成自己的配置并启动本地服务。**完整命令在 [Windows 安装与启动](docs/INSTALL_WINDOWS.md)**，包括目录选择、首次启动、停止和更新。
不需要管理员权限或激活虚拟环境；普通 wheel 未包含完整网页/器材资源，因此使用仓库内的 `-e .` 安装和前端构建。

安装包已自带 Python、pywebview 和网页资源，无需用户安装开发环境；独立窗口还需要 WebView2 Runtime 和 .NET Framework 4.6.2+，缺失时会明确提示。[运行要求与官方获取方式](docs/WINDOWS_APP.md#安装版运行环境与缺失提示)。现有包用于未签名内测，尚不提供经完整验收的稳定安装包。

## 照片和数据会怎样保存

- **浏览、评分和分析**不修改原片；人工决定保存在工作目录的数据库，缩略图写入独立缓存。
- **确认导入**会复制文件并校验，保留来源；同组出现新增 JPG/RAW/附属文件时整组保留，避免拆散配对。
- **确认归档**会先备份数据库、复制校验、更新索引，最后清理本批对应的待整理副本。
- **导出**生成新文件，不自动写 XMP 或操作 Lightroom 目录。原尺寸 JPG/RAW 可能保留 EXIF/GPS，分享前请核对隐私。

工作目录需要持久保存，不能当缓存删除。人工数据 JSON 只保存部分人工结果，不包含照片或相册定义/成员关系；
请独立备份照片和完整工作目录，不能把归档校验或人工数据 JSON 当作完整备份。

## 支持范围

| 内容 | 当前支持 |
|---|---|
| JPG/JPEG | 图库预览、对比、EXIF、评分标签、参数化修图预览和导出 |
| RAW | 配对、保留和导出；不提供 RAW 解码，需要 JPG 才能获得对应图库预览 |
| 视频及 XMP/LRF 等附属文件 | 随批次复制、校验、相册清单和归档；不提供视频播放、剪辑或分析 |
| ExifTool | 可选；未配置时使用 Pillow 读取基础图片 EXIF，RAW/厂商扩展信息可能缺失 |
| Lightroom | 只读预检和准备清单，不自动导入目录或写 XMP |
| 运行方式 | Windows 优先、可信本机单用户；没有公网/局域网共享和多用户权限系统 |

单批导入最多 10,000 个支持文件。中断任务会保留资料并阻止其他写任务，需恢复来源或存储条件后继续；当前没有自动放弃并清理批次的入口。
报告和备份没有自动按日期清理。macOS/Linux 的部分底层逻辑有测试，不代表桌面体验已经验收。

## 反馈与参与

欢迎分享“想完成什么、在哪一步遇到困难”，不需要先了解技术实现。
提交 [使用问题](https://github.com/Manamiiii/TangerinePhotoAssistant/issues/new?template=bug_report.md) 时，请附系统、项目版本、步骤和错误信息；可提供经检查的脱敏诊断包。
**不要上传私人照片、GPS、数据库、完整配置或服务控制凭据。**

开发者可查看 [架构](docs/ARCHITECTURE.md)、[路线图](docs/ROADMAP.md)、[命令行参考](docs/CLI.md) 和 [公开发布准备](docs/PUBLIC_RELEASE.md)。
技术栈为 Python/FastAPI/SQLite + React/TypeScript/Vite。回归只使用自动清理的临时目录，不启动真实模型：

```powershell
.\.venv\Scripts\python.exe -m pip install -c requirements-tested.txt -e ".[test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m ruff check src tests scripts
npm.cmd test --prefix web
npm.cmd run build --prefix web
```

## License

Copyright © 2026 Manamiiii.

项目自有代码依据 **GNU General Public License version 3 only**（SPDX：`GPL-3.0-only`）授权，完整条款见 [LICENSE](LICENSE)。
你可以依许可使用、修改和再分发，包括商用；分发受 GPL 约束的版本时，需要保留相关声明并按 GPL 提供对应源码。
不要求将个人自用的修改上传到本仓库，也不承诺任何担保；具体权利与义务以完整许可为准。

应用设置的“版本与更新 → 开源许可”可离线阅读条款。用户自己的照片、数据库和其他私人资料不因使用本工具而变为 GPL 作品。

内置器材照片有独立的开放许可与署名，见 [THIRD_PARTY_ASSETS.md](THIRD_PARTY_ASSETS.md)。第三方依赖也继续适用各自的许可证，本项目不重新授权第三方内容。
