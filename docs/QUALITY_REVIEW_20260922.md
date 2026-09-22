> 修复状态：本报告为修复前审查快照，后续实施与更正以 docs/QUALITY_REMEDIATION.md 为准。L08 关于 Ruff 默认规则未启用的推断已撤回。

# TangerinePhotoAssistant 全面质量审查与清理规划

审查日期：2026-09-22。基线：`main` / `431fd65`。审查开始、结束时受 Git 管理的工作区均干净。

## 1. 结论与审查范围

项目具备完整的本地照片管理业务链路，现有自动门禁通过，但不能因此认定数据边界已全部安全。本次发现 **32 项问题：高 5 项、中 19 项、低 8 项**。优先级应为：先保护照片身份与人工数据，再处理任务恢复和界面一致性，最后做结构与冗余清理。不建议先大规模拆文件或改写前端。

盘点了全部 **228 个 Git 跟踪文件**：217 个文本文件、11 个二进制资源。目录覆盖 `src`、`web`、`tests`、`scripts`、`.github`、`docs`、`equipment`、`assets`、`sample-library` 和根目录配置/启动器。对全部跟踪文本执行了标记、敏感信息特征、引用和文档链接扫描，并重点阅读扫描/配对/分组/归档/备份恢复、任务与安全边界、查询、前端状态、分页、配置和打包代码。

另盘点了本地被忽略目录（虚拟环境、依赖、缓存、构建产物、runtime）的用途；没有把第三方依赖源码、Git 对象库、历史运行报告逐字审读，也没有清理这些目录。未读取正式照片内容或操作正式数据库，未启动服务、模型、GPU、浏览器或窗口，未操作鼠标。未进行 Windows/Mac 实机视觉或安装包验收，也未扫描 Git 历史中的秘密或执行在线漏洞数据库审计。

技术栈：Python 3.12+ / FastAPI / SQLite schema 32；React / TypeScript / Vite；Pillow、可选 ExifTool 和本地模型；Windows pywebview/PyInstaller；Mac 隔离演示脚本。业务主体是文件索引 → Capture 配对 → 相册/连拍 → 人工管理与分析 → 归档/导出，人工数据主要留在数据库。

证据标签：**复现**＝在临时目录和临时数据库验证；**静态确认**＝可从现有分支直接确认；**风险**＝路径/缺口存在，但未用真实环境触发。文件位置均相对于 `D:\IdeaProjects\TangerinePhotoAssistant`；冒号后为审查版本行号。

## 2. 高严重程度：优先修复

### H01 扫描失败目录被误判为照片消失【高，复现】

- 位置：`src/tangerine_photo_assistant/inventory.py:49`、`:103`、`:162`。
- 问题：遍历遇到 PermissionError/OSError 只记 `scan_errors`，结束后却对所有未见文件设置 `present=0`，扫描仍标为 `complete`。无法读取不等于不存在。
- 复现：临时图库先成功扫描，再注入目录读取失败；结果为 `status=complete, files_seen=0`，原文件 `present=0`。
- 影响：暂时权限问题、外接盘/I/O 故障可触发错误缺失及后续配对清理，并传导至人工数据。
- 建议：记录扫描覆盖范围；只在成功完整遍历的范围判定消失。失败范围保留旧状态，扫描显示部分失败；大范围缺失先阻断破坏性索引整理。
- 验收：单目录失败不影响其他目录更新，失败范围已有照片/评分/标签不变。

### H02 配对重建破坏稳定身份，保护人工数据不完整【高，复现】

