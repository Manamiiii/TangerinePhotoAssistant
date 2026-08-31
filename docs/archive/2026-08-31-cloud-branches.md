# 2026-08-31 Cloud 开发与已合并分支归档

## 同步范围与证据

- 本地工作区开始时干净，`main` 为 `21464cf25dce847a5555669c7a4014dc0a54b6c9`。
- `git fetch origin --prune` 后远程 `main` 为
  `afba32242e5c92e4fee5c51e18ec3d65a4fc136d`；本地已通过 `git merge --ff-only origin/main` 更新。
- 新增 4 个开发提交和 1 个合并提交，改动仅涉及 6 个前端文件（153 行新增、27 行删除）。
  无后端、schema、依赖、模型、样例照片或正式数据变更。
- [PR #3](https://github.com/Manamiiii/TangerinePhotoAssistant/pull/3) 的合并关系由 Git 提交验证。
  本机 GitHub CLI 未登录，未读取 PR 评论或在线 CI 结果；本记录不声称完成在线讨论审阅。
- 现存开发分支均为 `origin/main` 的祖先，无未合并远程分支；没有其他工作树占用这些分支。

## 本次 Cloud 改动

| 提交 | 内容 |
| --- | --- |
| `b3553f7` | 连续看图、相邻详情与图片预加载、跨页导航、缩放拖动及关闭后卡片定位 |
| `0f83019` | 折叠相似组仅保留可见代表图参与连续浏览，另设“展开组”入口；新增导航工具测试 |
| `bf562ea` | 输入框和 Tab 的键盘焦点改为中性色，调整图库搜索框焦点反馈 |
| `85f0d81` | 恢复电脑全屏切换，压紧状态标签并避免单个标签折行 |

核心入口变化：非批量模式下点击图库缩略图直接沉浸查看；需要组内选片时点击“展开组”。
跨页导航沿用当前图库查询条件；照片预览仍是缓存缩略图，不是 RAW 解码或原图像素级检查。

## 审阅发现：尚未修复

以下为当前代码路径的静态结论，未启动浏览器重现实验。自动测试通过不代表这些交互已验收。
本轮只更新、审阅、归档和清理分支，不额外改写已合入功能。

### 优先修复

1. **跨页请求缺少完整的过期保护。** `web/src/main.tsx` 的 `navigateDetail` 在获取下一页后
   才递增 `captureRequestSequence`。如果等待期间关闭详情或触发历史导航，旧请求仍能更新图库
   并申请新代次，进而重新打开详情；多次快速翻页也可能按返回顺序覆盖。
   应在首次异步操作前取得代次，并在每次等待后、更新任意状态前校验，同时绑定查询上下文。
2. **组内导航会越界到图库。** 图库中的 `SimilarityPickerModal` 传入的是组内成员 ID，
   但 `navigateDetail` 和前后按钮只依据 `view === "library"` 决定是否跨页。
   组内最后一张可能跳到图库下一页的无关照片。应显式区分图库分页上下文和组内固定上下文。
3. **预加载缓存缺少上限和失效机制。** `detailPrefetch` 的 Map 只在消费或失败时删除，关闭详情
   和人工写入时不清理。反复开关不同照片可积累未消费的完整详情；先前缓存的星级、标签和修图
   方案也可能在后续切换时过时。应仅保留当前相邻窗口，关闭时清理，写后使对应 ID 失效，
   并防止写入前已发出的预加载请求重新填回旧状态。

### 随交互回归处理

- 预加载图片使用 `thumbnail_url`，实际详情图片默认增加 `retry=0`，URL 不一致，不能依赖
  浏览器复用同一缓存；应让首次加载与预加载使用相同 URL，仅失败重试时改变 URL。
- 拖动后按减号或滚轮缩回 100% 未重置平移量，此时又禁止拖动，画面可能偏离中心；“适应”可
  暂时恢复。应在回到适应倍率时归零位置，并处理 pointer cancel/lost capture。
- 图片失败重试的定时器未在换图或关闭时清理，旧图失败可能改变新图的重试状态。
- `content-visibility` 为所有图库布局设置统一的 `280px 340px` 占位；列表实际行高不同。
  需要实测长列表滚动、回到原卡片和滚动条稳定性；“展开组”的绝对定位也需检查列表模式遮挡。
- 全屏 Promise 未处理拒绝，需验证 Windows Chrome/Edge 与 Mac Safari 的成功、退出和不支持
  情况，避免失败时没有反馈。

### 最小专项验收

1. 使用隔离样例，分页大小设小，验证第一页/中间页/末页和前后翻页；折叠组不隐式展开成员。
2. 在慢网络下跨页后立刻关闭详情、连续按方向键、返回历史：旧请求不得重新打开或覆盖新视图。
3. 在图库“展开组”中打开成员，首尾应停在该组，不进入图库其他页。
4. 缩放、拖动、回到 100%、适应、切换照片、图片加载失败和全屏退出均能恢复正常显示。
5. 先预加载相邻图，再给该图改星级/标签/参数方案并来回浏览，不能出现旧值。
6. 列表/小图/中图/大图分别检查“展开组”、状态标签、键盘焦点以及关闭详情后的定位。

## 已合并分支清理清单

清理只删除下列分支引用，不删除 main 中的文件或提交。旧分支不属于本次新增 Cloud 功能，
在此一并记录已合并的遗留引用，避免把旧工作误报为本次新增。

| 分支 | 清理位置 | 工作摘要与 main 关系 |
| --- | --- | --- |
| `codex-757d02` | 远程 | 本次 Cloud 连续看图开发，合并提交 `afba322` |
| `codex/ci-quality-gates` | 本地、远程 | Linux/Windows CI 门禁和手动 Mac 冒烟，合并提交 `284ef41` |
| `codex/large-library-baseline` | 本地、远程 | 10k/50k/100k 合成性能基线及统计/查询优化，合并提交 `5eaa074` |
| `codex/schema27-acceptance` | 本地、远程 | schema 27 阶段验收文档和 CI 路径配置，合并提交 `4d4ec9d`；现行清单已为 schema 32 |
| `codex/copilot-optimization-integration` | 本地（远程此前已删除） | 大库分页、模型风险审计、完整性调查、本地 API 防护、深链接和请求保护集成，合并提交 `d63111b` |
| `copilot/business-function-analysis` | 远程 | 历史 feature 拆分、相册/评价服务及详情/分析查询抽离；分支 tip 已在 main 祖先链中 |

完整 tip 用于核验和恢复：

```text
codex-757d02                           85f0d81575fd2b0ff95e69fa9064bbbe429fb289
codex/ci-quality-gates                 c6731f95eea33b9cd7be0d133e9777016db6f251
codex/large-library-baseline           14cc3f4ebfa54f4736ca1fca32c65729295edfea
codex/schema27-acceptance              2af12552f464d4976629f53597297725fd34f36a
codex/copilot-optimization-integration 948cfd06437244cafe62720806644bd0fac8bc31
copilot/business-function-analysis    3a3e2b720e38b3dfee0c21411558ab2f86abb50d
```

删除前逐个验证 `git merge-base --is-ancestor <tip> main`，再次核对远程 tip 没有变化。
本地只使用 `git branch -d`，远程使用普通 `git push origin --delete`；不 force push。
若需恢复，可用 `git branch <原分支名> <完整tip>`，再按需 `git push -u origin <原分支名>`。
所有 tip 都保留在 main 的可达历史中，不依赖本机 reflog。

## 本地回归与安全边界

- Python：`python -m unittest discover -s tests -v`，94 项通过。
- 前端：`npm test`，4 个文件、8 项通过；新增的 2 项仅覆盖代表图 ID 和分页偏移计算，
  未覆盖上述异步交互。
- 静态检查：`python -m ruff check src tests` 通过。
- 生产构建：`npm run build`（TypeScript + Vite）通过。
- 正式健康/任务接口均不可达，未启动或结束服务，未运行正式库迁移或完整性检查；旧文档中
  的 schema 26 / 13,809 张为此前记录，不能当作本次数据库核验结论。
- 测试使用测试代码管理的隔离临时数据；未操作真实照片、XMP、Lightroom、ComfyUI 或模型任务。
