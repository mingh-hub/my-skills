# JANUS/Argus SSO — 详细流程参考

## 何时读取

当 `tools/argus_session.py verify-cookie` 失败、Argus 跳转 JANUS、需要飞书扫码、或需要解释 cookie 提取限制时读取。常规窗口和 cookie 检查优先使用 `tools/argus_session.py`。

## 目录

- 问题和前置条件
- XHR cookie 提取
- 剪贴板方案现状
- 直接解密方案
- 飞书扫码 fallback
- 注意事项

## 问题

Argus (`argus.xhdev.xyz`) 的 SSO 是 JANUS 统一认证，只支持**飞书扫码登录**，没有账号密码入口。用户本地 Chrome 的 Profile 2 已有登录态（argus-token JWT、TGC-prod），但云端浏览器 session 到期后会自动跳转到 JANUS 二维码页。

## 前置条件

- 用户本地 Chrome **Profile 2** (`~/Library/Application Support/Google/Chrome/Profile 2`) 已登录 Argus（有 argus-token cookie）
- 如果 AppleScript JS 执行被禁用，XHR 方式仍可工作
- macOS 系统，Hermes 运行在同一台机器

## 方法一：AppleScript + XHR HTTP Server（推荐，最可靠）

不需要用户开启「允许 Apple 事件中的 JavaScript」。使用同步 XHR 绕过 AppleScript 返回值截断问题。

### Step 1: 启动本地 HTTP Server 接收 Cookie

```python
import http.server, threading, urllib.parse, subprocess, time

cookie_data = {"value": None}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        cookie_data['value'] = urllib.parse.unquote(body.decode('utf-8'))
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'ok')
    def log_message(self, *args): pass

server = http.server.HTTPServer(('127.0.0.1', 9877), Handler)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
```

### Step 2: 创建或复用 Codex 专用窗口并导航到 Argus 域

```python
ensure_window_script = '''tell application "Google Chrome"
    set targetUrl to "https://argus.xhdev.xyz/favicon.ico"
    set targetWindow to missing value
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "argus.xhdev.xyz" or u contains "datasight-1300455117.internal.clsconsole.tencent-cloud.com" then
                set targetWindow to w
                exit repeat
            end if
        end repeat
        if targetWindow is not missing value then exit repeat
    end repeat
    if targetWindow is missing value then set targetWindow to make new window
    set URL of active tab of targetWindow to targetUrl
    return id of targetWindow
end tell'''
window_id = subprocess.check_output(['osascript', '-e', ensure_window_script], text=True, timeout=10).strip()
time.sleep(2)
```

### Step 3: XHR POST Cookie 到本地 Server

```python
script = f'''tell application "Google Chrome"
  execute active tab of (first window whose id is {window_id}) javascript "var x=new XMLHttpRequest();x.open('POST','http://127.0.0.1:9877/',false);x.send(encodeURIComponent(document.cookie))"
end tell'''
subprocess.run(['osascript', '-e', script], timeout=15)
time.sleep(1)
server.shutdown()

if not cookie_data['value']:
    print("FAILED: No cookies received")
    exit(1)
```

### Step 4: 解析 Cookie

```python
cookies = {}
for part in cookie_data['value'].split(';'):
    part = part.strip()
    if '=' in part:
        k, v = part.split('=', 1)
        cookies[k] = v

# 关键 cookie:
# - argus-token: JWT, ~490 chars, 有 exp 字段控制有效期
# - TGC-prod: SSO ticket, ~36 chars
# - user_name: minghai
# - isAdmin: 0
```

### Step 5: 验证本地专用窗口登录态

```python
# 不要注入到 Hermes 云端浏览器；Argus/CLS 访问统一走本地 Chrome 专用窗口。
verify_script = f'''tell application "Google Chrome"
  set targetWindow to first window whose id is {window_id}
  set URL of active tab of targetWindow to "https://argus.xhdev.xyz/favicon.ico"
  delay 1
  return execute active tab of targetWindow javascript "document.cookie.includes('argus-token')"
end tell'''
ok = subprocess.check_output(['osascript', '-e', verify_script], text=True, timeout=10).strip()
if ok != "true":
    print("FAILED: argus-token missing in local Chrome dedicated window")
    exit(1)
```

## 方法二：AppleScript + 剪贴板

要求用户开启 Chrome → 查看 → 开发者 → 「允许 Apple 事件中的 JavaScript」。

