# Windows 启动壳

本文描述源码工作区快捷方式。安装可选 `[desktop]` 依赖后，快捷方式默认打开独立窗口；未安装时
保留浏览器启动。独立窗口、内置 Python 的未签名内测包及安装说明见 [WINDOWS_APP.md](WINDOWS_APP.md)。
以下 PID/互斥锁说明专指浏览器回退路径。新日志与 PID 分别归入按配置身份和端口隔离的 `Logs/<身份>/Launcher`、`Runtime/<身份>/Launcher`；已有 `runtime/launcher` 原位保留。

## 已有入口和过渡路径

已建源码快捷方式继续指向根目录 `TangerinePhotoAssistant.vbs`，宿主为系统 `wscript.exe`，参数为带引号的 VBS 绝对路径，工作目录为工程根，图标索引为 `assets/tangerine-photo-assistant.ico,0`。VBS 按自身位置解析控制器，通过隐藏的 PowerShell 以 `-Mode Start` 启动。环境来自调用用户；子进程明确使用项目工作目录、优先使用根 `config.toml` 和项目 `.venv`；根配置不存在时，Start 使用统一默认配置的发现/首次创建流程，Status/Validate 不创建配置。

`start-photo-assistant.cmd` 进入脚本所在目录并以 `-Mode Start -Console` 启动相同控制器。`install-windows-launcher.cmd` 兼容原路径，其 `-Mode Install -Console` 现在只检查启动文件并报告现有 VBS 入口。正式安装版由 Setup 管理开始菜单。手动调用的旧 `Remove` 模式核对目标、参数及工作目录后才移除匹配的旧源码链接。

控制器支持 `Start/Status/Validate/Install/Remove`、`-Port`（默认 8765）、`-Console`、`-Browser` 与 `-NoBrowser`。已有显式配置的安装版快捷方式仍使用登记的 `--config`；新安装版默认使用当前用户的独立配置。浏览器回退复用服务前按窗口相同规则核对配置身份或旧版根目录，并读取当前任务；启动和重新连接保留活动任务。原生菜单执行停止或重启时另行检查服务身份、控制凭据和任务状态。

## 日常启动

点击桌面或开始菜单的 “TangerinePhotoAssistant”：

1. 已有本应用服务时直接复用并打开独立窗口（缺少可选依赖时打开浏览器）。
2. 端口被其他程序占用时拒绝启动，不会结束其他进程。
3. 否则隐藏启动仅监听 `127.0.0.1:8765` 的服务，最长等待十五分钟完成数据库备份和升级。
4. 健康检查确认 `status=ok`、`mode=local-only` 和 schema 后才打开页面。

启动器在创建服务后立即记录 PID，并用当前项目专属的 Windows 互斥锁保护启动决策。首次升级
尚未绑定端口时再次点击，会识别并等待同一进程，不会并行启动第二个服务。失效或已复用的 PID
会在核对进程后自动清理，不会根据 PID 文件结束任何进程。

新日志位于统一 Data 根的 `Logs`；已有仓库 `runtime/launcher` 仍沿用，不搬动 PID 或旧日志。启动壳不会自动扫描图库、运行质量或
模型分析，也不会中断现有后台任务。原来的 `start-photo-assistant.cmd` 仍保留为带控制台反馈的
排障入口，但现在与桌面快捷方式共用同一控制器。

## 当前边界

- 仍需要项目目录、`.venv` 和 `web/dist`；缺少依赖会给出错误。已有根配置优先；没有根配置时使用统一默认配置，不自动发现或接管其他资料库。
- `-Browser` 强制使用系统默认浏览器；独立窗口提供安全重启，关闭窗口不结束服务。
- 内测包已有独立窗口、校验安装、离线更新比较、回退与保留数据卸载；Setup 已提供系统卸载入口；使用手动更新，签名和干净机器验收见安装说明。

## 开发完成后的桌面交付

源码桌面入口不是固定 EXE：它使用本仓库 `.venv`、Python 源码和 `web/dist`，也可能复用之前启动的后台。
提交代码、重新编译网页、更新安装候选分别是不同操作。必须分开报告磁盘就绪与运行实例已更新；不通过改变端口或指向空库来获得“新版”。

1. 读取真实 `.lnk` 的 TargetPath、Arguments、WorkingDirectory 和 IconLocation；沿 VBS、控制器核对 `.venv`、配置与端口。只核对本项目入口。用项目解释器的 `-I` 模式核对 `tangerine_photo_assistant.__file__` 指向本仓库，避免其他 Python 环境混入。
2. 查看本项目进程及只读 `/api/health`、`/api/tasks/current`。端口不可访问不证明没有窗口或正在启动的进程；进程归属、未保存编辑或任务状态不明时保留当前产物。running/paused 不能停止；终态也不等于已确认没有未保存工作。不要读取或输出 service.json 等凭据。
3. 完成 Python、Ruff、前端测试及构建门禁后提交，在干净提交上独立构建。以下命令不覆盖日常页面、不启动后台或窗口：

   ```powershell
   $deliveryRoot = "runtime/desktop-delivery/" + (Get-Date -Format "yyyyMMdd-HHmmss")
   .\.venv\Scripts\python.exe -I scripts/desktop_delivery.py build --output $deliveryRoot
   .\.venv\Scripts\python.exe -I scripts/desktop_delivery.py audit --web-dir "$deliveryRoot/web" --receipt "$deliveryRoot/receipt.json"
   ```

   构建记录包含源码提交/dirty、Python/网页输入文件 SHA-256 和产物逐文件 SHA-256；不含配置内容或照片。
   构建中输入变化则拒绝生成交付凭据。`disk_ready` 只证明当前模块路径、解释器、输入和产物对应且构建来源干净，不证明服务已更新或已完成人工验收。
4. 确认无本项目在用进程、无任务/未保存工作后，才将原 `web/dist` 保留在本轮忽略的交付目录，再将已核验的 `web` 目录切换为 `web/dist`；不覆盖在用目录，不删除旧产物。开始切换前再次检查状态，失败则保留现场或恢复原目录，不启动业务任务。快捷方式链路正确时不必改写 `.lnk`。有旧服务或窗口时先报告待安全切换；不能由核对脚本自动重启。
5. 对实际 `web/dist` 重跑 `audit --receipt ...`，保存本机报告。正式库不允许启动的任务中，到此停止：报告“磁盘就绪、实例未启动”，不能将下一次点击推测成已经验证。后续用户正常启动并确认可检查时，重跑审计；脚本只请求 health、任务状态、主页与 assets，核对配置身份、后端构建、每个页面资源散列及请求前后实例身份；不读图库或控制凭据，不发送写请求。

`instance.updated=true` 表示本次读取时服务身份、干净后端提交与页面字节对应；运行/暂停任务会原样报告，脚本不停止它们。
`not_running` 明确表示没有当前实例，`unverified`/`identity_unverified`/`unreachable_unknown` 均不能当作安全切换依据。
审计遇到服务旧版、资源不一致或身份不明返回失败；没有服务但磁盘就绪可返回成功，仍不表示实例已加载。
浏览器可能保留旧页面内存；磁盘/HTTP 核对不代表浏览器已刷新。用户应先保存编辑再刷新，必要时关闭旧窗口并重新从原入口打开；后台重启另行遵守任务保护。

新脚本属于源码交付工具，不是应用启动依赖，不增加每次点击构建/重启，也不更新 Setup、Portable 或桌面安装候选“当前”目录。
仅这些工具与文档变化时可保留原安装包，但必须写清候选构建提交与本轮源码提交不同。
