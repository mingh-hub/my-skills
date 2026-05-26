# CLS Iframe 跨域工作流（历史废弃）

本文件保留历史结论：Argus 的 CLS iframe 加载自 `datasight-1300455117.internal.clsconsole.tencent-cloud.com`，与 `argus.xhdev.xyz` 不同源，父页面 JS 无法穿透 iframe 操作查询框或结果区。

## 当前规则

- 不再通过 Argus iframe 穿透操作 CLS。
- 不再把本地 cookie 注入云端浏览器。
- 应直接打开 CLS URL；优先使用 Hermes 内置浏览器，本地 Chrome + AppleScript 作为备用路径。

## 当前入口

使用主流程：

1. 组装 CLS URL，包含 `topic_id`、`time`、`queryBase64`。
2. 优先用 Hermes 内置浏览器直接打开该 URL。
3. Hermes 登录态不可用、页面操作失败或需要脚本自动提取时，改用本地 Chrome 备用窗口。
4. 使用本地 Chrome 备用窗口时，后续导航、`document.body.innerText` 提取、加载更多点击都按 window id 定向执行。

具体模板见：

- `../SKILL.md` 的 `浏览器和 CLS` 和 `CLS 工具`
- `cls-local-chrome-access.md`
- `cls-dom-extraction.md`

## 历史结论

- iframe 跨域限制是真问题，但通过直接打开 CLS URL 可以绕过。
- 修改 iframe `src`、在 iframe 外层点击、本地 cookie 注入远端浏览器都不再作为推荐路径。
- 如遇 CLS 页面挂死或状态错乱，优先重新打开完整 CLS URL；必要时切换到本地 Chrome 备用窗口。