- 位置：`src/tangerine_photo_assistant/pairing.py:24`、`:34`、`:101`；`src/tangerine_photo_assistant/database.py:473`。
- 问题：每次先清空 `capture_files`；保护集合只包含指纹、技术质量、评分、模型结果四类。标签、修图、人工分组等未全部纳入。缺失 Capture 的文件映射消失，文件恢复时无法关联旧 ID。
- 复现 A：有 5 星的 Capture 1 暂时缺失后恢复，照片绑定 Capture 2，原 5 星留在没有文件的 Capture 1。
- 复现 B：只有人工标签的照片暂时缺失，重建后 `capture_tags` 从 1 条变成 0 条，发生级联删除。
- 建议：保留缺失文件与 Capture 的身份映射；“当前可见”与“身份/历史是否存在”分开。禁止普通扫描按派生结果白名单删除 Capture；合并、拆分、重新出现分别定义人工数据处理规则。
- 验收：消失→恢复、JPG/RAW 分批到达、只有标签/修图/分组的照片，均保持稳定 ID 与人工数据。

### H03 给旧照片补 RAW 会重分配整个 Capture 的相册【高，复现】

- 位置：`src/tangerine_photo_assistant/webapp.py:1402`；`albums.py:179`。
- 问题：导入归属用 `files.first_seen_run_id` 找 Capture。新文件可能只是旧 Capture 的 RAW，而非新增照片；随后调用相册分配会删除旧相册关系。
- 复现：相册 A 已有 a.jpg；补 a.raf，并选择 B 更新图库，同一个 Capture 被转入 B。
- 建议：以扫描前后 Capture 身份差集或持久导入批次判断新增照片；补全旧 Capture 的文件时保留既有人工相册。明确区分“新文件”和“新拍摄单元”。
- 验收：补 RAW/JPG 不换相册；真正新照片仍进入用户选定相册。

### H04 启动在安全路径校验前已创建/升级数据库【高，复现】

- 位置：`src/tangerine_photo_assistant/webapp.py:1768`、`:1778`；`src/tangerine_photo_assistant/database.py:76`。
- 问题：`create_app()` 先 `connect(settings.database_path)`，然后才 `settings.validate()`。配置把工作区放到照片目录时，最终虽报错，写入已发生。
- 复现：临时配置指向 `photos/unsafe-workspace`，启动报 `Workspace must not be inside the photo library`，但该处数据库已经存在。
- 建议：所有可能创建目录/数据库/备份的操作之前先校验基础路径和安全开关；读取既有 active_root 使用只读连接，再校验实际生效路径，最后迁移数据库。
- 验收：非法路径、重叠目录、禁用离线/开启原片写入等配置失败时，磁盘无新增文件。

### H05 人工备份依赖可变路径键，归档后不能匹配旧备份【高，复现】

- 位置：`src/tangerine_photo_assistant/portable_data.py:24`、`:159`；`src/tangerine_photo_assistant/album_archive.py:239`；`src/tangerine_photo_assistant/pairing.py:57`。
- 问题：便携备份保存/匹配 `capture_key`，其内容由目录和文件 stem 组成；归档会改变该键。数据库 ID 保留不等于便携备份身份稳定。
- 复现：隔离相册归档前生成含评分的人工备份，预检匹配数归档前为 1，归档后为 0，缺失数为 1。
- 建议：建立不随路径变化的持久拍摄身份，或可靠的身份别名迁移机制；旧格式需兼容。备份恢复必须展示不匹配项，避免把“格式有效”误认为“可完整恢复”。
- 验收：归档、目录改名、备份迁移前后均能恢复对应人工数据，且不按易冲突文件名误配。

## 3. 中严重程度：可靠性、交互与维护

