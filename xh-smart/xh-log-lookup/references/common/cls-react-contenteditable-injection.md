# CLS React ContentEditable 注入

CLS 的查询编辑器是 React contenteditable div，非 CodeMirror 或标准 textarea。

## DOM 特征

- 编辑器元素位于 query 栏区域，class 包含 `cm-content cm-lineWrapping`，`role="textbox"`
- 查询文本显示在 div 内部，作为裸文本或 `<span>` 子元素
- 搜索按钮：一个带图标的 `<button>`，没有明显 class 标记

## 注入方法（按推荐顺序）

### 推荐方法：String.fromCharCode + execCommand + Enter 提交（支持中文）✅

**唯一支持中文查询的可靠方法。** 步骤：

1. 用 ASCII queryBase64 URL 加载 CLS 页面（让 contenteditable 先渲染，时间窗口一并设好）
2. 找到 contenteditable div：优先 `document.querySelector('[contenteditable=true]')`，若返回 null 则轮询所有元素找 `isContentEditable === true`
3. 用 `String.fromCharCode(...)` 构造中文（避免编码链丢失）
4. 用 `document.execCommand('insertText', false, query)` 注入
5. **通过 KeyboardEvent Enter 提交查询**（比点击 SVG 按钮更可靠，不会出现 click 后无响应的情况）
6. 等待 10-15s 提取页面文本

**完整示例（Python → AppleScript）：**

```python
import subprocess, time

def osa_js(js, wid, timeout=30):
    escaped = js.replace("\\\\", "\\\\\\\\").replace('"', '\\\\"')
    script = f'''
tell application "Google Chrome"
    return execute active tab of (first window whose id is {wid}) javascript "{escaped}"
end tell
'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

# Step 1: 先导航到 CLS（ASCII query，确保 contenteditable 渲染）
import base64, urllib.parse
b64 = base64.b64encode(b'serviceName:"order"').decode()
nav_url = f"..."  # 构造含 topic_id + time 的 URL
osa_js(f"document.querySelector('[contenteditable=true]')?.focus(); ''", wid)
time.sleep(8)

# Step 2: 注入中文查询
# 中文：[借款反欺诈]反欺诈服务调用异常
codes = [0x5b, 0x501f, 0x6b3e, 0x53cd, 0x6b3a, 0x8bc8, 0x5d,
         0x53cd, 0x6b3a, 0x8bc8, 0x670d, 0x52a1, 0x8c03, 0x7528, 0x5f02, 0x5e38]
code_str = ",".join(str(c) for c in codes)

inject_js = f"""
(function() {{
    var el = document.querySelector('[contenteditable=true]');
    if (!el) {{
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {{
            if (all[i].isContentEditable && all[i].tagName === 'DIV') {{
                el = all[i]; break;
            }}
        }}
    }}
    if (!el) return 'NO_CE';
    el.focus();
    el.innerHTML = '';
    var q = 'serviceName:\\\\\\\\"order\\\\\\\\" AND message:\\\\\\\\"'
         + String.fromCharCode({code_str}) + '\\\\\\\\"';
    document.execCommand('insertText', false, q);
    return 'OK: ' + el.innerText;
}})()
"""
osa_js(inject_js, wid)
time.sleep(1)

# Step 3: 使用 KeyboardEvent Enter 提交查询（比 click SVG 按钮更可靠）
enter_js = """
(function() {
    var el = document.querySelector('[contenteditable=true]');
    if (!el) return 'NO_CE';
    el.focus();
    var ke = new KeyboardEvent('keydown', {
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
    });
    el.dispatchEvent(ke);
    return 'ENTER';
})()
"""
osa_js(enter_js, wid)

time.sleep(15)

# Step 4: 提取结果
text = osa_js("document.body.innerText", wid, timeout=60)
```

**常见坑：**
- ⚠️ `contenteditable=true` 属性在 CLS 页面可能不存在（React 内部实现），此时用 `isContentEditable` 属性 + `tagName === 'DIV'` 回退方案
- 注入后不会自动搜索，**必须提交**——两种方式：① KeyboardEvent Enter（推荐，更可靠）② 点击带 SVG 的 button
- 中文不能用字符串字面量，必须用 `String.fromCharCode()`——AppleScript → JS 的编码链会丢失非 ASCII 字符
- `[]` 是 ASCII（0x5b, 0x5d），也要加在 fromCharCode 参数中，不要直接拼字符串
- 注入后等待 10-15s 结果才出来
- `execCommand('insertText')` 前先 `.focus()` + `.innerHTML = ''` 清空旧内容
- AppleScript 的 `&` 字符串拼接会被 terminal 工具误判为 shell 后台操作，AppleScript 中避免 `&` 或使用 Python 拼接后再传给 osascript

**搜索按钮备用方案（Enter 失效时）：**

```javascript
[...document.querySelectorAll('button')].find(b => b.querySelector('svg'))?.click(); 'done'
```

### 方法 2：execCommand 基本操作（仅 ASCII）

```javascript
var el = document.querySelector('[contenteditable=true]');
el.focus();
document.execCommand('selectAll');
document.execCommand('insertText', false, 'new query text');
```

### 搜索按钮定位

```javascript
var btns = document.querySelectorAll('button');
for (var i=0; i<btns.length; i++) {
  if (btns[i].querySelector('svg')) {
    btns[i].click();
    break;
  }
}
```

## 历史

2026-05 更新：CLS 界面从 CodeMirror 迁移到 React contenteditable 组件。旧版 CodeMirror 注入脚本已失效。