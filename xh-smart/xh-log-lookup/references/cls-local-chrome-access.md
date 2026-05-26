# 备用：CLS 本地 Chrome 访问方法

## 何时读取

当 Hermes 内置浏览器登录态不可用、页面操作失败、需要脚本自动加载更多/批量全文提取，或需要手写 AppleScript 诊断 CLS 页面时读取。常规查询优先使用 Hermes 内置浏览器直接打开 CLS URL。

## 目录

- 场景和前提
- 标准工作流
- 中文查询注入
- 常见问题
- 备用 URL 构造

备用路径通过 AppleScript 控制用户本地 Chrome 直接访问 CLS URL。不要通过 Argus iframe 穿透操作 CLS。

## 场景

- Hermes 内置浏览器登录态不可用或页面操作失败
- 查询含中文（queryBase64 不支持中文）
- 需要脚本自动加载更多、批量全文提取或本地 DOM 诊断

## 前提

用户本地 Chrome 已登录 Argus/CLS（有 argus-token cookie）。

## 标准工作流

### 1. 创建或复用 CLS 窗口

不要操作 `front window`。先复用已打开的 CLS/Argus 窗口；找不到时创建新窗口，并记录 window id。调查结束后用 `cls_query.py --close` 关闭：

```bash
CLS_WINDOW_ID=$(osascript <<'APPLESCRIPT'
tell application "Google Chrome"
    set targetUrl to "URL"
    set targetWindow to missing value
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "datasight-1300455117.internal.clsconsole.tencent-cloud.com" or u contains "argus.xhdev.xyz" then
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
```

URL 格式：
```
https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id=f6748b3a-8ab8-4191-b848-cb90b1598901&time=now-30d,now&queryBase64={base64_query}
```

- `topic_id=f6748b3a-8ab8-4191-b848-cb90b1598901` = logsvr-prod（生产）
- `time=now-30d,now` = 最近 30 天（调整范围）
- `queryBase64={base64}` = 纯 ASCII 查询（不支持中文）

### 2. 定向导航到 CLS 搜索页

如果已经有 `CLS_WINDOW_ID`，后续只操作这个窗口：

```bash
osascript -e "tell app \"Google Chrome\" to set URL of active tab of (first window whose id is ${CLS_WINDOW_ID}) to \"URL\""
```

### 3. 等待页面加载

```bash
sleep 5
```

页面会自动选择主题（应用日志 / logsvr-prod）并加载。

### 4. 提取日志信息

```bash
# 页面标题和 URL
osascript -e "tell app \"Google Chrome\" to return (title of active tab of (first window whose id is ${CLS_WINDOW_ID})) & \"|||\" & (URL of active tab of (first window whose id is ${CLS_WINDOW_ID}))"
```

```applescript
# 提取日志条数
tell app "Google Chrome"
	-- 将 123456 替换为 CLS_WINDOW_ID 的实际值
	set targetWindow to first window whose id is 123456
	set countText to execute active tab of targetWindow javascript "
document.querySelector('h5:not([class])') ? document.querySelector('h5:not([class])').textContent : 'no-count'
"
end tell
```

```applescript
# 提取全文 grep 关键词
tell app "Google Chrome"
	-- 将 123456 替换为 CLS_WINDOW_ID 的实际值
	set targetWindow to first window whose id is 123456
	set bodyText to execute active tab of targetWindow javascript "document.body.innerText"
	-- then parse in shell with grep/sed/awk
end tell
```

### 5. 注入中文查询（React contenteditable）

CLS 使用 React contenteditable div 作为查询编辑器（非 CodeMirror）。

```applescript
tell app "Google Chrome"
	-- 将 123456 替换为 CLS_WINDOW_ID 的实际值
	set targetWindow to first window whose id is 123456
	-- 1. 设置查询文本
	execute active tab of targetWindow javascript "
var el = document.querySelector('[contenteditable=true]');
if (el) el.innerText = 'serviceName:\"order\" AND message:\"[借款下单]下单请求结果为\" AND message:\"20161002000002677537\"';
"
	-- 2. 触发 React input 事件
	execute active tab of targetWindow javascript "
var el = document.querySelector('[contenteditable=true]');
if (el) el.dispatchEvent(new Event('input', {bubbles: true}));
"
end tell
```

**限制**：innerText + dispatchEvent(input) 能更新显示但可能不触发 React 的 onChange → 搜索按钮可能仍为禁用状态。Enter 键 also may not work. 方案 A（纯 ASCII URL） > 方案 C（全文 grep） > 方案 B（注入）。

### 6. 触发搜索

```applescript
tell app "Google Chrome"
	-- 将 123456 替换为 CLS_WINDOW_ID 的实际值
	set targetWindow to first window whose id is 123456
	-- 查找并点击搜索按钮
	execute active tab of targetWindow javascript "
var btns = document.querySelectorAll('button');
for (var i=0; i<btns.length; i++) {
	if (btns[i].querySelector('svg') || btns[i].innerHTML.includes('search') || btns[i].innerHTML.includes('play')) {
		btns[i].click();
		break;
	}
}
"
end tell
```

## 常见问题

### AppleScript 报错

- `&` 在 URL 中是字符常量，AppleScript 字符串拼接也用 `&`，但引号内 `&` 是字面量，没问题
- 长 AppleScript 最好写成 `.applescript` 文件用 `osascript /path/to/file` 执行
- JS 返回值超过一定长度会被截断

### 写入 AppleScript 文件

URL 中的 `&` 是字符，`+` 是字符，都不需要转义。直接写：

```bash
cat > /tmp/script.applescript << 'EOF'
tell app "Google Chrome" ...
end tell
EOF
osascript /tmp/script.applescript
```

## 关闭 CLS 窗口

调查结束（飞书卡片发送成功后），关闭 CLS 窗口避免累积：

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/cls_query.py --close
```

## 备用方案：直接 URL 查询（纯 ASCII）

当只需要给浏览器打开链接或生成卡片按钮时，构造直接 URL：

```python
import base64, urllib.parse

query = 'serviceName:"order" AND message:"20161002000002677537"'
b64 = base64.b64encode(query.encode()).decode()
url = f'https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id=f6748b3a-8ab8-4191-b848-cb90b1598901&time=now-30d,now&queryBase64={urllib.parse.quote(b64)}'
```

用户可以直接在浏览器中打开此 URL。
