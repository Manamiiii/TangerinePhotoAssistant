# Windows 程序与数据目录

从 0.1.1 起，新装默认集中到 `%LOCALAPPDATA%/Tangerine`。源码、Portable 和 Setup 使用同一套 Python 路径解析；Portable 指程序无需安装，并非把数据存入解压目录。没有改变数据库 schema 36、照片格式、JSON 备份或配置身份算法。

## 默认写入地图

| 位置 | 内容与创建时机 |
|---|---|
| `Apps/TangerinePhotoAssistant` | Setup/Install.cmd 的版本程序、清单、安装凭据、维护锁、卸载器；新安装时创建 |
| `Data/TangerinePhotoAssistant/Config` | 首次无配置启动生成 `config.toml`；设置修改保留同目录配置备份与原子替换临时文件 |
| `Data/TangerinePhotoAssistant/Storage/PhotoInbox` | 首次创建的空默认来源目录；不会自动扫描或导入照片 |
| `Data/TangerinePhotoAssistant/Storage/Workspace` | 默认业务工作区；按需创建数据库 `AnalysisDatabase`（含 SQLite WAL/SHM）、设备 `Equipment`、报告/导出 `Reports`、活动图库/待整理等业务目录 |
| `Storage/Workspace/Backups` | 数据库升级、分析前与人工恢复备份；维持现有工作区相对契约，未额外建立第二个顶层 Backups |
| `Storage/Workspace/AlbumArchive` | 归档和导入流程自身的备份、归档恢复记录；导入清单保存在工作区数据库中，保留流程约定，不按缓存清理 |
| `Data/TangerinePhotoAssistant/Storage/WebView2/<配置身份>-<端口>` | 窗口浏览内核 profile，含本地偏好与内核缓存；不拆分引擎自己管理的目录 |
| `Data/TangerinePhotoAssistant/Cache` | 按配置设置的可重建缩略图等缓存 |
| `Data/TangerinePhotoAssistant/Logs/<配置身份>-<端口>` | 有界服务日志；浏览器源码入口的新启动日志在其 `Launcher` 子目录 |
| `Data/TangerinePhotoAssistant/Runtime` | 默认配置创建锁；各配置/端口的启动锁、后台锁、窗口锁、服务控制凭据、焦点请求；源码新 PID 在对应 `Launcher` 内 |

目录按实际使用创建，不预建空的 Logs/Backups/Temp 分类。不要将整个 Storage 或工作区作为缓存删除。
报告、人工导出、模型日志/中间文件仍遵循业务配置和工作区路径；不为整理目录改动模型流程。

## 既有资料与安装

1. `--config` 最高优先，原有配置、照片、缓存和工作区位置不重写。源码根 `config.toml` 存在时继续使用；否则源码 Start 和安装版使用统一默认发现流程。Status/Validate 不创建默认配置。
2. 旧 `%LOCALAPPDATA%/TangerinePhotoAssistant/config.toml` 存在时原位使用并校验可解析性。旧工作区存在但配置丢失时拒绝新建替代库；损坏配置不覆盖。新旧默认配置同时存在时要求明确 `--config`，不根据时间或文件大小猜测。
3. 没有旧资料时才建立新默认配置。新工作区或 PhotoInbox 非空但配置丢失时也拒绝。配置创建有进程锁和独占文件创建；失败保留现场，不删除残片或覆盖配置。
4. 既有 `%LOCALAPPDATA%/TangerinePhotoAssistant/Runtime/<身份>-<端口>` 若含服务记录、日志、profile 等资料，整体原位沿用。这样旧版、当前服务和窗口继续共用原锁及凭据。新旧实质运行目录并存时拒绝；不自动复制活动 profile 或令牌。
5. 新后台使用集中 Runtime，但同时持有旧 Runtime 下的 `backend.lock`，防止旧二进制绕过后台互斥。该旧位置仅留锁文件时不视为旧资料；不存数据库或 profile。旧版后来在该处产生实质运行记录而新目录也存在时，新版拒绝并要求核对，不自动清理。
6. 程序升级优先原安装登记位置；无登记时检查两个旧默认程序目录 `Programs/TangerinePhotoAssistant`、`Programs/Tangerine/TangerinePhotoAssistant` 和新 Apps 目录。单个有效安装凭据原位维护；多份或不明目录停止，用户可核对后显式指定。运行中拒绝维护，不强杀。
7. 回退只切换程序，不回滚数据库或搬迁数据。旧版无参数启动不了解新默认位置，需要显式指定当前配置；不要启动旧版让它新建另一份默认库。原有 schema 版本下限保护继续有效。不同配置或端口不表示已允许同一图库并发写入。

本轮采用**原位兼容策略**，没有新增一键搬迁工具，不迁移既有照片、数据库或 profile。因而没有“自动搬迁完成”的承诺；不会为达到目录外观统一而复制一份正式库。临时虚构目录测试覆盖两代程序根、旧数据发现、新旧冲突、损坏/缺失配置、创建失败恢复及跨版后台互斥；不是用户真实数据迁移验收。

## 明确的例外

- 显式配置、用户选择的外部照片/工作区/缓存、主动导出和选择器保存位置优先。设置只更改下一次启动配置，不搬迁资料；外部存储不可用时不创建替代库。
- 工作区内部 Backups、Reports、AlbumArchive 等沿用已有相对结构；归档凭据和升级备份不合并成通用缓存。
- 旧 Runtime、兼容后台锁以及已有源码 `runtime/launcher` 原位保留。新源码日志归入集中 Logs，旧 PID 不搬动。
- 开发的 `.venv`、`node_modules`、`web/dist`、构建缓存、候选包及验收记录留在本仓库忽略目录。源码方式显式 `init --config config.toml` 仍可把配置保存在仓库。
- 安装解包、测试夹具、标准库临时文件及 Windows 自身工作文件使用系统临时目录；不会为了收纳而修改系统 TEMP。
- Setup 的 HKCU 卸载登记和开始菜单是系统入口；共享 WebView2/.NET 安装由系统管理。用户浏览器的站点存储由浏览器管理，保留原 URL/端口，不自动迁移或清空。

卸载只按程序清单处理已核验文件，默认保留所有数据、配置、备份、旧版本凭据、共享父目录及兄弟应用。不承诺系统零痕迹，不自动清理旧候选或曾删除受拒的失败夹具。
