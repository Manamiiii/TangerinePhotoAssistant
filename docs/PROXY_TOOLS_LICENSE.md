# proxy-tools 0.1.0 许可来源核对

核对日期：2026-11-03。结论：已找到与实际发行源码匹配、且早于 PyPI 发布的上游 BSD 许可原文。
本项目按该原文保留版权、再分发条件和免责声明；这不是由本项目重新授权，也不宣称上游 MIT 元数据已经修正。
本项不再作为当前候选包的“缺少上游许可依据”阻塞。

## 可复核证据

- [PyPI 0.1.0](https://pypi.org/project/proxy-tools/0.1.0/) 于 2014-05-05 21:02:24 UTC 上传，只有源码发行包。
  `PKG-INFO`、`setup.py` 标 MIT；源码头写 BSD；发行包文件清单没有 LICENSE。差异确实存在。
- [上游提交 77369e4](https://github.com/jtushman/proxy_tools/tree/77369e4d321ed7b10d7b6e4885d7fe7a7ec2dfb7)
  的提交时间为 2014-05-05 20:40:18 UTC，早于该上传。其 `proxy_tools/__init__.py` 与发行包、
  本项目安装的模块逐字节相同。上游无发行 tag，因此这里不把它冒称为唯一的“发布提交”。
- 同一提交的 [LICENSE.txt](https://github.com/jtushman/proxy_tools/blob/77369e4d321ed7b10d7b6e4885d7fe7a7ec2dfb7/LICENSE.txt)
  明确列出 Armin Ronacher（2013）与 Jonathan Tushman（2014）版权，以及源码、二进制再分发条件。
  许可文件最晚在 `ccd35a569b95bec271a59890780c7821756c548a`（发布日 17:11:55 UTC）已是相同内容。
- 完整抓取的上游 master 历史截至 `db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6` 共 14 次提交；
  源码匹配不只出现在最新 master，发布前的提交也匹配，所以不是借用后来不明范围的许可。

| 核对对象 | SHA-256 |
|---|---|
| PyPI `proxy_tools-0.1.0.tar.gz` | `ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010` |
| `proxy_tools/__init__.py` | `d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be` |
| 上游 `LICENSE.txt` 原始字节 | `a428fb8a2e762af3eb0a6edbbb88e9b42ccfee80fd9b423958bcacf9b9abbfe4` |

机器可读来源与固定下载 URL 见 `assets/licenses/proxy-tools-0.1.0-provenance.json`。
许可原文见同目录 `proxy-tools-0.1.0-LICENSE.txt`。保留原文件末尾拼接笔误和占位符，
不“修复”为另一份模板，不擅自将其规范化成一个无差异的 SPDX 标识。

## 打包处理与边界

Setup 和 Portable 的 `_internal/ThirdPartyNotices/proxy-tools/` 包含上游 LICENSE、来源 JSON、
本说明、原始包元数据和带版权头的模块源码。构建时验证版本、模块源码 SHA-256 和许可 SHA-256，
任何一项变化都拒绝沿用旧审查结论。对应 Source.zip 包含相同许可与证据记录。

此前附带的 Werkzeug 0.9.6 BSD 文本仅作为来源补充保留；未核实 proxy-tools 抽取自 Werkzeug 的哪个精确版本，
不能把该补充文本当成 proxy-tools 自身许可，亦不声称两者有精确版本对应关系。
当前结论依据的是 proxy-tools 自己在相同源码所在历史提交中提供的明确授权原文。

MIT/BSD 元数据冲突及 sdist 漏装 LICENSE 是上游现状，本轮没有修改上游、代替作者重新授权或发送消息。
后续依赖升级需重新审查。本项目整体 GPL-3.0-only 不改变该组件自身的许可条件。