```bash
ARGUS_WINDOW_ID=$(osascript <<'APPLESCRIPT'
tell application "Google Chrome"
    set targetUrl to "https://argus.xhdev.xyz/favicon.ico"
    set targetWindow to missing value
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "argus.xhdev.xyz" or u contains "datasight-1300455117.internal.clsconsole.tencent-cloud.com" then
                set targetWindow to w
                exit repeat
            end if
        end repeat
        if targetWindow is not missing value then exit repeat
    end repeat
    if targetWindow is missing value then set targetWindow to make new window
    set URL of active tab of targetWindow to targetUrl
    return id of targetWindow
end tell
APPLESCRIPT
)
sleep 3

osascript -e "tell application \"Google Chrome\" to execute active tab of (first window whose id is ${ARGUS_WINDOW_ID}) javascript \"
  (async () => {
    const c = document.cookie;
    const blob = new Blob([c], {type: \\\"text/plain\\\"});
    const item = new ClipboardItem({\\\"text/plain\\\": blob});
    await navigator.clipboard.write([item]);
  })();
\""
sleep 1

pbpaste > /tmp/argus_cookies.txt
```

### 2026-05-13 更新：剪贴板方案现状

所有剪贴板方案在 Chrome v148 上已验证失败：

| Approach | Result | Root Cause |
|----------|--------|------------|
| `navigator.clipboard.write` | ❌ `Document is not focused` | JS clipboard API requires active user focus |
| `navigator.clipboard.writeText` | ❌ Same error | Same focus requirement |
| `document.execCommand('copy')` | ❌ Returns `false` | Deprecated API blocked without user gesture |
| `document.title` 赋值 | ❌ SPA 覆写 | Argus React/Vue 在几秒内覆写 document.title |

结论：方法二目前不可靠，优先使用方法一（XHR HTTP Server）。

## 方法三：browser_cookie3 直接解密

当 AppleScript 不可用时，从 Chrome cookie 数据库直接解密。

```python
import browser_cookie3

cj = browser_cookie3.chrome(
    cookie_file='/Users/user/Library/Application Support/Google/Chrome/Profile 2/Cookies'
)
for cookie in cj:
    if 'xhdev.xyz' in cookie.domain and cookie.name == 'argus-token':
        print(cookie.value)
```

**Pitfall:** macOS 上会触发钥匙串 GUI 弹窗（`security find-generic-password` 或 AES-256-GCM 解密都需要 Keychain 授权），用户不在电脑前时无法使用。

## 方法四：飞书扫码（最后手段）

当所有本地 cookie 提取方案都失败时：

1. 用 Codex 专用 Chrome 窗口导航到 `https://argus.xhdev.xyz` → 自动跳转 JANUS
2. **必须在本地专用窗口的 JANUS 页面（含 iframe）截图**，不要直接导航到 `passport.feishu.cn`
3. 发送截图请求用户扫码
4. **不要导航离开 JANUS 页面**，等待回调
5. 轮询 URL 变化检测扫码完成
6. 提取 `argus-token` cookie

### 扫码失败模式

- **跳转到 about:blank**：回调链断裂，通常因为直接导航到了 `passport.feishu.cn` 而非在 JANUS iframe 中扫码
- **二维码过期**：默认有效期约 5 分钟，超时需刷新页面重新获取

## 应急流程：用户在手机端

当云端和本地 Chrome 会话都过期，用户只在手机上时：

```
AppleScript(导航本地 Chrome → JANUS QR)
  → screencapture(截图)
  → MEDIA:(发飞书)
  → 用户手机扫码
  → AppleScript(提取新 cookie)
  → 复用本地专用 Chrome 窗口继续访问 Argus/CLS
```

QR 回调在本地 Chrome 完成，与扫码设备无关。

## Argus 页面 title 含 Cookie（备用提取）

Argus CLS 页面的 `document.title` 会被设为完整 cookie 字符串（但 argus-token JWT 会被截断）：

```python
subprocess.run(['osascript', '-e', '''tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t) contains "clsDatasightSave" then
                return title of t
            end if
        end repeat
    end repeat
end tell'''])
```

仅可用于提取短值 cookie（user_name、isAdmin 等），argus-token 不完整。

## 关键注意事项

- **Profile 2**：用户使用 Chrome Profile 2，非默认 profile。所有 cookies 在 `Profile 2/Cookies` 中
- **argus-token 有效期**：JWT 有 `exp` 字段，过期需重新提取。验证方式：注入后导航到 argus.xhdev.xyz 是否显示 dashboard
- **多 Chrome 实例**：AppleScript 可能定位到 Hermes 无头 Chrome，用 `pkill -f "headless.*chrome"` 清理
- **AppleScript index 错误**：不要用 `set index of w to 1`，直接在 tab 上执行 JS
- **Terminal 截断**：Terminal 输出和 read_file 会截断显示长字符串（显示 `...`），但实际数据完整。用 `len()` 验证字节数
- **Cookie 域**：必须设在 `.xhdev.xyz`，不是应用域
- **CLS 查询**：认证完成后的 CLS 日志查询流程见 `xh-log-lookup` 技能
