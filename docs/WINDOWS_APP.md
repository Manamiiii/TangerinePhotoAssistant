# Windows 独立窗口与本地安装包

独立窗口复用原有本地 HTTP 服务、TOML 配置和网页，不另建图库，也不包含模型、照片、个人配置
或数据库。运行时需要 Windows 的 WebView2 Runtime；不自动下载安装系统组件，不降级到旧 IE
内核。核心功能仍离线，外部资料链接由用户主动在浏览器打开。

## 源码工作区

安装一次可选依赖后，现有桌面快捷方式会自动使用独立窗口：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
```

原有浏览器入口保留：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows_launcher.ps1 -Browser -Console
```

“应用”菜单可重新连接、安全重启/停止、查看版本、检查本地安装包、打开程序维护目录、浏览器
和启动日志目录。关闭窗口不会停止后台服务或
任务；再次点击只唤起同一配置的窗口。菜单重启会要求先确认保存编辑，然后检查服务身份、
控制凭据、在途写入、运行/暂停任务和审计补齐状态，不使用强杀 PID 的方式。

首次复用旧版服务可以浏览，但旧进程尚无桌面控制协议，需要按旧方式正常重启一次才能使用
菜单安全重启。不同配置占用同一端口时拒绝复用，不自动选择另一个图库。

## 构建 Windows x64 包

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,package]"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows_app.ps1
```

输出到新的 `runtime/packages/windows-时间戳`，拒绝覆盖已有目录。ZIP 内包含独立 Python 运行时、
网页、公开器材目录及项目图标，无需目标机器安装 Python、Node 或克隆工程。构建目录中的
`build` 是可重建产物，不需分发。当前为未签名内测包，不属于已签名公开发布版。

## 安装与配置

解压后直接运行 `TangerinePhotoAssistant.exe` 可使用便携程序；双击 `Install.cmd` 会复制程序到
当前用户 `%LOCALAPPDATA%/Programs/TangerinePhotoAssistant/release-时间戳` 并创建快捷方式。
不需要管理员权限，不注册开机启动，不停止现有服务。升级创建新版本目录，不覆盖正在运行
的可执行文件；旧程序目录保留供人工回退，暂不自动清理。

新包携带版本号、Git 提交、构建时间、未提交修改标记和逐文件 SHA-256 清单；安装前及复制后
都校验。只复制清单内的程序资源，不复制解压目录中额外放入的文件。校验和用于发现损坏，
不是数字签名，也不能证明发布者身份；只安装可信来源的包。

升级继续运行新包的 `Install.cmd`，保留原配置和旧程序目录。运行中的旧进程不会被替换或重启，
需保存编辑、空闲时安全停止服务并关闭窗口，再从快捷方式打开新版本。“版本与更新”显示
窗口程序和后台服务的构建身份；“检查本地安装包”只比较用户选中的解压目录，不自动联网、
下载、执行或声称某个不同提交一定更新。源码窗口的构建身份在进程启动时记录。

首次设置过 `-ConfigFile` 后，后续升级不必重传，安装器不会偷偷改回默认图库；若需改照片或工作区
目录，使用应用设置。已有的源码快捷方式或其他安装目录的同名快捷方式不会被覆盖；冲突时用
`-NoShortcuts` 安装，并从明确的程序目录打开。无清单的早期内测目录不自动接管，选新空目录安装。

新用户默认配置位于 `%LOCALAPPDATA%/TangerinePhotoAssistant/config.toml`。首次启动只创建空的
PhotoInbox、默认工作区与缓存；随后通过首页向导或设置选择真实目录，绝不自动扫描或导入。
程序目录、配置和工作区分开，升级程序不意味着升级或移动用户数据；数据库迁移仍先备份。

已有资料库应显式复用原配置，不复制照片或数据库：

```powershell
.\TangerinePhotoAssistant.exe --config "D:\YourProject\config.toml"
# 或安装时保留该配置入口：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install_windows_app.ps1 -ConfigFile "D:\YourProject\config.toml"
```

启动日志、服务凭据和窗口浏览缓存按配置身份存放在当前用户的 `TangerinePhotoAssistant/Runtime`
目录。不要分享其中的 `service.json`；使用应用内脱敏诊断包。浏览器与独立窗口的主题/常用视图
等浏览器本地偏好暂不迁移；数据库中的评分、分组、标签等仍是同一份数据。

新版服务日志固定为 `service.log` 与最多 4 个轮转文件，每份约 2 MiB，总量约 10 MiB/配置端口。
只记录生命周期事件和异常类型，不持久化 HTTP URL/查询内容、控制令牌或完整异常正文。
此策略不清理早期版本的 `server-*.log`、`backend-*.log`、模型日志或 WebView 缓存；旧文件保留，
不为上线新策略自动删除历史记录。

源码快捷方式会使用本地工作区的代码和已构建网页；从 Git 拉取后仍须按需构建网页、正常重启
后端。安装包则是构建时的版本快照，拉取 `main` 不会自动更新已安装的 EXE，需要重新构建/安装。

## 回退与卸载

从窗口“打开程序维护目录”找到 `Manage.cmd`，双击后选择切换版本或卸载某个版本；先预览，
输入完整版本目录名确认。维护窗口使用控制台文字交互，尚未接入 Windows“已安装的应用”。
回退/卸载要求该安装目录下的程序和后台均已退出；只关窗口不会退出后台，应先在任务空闲时
使用“安全停止服务”。检测到仍运行的程序或无法核对归属时拒绝，不强杀任何进程。

也可以明确指定目录执行预览，再追加 `-Apply` 确认：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File manage_windows_app.ps1 -InstallRoot "C:\YourProgram" -Action Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File manage_windows_app.ps1 -InstallRoot "C:\YourProgram" -Action Activate -Release "release-时间戳-标识"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File manage_windows_app.ps1 -InstallRoot "C:\YourProgram" -Action Uninstall -Release "release-时间戳-标识"
```