| 编号 | 位置 | 问题与证据 | 建议与验收 |
|---|---|---|---|
| M01 | `src/tangerine_photo_assistant/webapp.py:931`、`:1364`；`src/tangerine_photo_assistant/inventory.py:162` | **静态确认**：目标相册仅在线程参数中；文件扫描已提交后，元数据/分配失败或取消，再扫描不会重新获得原 `first_seen_run_id`。本批照片可能未归入原目标相册，重试不能完整接续。 | 持久化导入批次和目标相册，在提交阶段完成可重试归属；注入元数据失败/进程中断后验证恢复。 |
| M02 | `albums.py:223`；`src/tangerine_photo_assistant/queries/similarity.py:184` | **静态确认/语义缺口**：部分照片移入另一相册时整个 burst 留在原相册；组成员仍跨相册。相册内选片可能包含已经移出的照片；当前测试验证“暂不移动整组”，没有验证最终业务语义。 | 明确跨相册分组规则。清理阶段可先阻止有冲突的部分移动并提示；若需拆组，单独设计保留人工历史的事务。 |
| M03 | `src/tangerine_photo_assistant/album_archive.py:36`、`:42`；`src/tangerine_photo_assistant/webapp.py:499`、`:1508` | **静态确认**：遍历所有归档 JSON 时无格式/字段隔离；一个损坏的旧预览或完成记录即可使 pending 检查抛错，影响启动、扫描和相册列表。 | 区分坏历史记录与真实待恢复任务，报告具体记录并进入安全只读恢复状态；不能简单忽略可能未完成的记录。 |
| M04 | `src/tangerine_photo_assistant/album_archive.py:128`、`:166`；`src/tangerine_photo_assistant/webapp.py:1843`；`web/src/features/library/AlbumArchive.tsx:34` | **风险**：归档一旦 pending 就只允许继续原计划。若源文件被外部删除、目标永久不可恢复，缺少安全的退出/恢复处理入口，全部写入长期被阻断。不是建议开放强制删除。 | 先提供明确阶段、阻塞文件、可采取的恢复步骤；安全撤销/放弃必须依据“尚未提交/已提交”分阶段设计并另行授权。 |
| M05 | `src/tangerine_photo_assistant/portable_data.py:183`、`:330`；`src/tangerine_photo_assistant/equipment.py:147` | **静态确认的故障窗口**：恢复中先替换器材 JSON，再提交 SQLite；数据库提交失败时只回滚数据库，器材文件不会一起恢复。 | 为跨文件恢复建立备份及恢复记录，失败补偿旧器材文件；注入提交失败验证两份数据一致。 |
| M06 | `src/tangerine_photo_assistant/portable_data.py:24`；`README.md:14` | **静态确认**：人工数据导出没有手动相册、人工相册归属、相册器材关系等内容。它不能替代完整人工配置备份，当前入口名称容易让人误解覆盖范围。 | 先列清覆盖/不覆盖项及适用恢复场景；是否扩展备份格式单独处理，不宣称当前备份可完整重建所有人工管理状态。 |
| M07 | `src/tangerine_photo_assistant/metadata.py:281`；`src/tangerine_photo_assistant/visual.py:192` | **静态确认**：ExifTool 常驻进程 `readline()` 无期限，视觉缩略图提取 `subprocess.run` 也无 timeout。工具卡住时安全取消只能等待，任务可能持续占槽。 | 增加批次期限、取消信号与工具进程回收，只终止本任务子进程；使用假进程测试永不返回和半截 JSON。 |
| M08 | `src/tangerine_photo_assistant/ai_safety.py:24`、`:123` | **静态确认**：ComfyUI 检测只匹配 `Documents\ComfyUI`；其他安装位置不识别，检测命令失败也返回空集合；不能等同“GPU 无竞争”。 | 检测失败应显示未知并阻止自动放行；按可配置进程特征及实际 GPU 使用核对。不得为测试结束用户进程。 |
| M09 | `src/tangerine_photo_assistant/webapp.py:1854`、`:2942`；`src/tangerine_photo_assistant/exports.py:25` | **静态确认**：全局写锁覆盖整个请求，同步 ZIP 编码/复制在锁内执行；长导出可能阻塞评价、任务取消和其他写请求。 | 将“注册/互斥/安全重启保护”与耗时 I/O 分开；用假慢导出验证取消接口及无关写入的响应。不能直接删除安全锁。 |
| M10 | `web/src/features/library/LibraryView.tsx:222`、`:431`；`src/tangerine_photo_assistant/exports.py:37`；`src/tangerine_photo_assistant/webapp.py:274` | **静态确认**：UI 可选 500 张，导出按钮未对超过 100 张禁用或说明，后端导出上限 100。用户操作到最后才被拒绝。 | 保留合理上限，但提前显示不同操作的限制、禁用及原因；覆盖 100/101/500 边界。不默认扩大 RAW 导出负载。 |
| M11 | `web/src/features/system/ArchiveView.tsx:82`、`:107`；`web/src/main.tsx:550` | **静态确认**：差异列表、任务异常筛选、打开相似组缺少统一请求代次保护；先发后到响应可覆盖新筛选/新组。差异读取还有未捕获拒绝，失败会留下旧内容。 | 复用已有 requestGuard/AbortController，绑定数据与查询键，增加局部错误和重试；测试 A 慢 B 快及请求失败。 |
| M12 | `web/src/features/analysis/AnalysisView.tsx:144`；`web/src/features/library/AlbumArchive.tsx:26` | **静态确认**：模型结果错误被转换为 null，与加载态混淆；归档状态读取失败被吞掉，页面仍可能显示“下一步：完成归档”。新相册请求开始时旧 status 未立即清除。 | 显式 idle/loading/success/error 状态，失败不能显示业务完成/待办结论；切换对象时使旧状态失效。 |
| M13 | `src/tangerine_photo_assistant/queries/library.py:169`、`:201` | **静态确认的分页风险**：按评分排序缺少最终唯一 ID 排序；同评分同时间/无时间的照片顺序无保证，ID 分页与补字段查询也可能对平局取不同顺序。未声称本机已有重复页。 | 在普通和折叠排序末尾加稳定唯一键；用大量相同评分/时间的数据验证无重复或遗漏。 |
| M14 | `src/tangerine_photo_assistant/queries/albums.py:43`；`src/tangerine_photo_assistant/webapp.py:3276`；`web/src/features/library/AlbumArchive.tsx:33` | **静态确认**：归档状态主要依据路径是否位于“待整理”，不证明文件现存、属于标准正式目录或完成校验。UI 却有“源副本已清理”等较强语义。 | 区分“索引位于待整理外”“本系统归档完成”“完整性未知”；普通查询不为此全盘校验，文案与证据保持一致。 |
| M15 | `src/tangerine_photo_assistant/database.py:76`、`:94`、`:799` | **静态确认**：普通写连接重复执行建表/索引、字段探测、预置记录及迁移逻辑。职责混合、故障定位和升级审查困难；本次未量化其性能开销。 | 独立启动迁移与日常连接，逐版本升级并验证 schema 26→32；不要删除旧表“简化”迁移。 |
| M16 | `src/tangerine_photo_assistant/webapp.py`（3524 行）、`web/src/main.tsx`（1249 行）、`web/src/styles.css`（2532 行） | **静态确认**：任务、路由、模型、系统操作集中；主组件保存大量写操作和页面状态；CSS 多轮覆盖。单行大 JSX 进一步降低定位和代码审查效率。 | 先固定行为测试，再按一个领域一个提交拆边界；抽公共事务/错误/请求状态，避免只机械搬行或一次重写。 |
| M17 | `pyproject.toml`；`web/package.json:12`；`start-mac-test.sh:40` | **静态确认**：Python 无精确依赖锁；前端多处 latest（已有 package-lock，npm ci 并非不确定）；Mac 脚本仅环境/依赖目录不存在才安装，拉取依赖更新后可能继续用旧环境。脚本说 Node 20+，当前安装的 Vite 要求 `^20.19.0 || >=22.12.0`。 | 锁定可复现依赖集合，声明 Node 引擎版本；启动前检查依赖清单变化并明确更新，不在每次启动盲目升级。 |
| M18 | `.github/workflows/quality.yml`；`tests/test_inventory.py`；`web/src/components/PaginationInteraction.test.tsx` | **静态确认**：门禁通过但未覆盖 H01–H05；前端主要 jsdom/静态输出，没有真实浏览器布局、响应式和跨页完整链路门禁。Ruff 默认规则也不等同复杂度、hooks 和安全审计。 | 先加数据生命周期失败回归，再增加少量隔离浏览器关键链路；不要按测试数量评估安全程度。 |
| M19 | `src/tangerine_photo_assistant/album_archive.py:24`、`:114`、`:151`；`src/tangerine_photo_assistant/exports.py:83`；`src/tangerine_photo_assistant/settings.py:110`；`src/tangerine_photo_assistant/thumbnails.py:199` | **静态确认**：每次预览保存新 JSON，归档反复写全量清单，报告/ZIP/数据库备份无统一保留策略；cache 总上限主要是配置与校验，实际有执行的回收是缩略图目录，不能视为整个工作区容量保障。 | 先统计并分类“可重建缓存/过期预览/恢复所需记录/备份”，定义容量和保留期限、预览清理范围。任何待恢复清单和备份禁止按日期直接删除。 |

