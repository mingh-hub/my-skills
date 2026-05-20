# CLS DOM 数据提取方法

主流程见 `../SKILL.md`。本文记录在 CLS 查询结果页提取日志数据的方法。

## 原则

通过 osascript + 本地 Chrome 操作 CLS 页面，不使用 browser_* 工具。所有示例都必须使用已记录的 `CLS_WINDOW_ID`，不要操作用户当前的前台窗口。

## ⚠️ 致命坑：innerText 前缀 ≠ 数据存在性

**不要**用 `document.body.innerText.substring(0,500)` 或 `substring(0,N)` 判断 CLS 页面是否有数据。

**原因**：CLS 的 React 页面布局是：
1. 左侧边栏（主题列表）
2. 顶部工具栏（查询框、时间选择）
3. 字段列表（30+ 个可用字段）
4. **日志数据表格** — 这部分在 innerText 的末尾

取前 500 字符 = 只抓到 sidebar/toolbar/字段列表 → 看起来永远是"0 条结果"，即使实际有 1,895 条数据。

**正确做法**：
```bash
# 提取全页文本，保存到文件
osascript -e "tell app \"Google Chrome\" to execute active tab of (first window whose id is ${CLS_WINDOW_ID}) javascript \"document.body.innerText\"" > /tmp/cls_output.txt 2>&1

# 在文件末尾查看数据
tail -100 /tmp/cls_output.txt
```

## 基础提取

```bash
osascript -e "tell app \"Google Chrome\" to execute active tab of (first window whose id is ${CLS_WINDOW_ID}) javascript \"document.body.innerText\"" > /tmp/cls_output.txt
```

## 大批量数据提取（"加载更多"连击）

CLS 页面默认只显示 20 条结果。对于数百到数千条的结果集，需要反复点击"加载更多"：

```bash
# 找到并点击"加载更多"按钮（<button class="sdk-cls-btn sdk-cls-btn--link">）
for i in $(seq 1 10); do
  osascript -e "tell app \"Google Chrome\" to execute active tab of (first window whose id is ${CLS_WINDOW_ID}) javascript \
    \"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '加载更多')?.click()\""
  sleep 1
done
```

注意：
- 即使 osascript 返回 "missing value"，点击通常也成功了
- 用 `querySelectorAll("div[class*=message]").length` 验证是否在增长
- 1,895 条 ≈ 95 页 × 20 条/页，需要 ~95 次点击（每次 1 秒 ≈ 1.5 分钟）
- 可以根据总条数估算需要的点击次数

## Python 正则解析

```python
import re

with open('/tmp/cls_output.txt') as f:
    text = f.read()

# 提取所有唯一合同号
contracts = set(re.findall(r'contractNo":"(C[KS][^"]+)"', text))

# 提取合同状态（仅在特定日志类中有 contractNoState）
for m in re.finditer(r'contractNo":"([^"]+)".*?contractNoState":"([^"]+)"', text, re.DOTALL):
    print(f"{m.group(1)} → {m.group(2)}")

# 提取 orderStatus / accountStatus
order_statuses = set(re.findall(r'orderStatus":"([^"]+)"', text))
account_statuses = set(re.findall(r'accountStatus":"([^"]+)"', text))

# 提取 orderId
order_ids = set(re.findall(r'orderId":"(\d+)"', text))

# orderId → contractNo 映射
for oid in sorted(order_ids):
    m = re.search(r'orderId":"' + oid + r'"[^}]*?contractNo":"([^"]+)"', text)
    if m:
        print(f"{oid} → {m.group(1)}")
```

## 致命坑：document.body.innerText 漏掉 message 字段内容

**问题**：标准 `document.body.innerText` 提取 CLS 原始日志视图时，`message` 字段的值经常不被包含在内。CLS 的 React 渲染将 message 值放在深层 DOM 节点中，`innerText` 串联时可能跳过。

**表现**：搜索到了日志条目（log_count > 0），但只提取到 `message` 字段名，没有字段值。`grep hisMaxOverdueDay` 只找到查询条件本身，而非日志内容。

**解决方案 — 叶子节点文本搜索法**（用 Python `subprocess` 执行 osascript，避免引号转义问题）：

```python
import subprocess, json

js_code = """
(function() {
    var allEls = document.querySelectorAll('*');
    var results = [];
    for (var i = 0; i < allEls.length; i++) {
        var el = allEls[i];
        if (el.children.length === 0 && el.textContent) {
            var t = el.textContent.trim();
            // 条件：包含目标值 + 足够长（排除短标签文本）
            if (t.indexOf('YOUR_CID_OR_TRACE_ID') > -1 && t.length > 80) {
                results.push(t.substring(0, 1200));
                if (results.length >= 30) break; // 限制数量防超时
            }
        }
    }
    return JSON.stringify(results);
})()
"""

proc = subprocess.run([
    'osascript', '-e',
    f'tell app "Google Chrome" to execute active tab of (first window whose id is {CLS_WINDOW_ID}) javascript "{js_code}"'
], capture_output=True, text=True, timeout=30)

lines = json.loads(proc.stdout)
for l in lines:
    print(l)  # 每行是一条完整日志，包含 message 字段值
```

**原理**：跳过所有容器元素（有 children 的 div/span），只取叶子 DOM 节点。CLS 的 message 值正好在 `<span>` / `<div>` 等叶子节点中，且不与其他字段挤在同一节点。

**适用于**：
- 查询结果数少（<200 条）时，直接提取全部
- 结果数多时，先缩小查询范围（加 `NOT filename:"dubbo-profile.log"` / `AND filename:"order-default.log"` / 加 level 约束等）
- 不能直接用 `document.body.innerText` 的场景

## send_feishu_card.py JSON 传递技巧

`send_feishu_card.py --data` 参数是 JSON 字符串，但包含换行的 `analysis` 字段在 bash 中容易引发 JSONDecodeError。

**推荐做法**：用 Python 构造 JSON 后通过 `'$(cat file)'` 或直接传字符串：

```python
import json
data = {"analysis": "包含换行的\n文本内容"}
data_str = json.dumps(data, ensure_ascii=False)
# 传给 terminal() 或 subprocess
```

避免在 bash 层拼接包含换行的 JSON。

## 已知限制

- `contractNoState` 只出现在特定日志类（DroolsService 校验换卡入口规则入参、CheckShowChangeCardEventListener）中
- 不是所有合同都有 `contractNoState` — 需要结合 `accountStatus` 交叉判断
- 已结清合同可能不在 30 天日志范围内，无法通过 CLS 确认
- osascript 保存到文件的方式避免了大返回值截断问题