- 回退只切换程序入口，不回滚数据库。安装记录保留曾激活版本的最高 schema，低于此值的版本
  不允许切换；即使数据库被其他入口升级，原有数据库版本保护也会在启动时拒绝旧程序写入。
- 卸载只逐个删除清单中校验仍一致的程序文件。不递归删除安装目录；额外文件、被修改的文件、
  配置、数据库、缓存、照片全部保留。版本目录、清单收据和安装状态保留用于核对。
- 卸载当前版本时仅移除仍指向本安装目录已登记程序的快捷方式，不自动激活另一个版本。
  删除的程序文件可从原安装包恢复，但卸载本身没有“撤销删除”；请保留可信安装包。
- 文件被占用或维护中断可能留下部分程序文件，可从原包重新安装；不把部分失败当成成功，
  不处理用户数据，也不自动删除残留目录。

## 验收与当前边界

2026-08-31 已在当前 Windows 机器完成源码窗口复用、重复启动、关闭后后台继续运行验证；
用户确认窗口功能没有发现问题。打包后端的隔离启动、安全重启、静态资源与器材接口、空库
完整性检查，以及隔离目录安装复制已通过。未中断正式服务，也未替换正式快捷方式。

构建后可在开发环境重复执行独立空库冒烟（不打开窗口；默认测试端口 18876，已占用则拒绝）：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_windows_app.py "完整路径\TangerinePhotoAssistant.exe" --port 18877
```

脚本每次建立新的临时照片空目录、工作区、配置与运行状态，退出时只请求此测试实例安全停止。
测试目录保留供排查，不会自动删除；失败时也不强杀进程。不能将正式配置传给此脚本。

- `--check --config ... --report 新文件.json` 只检查资源和配置，不启动服务/GUI，不扫描照片。
- 写入、安装复制和安全重启测试只在隔离配置中进行，禁止用正式照片制造测试数据。
- 关闭窗口后后台服务仍可被浏览器使用；没有默认“退出并终止任务”。
- 已补安装清单、配置保留、同 schema 回退、预览式保留数据卸载，以及有界日志的隔离自动测试。
- 不提供静默自动更新、联网检查、代码签名、数据库降级、自动清理旧版本或卸载用户数据。
- 安装包分发前还需公开许可证决策、第三方依赖许可汇总与干净 Windows 环境验收。