## 4. 低严重程度：可安排在修复后的清理

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| L01 | `web/vite.config.js`、`web/vite.config.d.ts`、`web/tsconfig.node.json` | **静态确认**：TypeScript 配置旁的生成 JS/声明也入 Git，形成三个配置文件；当前内容一致，但以后存在误改和解析入口混淆。 | 明确唯一配置源，调整 node tsconfig 输出/无输出策略，清除并忽略生成物，验证全新构建后工作区仍干净。 |
| L02 | `web/src/styles.css:83`、`:107`、`:2518` | **静态确认**：`.ai-results-pagination`、`.archive-list-pages` 在当前应用源码已无使用，分页统一后仍保留。 | 删除已确认无引用规则；动态类名、主题覆盖不能靠一次字符串扫描批量删除。 |
| L03 | `src/tangerine_photo_assistant/metadata.py:105` | **静态确认**：`UnavailableMetadataReader` 全仓仅定义一次，没有调用方。 | 核实不是公开外部 API 后删除，保留当前实际使用的 Pillow 降级路径。 |
| L04 | `README.md:3`、`:22`、`:187`、`:210`；`docs/CURRENT_STATE.md:129` | **静态确认**：四张 Mac 样片/旧图库数量/v4 描述/“复制只能通过迁移”等表述与扩展演示、后续导入、v5 和相册归档并存，部分缺日期限定；CURRENT_STATE 的“没有后台预取”易与下文有限前端预加载混淆。 | README 写当前产品行为，历史数量标采样日期或移到运行记录；区分后端全库预生成和前端有限预加载。 |
| L05 | `README.md:20`、`docs/CURRENT_STATE.md:10`、`config.example.toml`、`scripts/windows_app.spec:8` | **静态确认**：仓库保存个人盘符、设备环境和生日主题等记录，README 又被打进发布包。这些不是密钥，但不适合作为公共发行材料默认内容。 | 个人运行记录与公共使用文档分离；公共配置用中性示例。内部安全边界可继续保留，不机械删除所有绝对路径。 |
| L06 | `web/src/components/Navigation.tsx:50`；`web/src/features/similarity/BurstsView.tsx:237` | **静态确认**：部分控件声明 tablist/tab，但未完整实现焦点游走/方向键和面板关联；部分 tablist 内按钮甚至没有对应 tab 语义。 | 切换筛选可用 group+aria-pressed；真正页签才统一完整键盘/ARIA 行为，做键盘验收。 |
| L07 | `web/package.json:12` | **静态确认**：Vite、TypeScript、React 插件放在运行 dependencies；实际属于构建工具。未发现足够证据认定存在可直接删除的第三方依赖。 | 移到 devDependencies 并重新锁定；React/ReactDOM 保留运行依赖，确认构建环境安装 dev 依赖。 |
| L08 | `pyproject.toml:41`；`.github/workflows/quality.yml:43` | **静态确认**：配置保留 BLE001/TRY004/SIM118/I001/DTZ 等忽略说明，但没有启用相应规则族；容易让维护者以为已执行这些检查。CI Ruff 只覆盖 src/tests，本次额外检查 scripts 也通过。 | 删除无效忽略或有计划地启用对应规则；把 scripts 纳入门禁，避免为“全绿”一口气添加大量全局豁免。 |

