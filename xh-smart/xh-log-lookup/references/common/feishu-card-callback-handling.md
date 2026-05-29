# 飞书卡片交互按钮回调处理（历史参考）

当前 `xh-log-lookup` 主流程优先发送飞书卡片。本文记录飞书互动卡片按钮的回调处理逻辑；按钮回调仍是可选能力，不影响主流程卡片发送。

## 适用场景

仅当手工启用历史飞书卡片并包含交互式按钮（非 URL 跳转按钮）时，用户点击后飞书发送回调事件，需要处理并执行后续查询。

## 按钮定义

| 按钮 | action | 额外参数 |
|------|--------|---------|
| 查询全链路 | `query_full_trace` | `trace_id`: 当前 traceId hex 值 |
| 放大时间范围 | `expand_time_range` | `trace_id`, `current_time_range`: 当前时间参数, `original_query`: 原始 CLS 查询语句（含中文原始字符串） |
| 只看错误 | `query_errors_only` | `trace_id`: 当前 traceId hex 值 |

## 回调事件格式

用户点击卡片按钮时，飞书发送 `card.action.trigger` 事件，形如：

```
/card button {"action":"query_full_trace","trace_id":"4fb300217d24dc8f"}
```

## 处理逻辑

1. **解析 action**：从 JSON 中提取 `action` 字段
2. **根据 action 执行对应查询**：
   - **`query_full_trace`**：搜索 `traceId:"<trace_id>"`（不限 serviceName，跨服务全链路），时间范围使用原始卡片的时间范围
   - **`expand_time_range`**：解析 `current_time_range`（如 `now-5m,now`），**前后各增加 1 天**（如 `now-5m,now` → `now-1d-5m,now+1d`）。如果计算后结束时间 > 当前时间，截止到 `now`。使用 `original_query` 搜索并输出新结论
   - **`query_errors_only`**：搜索 `traceId:"<trace_id>" AND level:"ERROR"`，仅返回错误日志结论
3. **输出结果**：当前主流程优先发送互动卡片到原始聊天；发送失败、来源缺失或来源歧义时降级为飞书兼容文本结论

## 中文自动转码

按钮 `value` 中的 `original_query` 可能含中文（如 `message:"[借款下单]下单请求为"`）。收到事件后，必须自动检测中文并转码后才能在 CLS 中使用。

```python
import re

def auto_convert_chinese_to_unicode(query: str) -> str:
    """自动检测查询中的中文并转换为 String.fromCharCode() 格式"""
    chinese_chars = set(re.findall(r'[一-鿿]', query))
    if not chinese_chars:
        return query
    result_parts = []
    for ch in query:
        if '一' <= ch <= '鿿':
            result_parts.append(f'String.fromCharCode({hex(ord(ch))})')
        else:
            result_parts.append(ch)
    return ''.join(result_parts)
```

### 批量转码工具

```python
def encode_chinese_to_unicode(query: str) -> str:
    """将查询字符串中的连续中文替换为 String.fromCharCode() 拼接"""
    def replacer(m):
        codes = ', '.join(f'0x{ord(c):04x}' for c in m.group(0))
        return f'" + String.fromCharCode({codes}) + "'
    return re.sub(r'[一-鿿]+', replacer, query)
```

### 快速查码

```python
def code_points(s):
    return [hex(ord(c)) for c in s]
# code_points("借款下单") → ['0x501f', '0x6b3e', '0x4e0b', '0x5355']
```

## 注意事项

- `original_query` 中始终存原始字符串（含中文），运行时自动检测并转码
- `send_message` 工具发送卡片 JSON 时按钮不渲染（变纯文本），必须通过飞书 Open API 发送
- 当卡片无法使用交互式按钮时，改用 URL 跳转按钮（见 `feishu-card-template.md`）

## 原始日志文本解析

当只有 CLS 页面原始文本时，可用以下函数提取结构化数据：

```python
import re

def parse_cls_raw_text(raw_text: str) -> dict:
    """从 CLS 页面文本提取关键结构数据"""
    count_match = re.search(r'日志条数\s+([\d,]+)', raw_text)
    total_count = count_match.group(1) if count_match else "N/A"
    rows = []
    pattern = r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+).*?message:(.*?)(?=\n\t|\Z)'
    for m in re.finditer(pattern, raw_text, re.DOTALL):
        timestamp = m.group(1)
        msg = m.group(2).strip()[:300]
        rows.append({"time": timestamp, "msg": msg})
    return {"total_count": total_count, "rows": rows}
```
