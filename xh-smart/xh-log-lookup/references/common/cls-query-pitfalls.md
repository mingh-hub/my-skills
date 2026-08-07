# CLS 查询高频坑

## 目录

- Topic 识别
- URL 和时间范围
- 中文 queryBase64
- 大量日志和加载更多
- 页面状态异常
- count 提取

## 何时读取

当 `log_cls_query.py` 返回 0 条、页面状态异常、服务覆盖不完整、或需要解释查询限制时读取。

## 1. Topic 识别

生产应用日志 topic：

```text
topic_id=f6748b3a-8ab8-4191-b848-cb90b1598901
UI 显示名=应用日志 / logsvr-prod
```

不要误选 `fg-prod`。它是 NGINX 访问日志，不含应用日志常用字段 `serviceName`、`message`、`traceId`。

测试应用日志 topic：

```text
topic_id=1f92a7ca-cf46-4f4f-92dd-72c5df5910dc
UI 显示名=logsvr-test-标准+低频
```

## 2. URL 和时间范围

推荐始终使用完整 URL：

```text
https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id={topic_id}&time={start},{end}&queryBase64={base64_query}
```

避免使用 `hide*` 参数。它们可能导致页面空白或提示“请选择需要检索的主题”。

CLS 默认时间范围是近 15 分钟。用户说“今天/全天/最近几天/本月”时必须主动调整时间范围。

## 3. 中文 queryBase64

含中文查询不能直接放入 `queryBase64`。CLS 使用原生 `atob()` 解码，中文会乱码。

推荐：

- 优先使用 ASCII 标识符值搜，例如 `message:"20161002000002677537"`。
- 按钮 URL 也使用 ASCII 查询。
- 中文条件从 `document.body.innerText` 的提取结果中二次过滤。
- 只有值搜不可用时，才读取 `cls-react-contenteditable-injection.md` 尝试 UI 注入。

## 4. 大量日志和加载更多

CLS 页面默认只渲染部分结果。traceId 跨服务链路可能有数百条日志，第一页会漏掉后续服务。

典型踩坑：`traceId:"37426d42fdc699d1"` 第一页只看到 20 条和 3 个服务；加载更多后有 240 条和 9 个服务。

正确做法：

- WorkBuddy 页面操作失败或需要批量自动提取时，切换到本地 Chrome 备用路径，用 `scripts/log_cls_query.py --use-local-chrome --max-load-more` 自动点击“加载更多”。
- 提取全文后检查 `services` 覆盖。
- 如果页面仍有“加载更多”且服务数过少，说明结果仍不完整。

## 5. 页面状态异常

现象：

- 页面显示“请选择需要检索的主题”
- 查询框为空，即使 URL 含 `topic_id` 和 `queryBase64`
- 页面长时间不更新

处理：

1. 重新打开完整 CLS URL，优先使用 WorkBuddy 内置浏览器。
2. 确认 URL 同时包含 `topic_id`、`time`、`queryBase64`。
3. 避免复用被手工点乱的页面；必要时切换到本地 Chrome 备用窗口。
4. 不要直接重启或杀 Chrome，除非用户明确允许。

## 7. level 字段统一加引号

`level` 字段加不加引号均可命中，统一使用加引号写法保持一致：

| 写法 | 结果 |
|------|------|
| `level:"ERROR"` | ✅ |
| `level:"WARN"` | ✅ |
| `level:"INFO"` | ✅ |

**最佳实践：** 所有字段值统一加引号 — `level:"ERROR"` / `level:"WARN"` / `level:"INFO"`，与 `serviceName:"order"` 等写法风格一致。

---

## 6. count 提取（原序号不变）

新版 CLS UI 中结果总数提取不稳定：

- `body.innerText` 不一定包含所有计数字段
- CSS 类名经常变化

如果 `log_count` 为 0 但全文中有日志内容，按采样结果分析，并在最终文本的"风险提示:"字段说明"总数未成功提取"。

### 6a. `=` 等号导致 log_count 不可靠

当 `message:"..."` 查询中包含 `=` 等号时，CLS 可能返回 **topic 总日志数** 而非过滤后的命中数。例如：

| 查询 | 实际 log_count | 含义 |
|------|---------------|------|
| `message:"outBizId="` | 10M+（topic 总数） | ❌ 未过滤 — 值被当成全量 |
| `message:"outBizId=" AND level:"WARN"` | 392（合理） | ✅ 加 level 后正常过滤 |
| `message:"orderId"` | 262M（topic 总数） | ❌ 未过滤 |
| `message:"LoanAntiFraud"` | 0 | ✅ 真实 0 条 |
| `level:"WARN"` | 8 | ✅ 精确 |

**规律**：如果 `log_count` 等于该 topic 近似总量（数百万/千万级），说明查询中的 `=` 符号导致 CLS 退化为全量返回。加一个约束字段（如 `level:"WARN"`）可恢复过滤行为。此时应以 `load_more_clicks` 加载出的实际日志内容为准，忽略 `log_count`。