## 5. 用户给定清单逐项检查结果

| 检查项 | 结果 |
|---|---|
| TODO/FIXME/HACK/XXX | 跟踪文本中未发现这些遗留标记。没有标记不等于没有未完成工作，路线图仍有明确待办。 |
| console.log/debugger/临时输出 | 跟踪源码未发现上述前端调试输出；Python print 主要用于 CLI、worker 进度和基准/冒烟工具，应保留。未把正式日志和用户命令输出当作垃圾。 |
| 未使用函数/组件/变量/资源/依赖 | 确认一个无调用类、两组旧分页 CSS、两份生成配置文件。TypeScript noUnusedLocals 和 Ruff 通过；没有证据证明所有其他导出或资源都被使用，也不据此批量删除。 |
| 临时配置、脚本、环境变量 | runtime 中确有历次验收/导入/构建产物，受忽略规则保护；不能直接判定可删除。正式源目录未发现足够依据认定可删除的“一次性脚本”。TANGERINE_CONFIG、TANGERINE_BUILD_INFO、PYTHON_BIN 有实际用途。 |
| 敏感信息 | 跟踪文本特征扫描未发现真实 API 密钥、密码或私网地址；命中的 token 赋值是测试假值。127.0.0.1 为预期本地服务地址。发现个人绝对路径/主题记录，见 L05。未审计 Git 历史与被忽略本机秘密。 |
| 注释与实现不符、描述性注释、注释掉代码 | 已列文档/配置语义偏差。未发现值得单列的大段注释掉实现。安全边界、事务、取消、预加载的解释性注释是必要维护信息，不建议按“描述性内容”统一删除。 |
| 测试/README/文档同步 | 门禁数字与当前运行相符，局部业务说明陈旧；文档本地 Markdown 链接扫描未发现失效链接。测试缺失的是异常业务场景和真实布局，不是缺少更多同构断言。 |

