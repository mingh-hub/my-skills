# CLS Iframe 跨域工作流（历史废弃）

本文件保留历史结论：Argus 的 CLS iframe 加载自 `datasight-1300455117.internal.clsconsole.tencent-cloud.com`，与 `argus.xhdev.xyz` 不同源，父页面 JS 无法穿透 iframe 操作查询框或结果区。

## 当前规则

- 不再使用 Hermes 云端 `browser_*` 工具访问 Argus/CLS。
- 不再通过 Argus iframe 操作 CLS。
- 不再把本地 cookie 注入云端浏览器。
- 当前唯一推荐方式：通过 AppleScript 控制用户本地 Chrome 的 Codex 专用窗口，直接打开 CLS URL。

## 当前入口

使用主流程：

1. 组装 CLS URL，包含 `topic_id`、`time`、`queryBase64`。
2. 复用 URL 含 `datasight-1300455117.internal.clsconsole.tencent-cloud.com` 或 `argus.xhdev.xyz` 的 Chrome window。
3. 找不到时创建新 window，并记录 `id of window`。
4. 后续导航、`document.body.innerText` 提取、加载更多点击都按 window id 定向执行。

具体模板见：

- `../SKILL.md` 的 `0.1 浏览器规则` 和 `4.2 CLS 查询执行方式`
- `cls-local-chrome-access.md`
- `cls-dom-extraction.md`

## 历史结论

- iframe 跨域限制是真问题，但通过直接打开 CLS URL 可以绕过。
- 修改 iframe `src`、在 iframe 外层点击、云端浏览器注入 cookie 都不再作为推荐路径。
- 如遇 CLS 页面挂死或状态错乱，优先新建/复用本地 Chrome 专用窗口重新打开完整 CLS URL。
