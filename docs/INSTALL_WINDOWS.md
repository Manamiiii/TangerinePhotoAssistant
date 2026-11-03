# Windows 安装与启动

[返回项目首页](../README.md) · [首次导入与常见问题](GETTING_STARTED.md)

当前推荐 Windows 源码安装。以下步骤只安装程序和建立配置，不会自动扫描、复制或修改你的照片。

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


## 第一次打开后

进入“导入新照片”，先检查一次拍摄的来源目录，核对清单后再确认复制。
程序会创建待整理批次，不需要事先建文件夹；详细步骤见 [首次使用](GETTING_STARTED.md)。

JPG/JPEG 提供图库预览；RAW 可成对管理，但没有 RAW 解码。视频和附属文件可保存、列出与归档，不支持播放。
基础流程不需要 ExifTool、显卡模型或 Lightroom。模型设置可以一直留空。

已有电脑照片、不希望再复制一份时，先阅读 [已有图库接入范围](GETTING_STARTED.md#接入已有照片还是从存储卡开始)。

## 停止与再次启动

关闭浏览器不会停止后台任务。确认任务空闲后，在启动终端按 Ctrl+C 停止服务。
下次使用时回到仓库目录，仅执行：

```powershell
.\.venv\Scripts\tangerine-photo.exe serve --config config.toml --no-open
```

再手动打开本地地址，不要重复初始化配置。独立窗口的安全停止和可选依赖见 [Windows 窗口说明](WINDOWS_APP.md)。

## 更新已有源码安装

先确认没有 running/paused 任务，正常停止服务，并独立备份照片和完整工作目录。
保留你自己的 `config.toml`，不要用示例覆盖。拉取代码前先检查工作区；存在自己的改动时不要直接覆盖。

```powershell
git status --short --branch
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -c requirements-tested.txt -e .
npm.cmd ci --prefix web
npm.cmd run build --prefix web
.\.venv\Scripts\tangerine-photo.exe doctor --config config.toml
.\.venv\Scripts\tangerine-photo.exe serve --config config.toml --no-open
```

按顺序执行，任何一步报错都先停下排查；`git pull --ff-only` 不会替你解决分支分歧。
数据库如需升级，应用会先创建自动备份；不要删除升级备份。安装包用户不能靠拉取源码更新已安装的 EXE。

遇到命令不存在、端口占用、目录选择或导入失败，见 [常见问题与恢复](GETTING_STARTED.md#失败时怎么做)。
