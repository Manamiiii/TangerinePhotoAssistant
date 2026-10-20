# 2026-10-20 自主导入部署与正式库核验

## 代码与自动门禁

- 功能提交 `2d0671f`：独立导入页面、持久批次、限定范围索引、视频/附属文件归属与归档。
- Python 214 项：213 通过、1 项因 Windows 建链权限跳过；链接边界仍有模拟回归。
- 前端 113 项、Ruff（src/tests/scripts）、TypeScript 与生产构建通过。
- 另行复核 15 项归档回归。所有写入实验使用自动清理的临时目录/数据库，未启动模型。

## 正式库升级

- 启动前健康和任务接口不可连接，端口未监听；正式数据库 schema 35。
- 使用 ServiceClient 的隐藏后端启动协议加载 `2d0671f`，dirty=false；未使用桌面启动入口、浏览器或鼠标。
- 自动升级 35→36，新增 `import_jobs` 和 `album_files`；两表均为空。
- 自动备份保留于：
  `D:\PhotoLibrary\Backups\AnalysisDatabase\catalog-pre-schema36-from35-20261020-031506-313793.sqlite3`。
- 升级前逐表记录行数和完整行内容摘要；备份与升级前快照完全一致。
  主库除 schema_info 外的全部 50 张既有表，行数及内容 SHA-256 均不变。
- 主库 schema 36、备份 schema 35；两者 `integrity_check=ok`，`foreign_key_check` 均为 0。
- Capture 数仍为 14,713。未复制、移动、删除、重命名真实照片，未写 XMP 或操作 Lightroom。

## 只读接口核验

- `127.0.0.1:8765` 健康为 ok、local-only、schema 36；任务 idle；启动审计补齐处理 0 项。
- 图库可见照片 14,557 张，相册 53 个；前两页各 40 张且 ID 无交集。
- 新导入历史为空；相册筛选/类型及新文件清单接口正常；网页入口和引用的静态资源返回 200。
- 国庆相册 54 的索引归档状态为 852 文件、0 待整理路径、pending=false。
  这是索引状态核对，没有重读原图进行物理完整性证明，也没有自动把历史遗留视频关联到相册。
- 服务保持运行，新功能可在用户自行刷新已有页面后使用；未重制独立安装包。

逐表摘要与接口结果保存在 `runtime/maintenance/import-schema36-*-20261020.json` 和
`runtime/maintenance/import-ui-api-verified-20261020.json`，属于正式维护凭据，保留而不提交个人数据。

## 尚需用户验收

自动检查不替代真实窗口布局、原生目录选择以及自主导入操作体验。请按
[IMPORT_ACCEPTANCE.md](IMPORT_ACCEPTANCE.md) 的必要检查，用下一批真正准备导入的照片走一次流程。
不要求新建测试图库，也不要为验收故意中断服务、拔卡或损坏文件。
