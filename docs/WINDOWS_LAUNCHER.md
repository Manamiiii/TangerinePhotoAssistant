# Windows 启动壳

本文描述源码工作区快捷方式。安装可选 `[desktop]` 依赖后，快捷方式默认打开独立窗口；未安装时
保留浏览器启动。独立窗口、内置 Python 的未签名内测包及安装说明见 [WINDOWS_APP.md](WINDOWS_APP.md)。
以下 PID/互斥锁与 `runtime/launcher` 日志说明专指浏览器回退路径。

## 已有入口和过渡路径

已建源码快捷方式继续指向根目录 `TangerinePhotoAssistant.vbs`，宿主为系统 `wscript.exe`，参数为带引号的 VBS 绝对路径，工作目录为工程根，图标索引为 `assets/tangerine-photo-assistant.ico,0`。VBS 按自身位置解析控制器，通过隐藏的 PowerShell 以 `-Mode Start` 启动。环境来自调用用户；子进程明确使用项目工作目录、根 `config.toml` 和项目 `.venv`。

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

启动日志位于仓库的 `runtime/launcher`，已经被 Git 忽略。启动壳不会自动扫描图库、运行质量或
模型分析，也不会中断现有后台任务。原来的 `start-photo-assistant.cmd` 仍保留为带控制台反馈的
排障入口，但现在与桌面快捷方式共用同一控制器。

## 当前边界

- 仍需要项目目录、`.venv`、`web/dist` 和 `config.toml`；缺少任一项会给出明确错误。
- `-Browser` 强制使用系统默认浏览器；独立窗口提供安全重启，关闭窗口不结束服务。
- 内测包已有独立窗口、校验安装、离线更新比较、回退与保留数据卸载；Setup 已提供系统卸载入口；使用手动更新，签名和干净机器验收见安装说明。
