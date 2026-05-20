---
name: xh-sso-access
description: 内部 Web 应用 SSO 会话处理。Use when Argus, JANUS, PMP, boss-mgr, droolsCms, or internal pages need login/session recovery, local Chrome cookie verification, Feishu QR fallback, or AppleScript-controlled dedicated Chrome window access.
metadata:
  hermes:
    version: 2.0.0
    platforms: [macos]
    tags: [sso, argus, janus, pmp, local-chrome, cookie]
---

# xh-sso-access — 内部 SSO 会话

统一处理内部 Web 应用的 SSO 认证和会话验证。CLS 日志查询本身属于 `xh-log-lookup`；本 Skill 只负责 Argus/JANUS/PMP 等会话准备。

## 强制规则

- 内部 Web 应用优先使用用户本地 Chrome，因为本地已有 SSO cookie 和会话。
- 禁止用 Hermes 云端 `browser_navigate` 直接访问内部 SSO 页面。
- 禁止默认操作 `active tab of front window`；必须复用或创建 Codex 专用 Chrome window，并通过 window id 定向操作。
- Argus/CLS 访问不再把本地 cookie 注入云端浏览器。
- 需要本地窗口、cookie 验证或 cookie 提取时，优先使用 `tools/argus_session.py`。

## 触发条件

- Argus/CLS 跳到 JANUS 登录页或二维码页。
- 用户要求登录 PMP、boss-mgr、droolsCms、Argus 等内部页面。
- `xh-log-lookup` 查询前发现本地 Chrome 会话失效。
- 需要验证本地 Chrome 是否有 `argus-token`。

## SSO 平台识别

| 平台 | 认证方式 | 适用应用 | 参考 |
|------|----------|----------|------|
| PMP SSO | RSA 加密密码登录 | boss-mgr, droolsCms, PMP | `references/pmp-sso-login.md` |
| JANUS SSO | 飞书扫码，无密码入口 | Argus 日志平台 | `references/janus-argus-sso.md` |

两套 SSO 完全独立，不要混用 cookie 或登录流程。

## 决策流程

1. 先确认应用域名：Argus/JANUS 走本地 Chrome 专用窗口；PMP 类应用按 PMP SSO 参考。
2. 如果是 Argus/CLS，运行 `argus_session.py ensure-window`，复用或创建专用窗口。
3. 运行 `argus_session.py verify-cookie` 检查本地窗口是否有 `argus-token`。
4. 如果 cookie 存在，回到 `xh-log-lookup` 继续查 CLS。
5. 如果 cookie 缺失，按 `references/janus-argus-sso.md` 的飞书扫码 fallback。
6. 如果是 PMP/boss-mgr/droolsCms，读取 `references/pmp-sso-login.md`，优先用 requests 登录和本地窗口验证。

## Argus 工具

### 创建或复用专用窗口

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-sso-access/tools/argus_session.py ensure-window
```

输出：

```json
{"window_id": "12345", "url": "https://argus.xhdev.xyz/favicon.ico"}
```

### 验证 Argus cookie

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-sso-access/tools/argus_session.py verify-cookie --window-id 12345
```

输出中的 `has_argus_token=true` 表示本地 Chrome 可继续访问 Argus/CLS。

### 提取 cookie（仅诊断或扫码后确认）

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-sso-access/tools/argus_session.py extract-cookie --window-id 12345
```

`extract-cookie` 会通过本地 HTTP server + XHR 接收 cookie，避免 AppleScript 返回值截断。不要把输出注入 Hermes 云端浏览器。

## 降级和人工交互

- 如果本地 Chrome 会话失效，导航专用窗口到 Argus，让 JANUS 页面显示二维码。
- 必须在 JANUS 页面自身截图，不要直接导航到 `passport.feishu.cn`。
- 请求用户扫码后，等待回调完成，再运行 `verify-cookie`。
- 用户只在手机端时，流程是：专用窗口打开 JANUS QR → 截图发飞书 → 用户扫码 → 验证本地窗口 cookie → 回到日志查询。

## 注意事项

- 用户使用 Chrome Profile 2 的历史记录只作为诊断线索；不要默认启动独立 profile，避免丢登录态。
- `argus-token` 是 JWT，有过期时间；过期时必须重新扫码或重新提取。
- AppleScript 可能定位到无头 Chrome 时，先确认窗口列表；不要直接杀进程，除非用户明确允许。
- PMP RSA 登录细节、JANUS XHR cookie 提取细节都在 references 中；主流程不要复制大段代码。

## References

- `references/janus-argus-sso.md`：JANUS/Argus 登录、扫码和 cookie 提取细节
- `references/applescript-cookie-extraction.md`：AppleScript 返回值截断和 XHR workaround
- `references/pmp-sso-login.md`：PMP SSO RSA 登录、redirectUri、cookie 域
- `tools/test_encrypt.py`：旧 PMP 登录实验脚本；优先参考 `pmp-sso-login.md`