## 6. 验证结果与复现边界

- Python：`python -m unittest discover -s tests`，162 项，成功；其中 1 项真实 Windows 符号链接测试因权限跳过，即 161 项执行通过。
- Ruff：`ruff check src tests` 通过；额外 `ruff check scripts` 通过。
- 前端：20 个测试文件、97 项全部通过。
- 生产构建：TypeScript + Vite 通过。
- 六个隔离观察：读取失败仍 complete；评分与照片 ID 脱离；仅标签记录被级联删除；补 RAW 改旧相册；非法工作区校验前建库；归档前备份归档后匹配 1→0。
- 没有修改业务源码、测试或配置。测试及构建生成的依赖缓存、dist 属正常被忽略产物；本报告也位于被忽略 runtime，不提交或推送。
- 以上是当前代码缺陷的复现，不表示正式生日相册或正式库已发生这些损失。正式库是否受影响应另做受控只读审计，不能用本报告推断历史损坏。

## 7. 可执行的修改顺序

### 第 1 批：数据安全回归与最小修复（最高优先级）

1. 把 H01–H05 的隔离复现转成正式回归测试，先确认旧代码失败。
2. 先修 H04 校验顺序，再修 H01 扫描覆盖范围。
3. 联合设计 H02/H03/M01 的身份、补全与导入归属，避免三个补丁相互抵消。
4. 处理 H05 备份身份及旧格式兼容；如果要迁移 schema，必须先备份、验证旧版本升级/回退和外键。
5. 验收：人工数据逐表前后比较、ID 稳定、异常重试无重复；通过完整门禁才提交。严禁拿真实照片制造缺失/改名。

