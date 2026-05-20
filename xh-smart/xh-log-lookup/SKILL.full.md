# xh-log-lookup 历史版本说明（已压缩）

本文件原保存 `xh-log-lookup` 重构前的完整长版说明。旧内容包含 Hermes 云端 `browser_*`、CodeMirror 注入、云端浏览器 cookie 注入等历史方案，这些路径已经废弃，避免继续保留为可复制模板。

当前实现请以以下文件为准：

- `SKILL.md`：主控流程和强制规则
- `tools/cls_query.py`：CLS URL 构造、本地 Chrome 专用窗口、加载更多、全文提取
- `references/cls-local-chrome-access.md`：本地 Chrome 访问方法
- `references/cls-dom-extraction.md`：DOM 文本解析和 CK/CS 合同号提取
- `references/cls-query-pitfalls.md`：当前高频坑
- `references/feishu-card-template.md`：飞书卡片规则

历史结论中仍有效的部分已经迁移到 references；不要从本文件恢复旧浏览器操作流程。