### 第 2 批：恢复与任务可控性

1. 修 M03 坏记录处理、M05 跨文件恢复失败补偿。
2. 为 ExifTool 增加超时和可取消边界，修 GPU 竞争检测的未知状态。
3. 量化慢导出下写锁等待，保持安全关闭协议的前提下缩小锁范围。
4. 明确 M04 的恢复操作手册；安全放弃/撤销若需新增入口，先审设计，不在清理中偷偷加入。

### 第 3 批：界面与查询一致性

1. 统一导出限制和错误反馈（M10/M12）。
2. 给差异、相似组等补请求代次保护（M11）。
3. 修评分排序唯一键（M13），调整归档状态文案（M14）。
4. 处理页签键盘语义（L06）；用隔离数据验证多页、空页、请求失败、快速切换、窄窗口和主题。

### 第 4 批：低风险清理与依赖可复现

1. 删除有证据的死 CSS/无调用类和生成 Vite 配置，保持源码配置唯一。
2. 整理依赖分类、锁定与 Mac 环境更新检查；不无理由升级所有依赖。
3. 修 README 与运行记录的边界；分离公共发行材料与个人现场记录。
4. 清理后全新构建、完整门禁、核对 diff/暂存区，保证工作区不产生新的跟踪文件变化。

### 第 5 批：有边界的结构重构与保留策略

1. 有测试保护后先拆一个领域 router/controller，不同时修改 API、SQL、CSS 和业务语义。
2. 分离数据库迁移和连接；验证历史 schema 升级后再替换连接入口。
3. CSS 先建立少量视觉基线再拆分，保留现有风格。
4. 对 runtime、导出包、预览计划、备份先生成清理预览和大小统计；实际清理另行确认，不删除恢复所需数据。

每批交付都需：问题编号、变更范围、隔离失败/正常路径结果、Python/Ruff/前端测试/构建结果、提交前 diff 与暂存文件核对。数据安全问题修复不能与数千行纯格式化混成一次提交。

## 8. 新功能/较大重构建议（单独列出，不纳入直接清理）

| 建议 | 理由 | 范围限制 |
|---|---|---|
| 持久照片身份及备份格式兼容迁移 | H02/H05 暴露路径键不足以承载长期人工数据身份。 | 属数据模型重构；先比较稳定 UUID、别名与指纹策略，避免仅凭文件名合并。 |
| 归档恢复检查与分阶段安全撤销 | M04 的不可恢复源/目标问题需要用户可理解的出口。 | 涉及真实文件操作；必须有计划、预览、备份及阶段约束，另行授权。 |
| 补全便携人工数据覆盖范围 | M06 的手动相册/归属等未进入当前格式。 | 先明确备份用途；不把日志、模型结果和照片都塞入“便携人工备份”。 |
| OpenAPI 生成前端契约、领域 router/hook 拆分 | 减少长期手写接口漂移和巨型组件耦合。 | 不改变产品功能；一次迁移一个领域，保留兼容。 |
| 隔离浏览器回归与视觉基线 | 当前 jsdom 无法证明布局、滚动、焦点和缩放正确。 | 优先少量关键链路，无需新建复杂测试平台或操作正式照片。 |
| 持久化大批量导出任务 | 若慢导出仍明显影响交互，可解决 M09。 | 先测量；不因此扩展“全部匹配”批量或自动清理照片。 |

当前审查和规划已完成，以上修改均尚未开始。建议下一项只授权“第 1 批：数据安全回归与最小修复”。用户暂时无需执行验收操作；无需为本次审查重新导入或重新归档照片。
