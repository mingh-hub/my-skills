# 飞书卡片模板

## 目录

- 何时读取
- 标题和颜色
- 必填内容
- 卡片结构
- 按钮 URL
- Markdown 降级

## 何时读取

当需要手工构造或排查 `tools/send_feishu_card.py` 发送的卡片内容时读取。常规查询优先使用 `xh-log-lookup/SKILL.md` 的 Hermes 内置浏览器路径；需要卡片按钮 URL 时，可用 `cls_query.py` 默认 URL-only 输出的 `cls_url` / `expanded_url`。

主流程见 `../SKILL.md`。所有日志查询结果必须输出飞书卡片；不可用时使用 Markdown 链接降级。

## 1. 适用范围

适用于所有 `xh-log-lookup` 日志查询结果，包括：

- 生产 / 测试环境
- 命中 / 未命中
- 正常 / 业务异常 / 系统异常
- 交互式卡片不可用时的 Markdown 降级输出

## 2. 标题规范

标题格式：

```text
[emoji] 场景简述 · 开始时间~结束时间
```

示例：

```text
✅ 下单正常 · 05-17 09:00~10:00
⚠️ 下单业务异常 21 笔 · 05-17 00:00~23:59
❌ 下单出现系统错误 · 05-17 00:00~23:59
⚠️ 未查询到相关日志 · 05-17 09:00~10:00
```

## 3. 颜色分级

| 级别 | template | 条件 |
|------|----------|------|
| 🔴 红色 | `red` | ERROR、堆栈、流程阻断、查询未正常执行 |
| 🟡 黄色 | `yellow` | WARN、业务异常、失败但流程完整、无结果但查询正常 |
| 🟢 绿色 | `green` | 全部正常、全部 SUCCESS |

判定优先级：

```text
ERROR/查询失败 > WARN/失败/无结果 > SUCCESS
```

### 无结果场景

无结果但查询正常时，使用黄色卡片，并明确说明：

- topic 是否正确
- 时间范围是否符合用户问题
- 查询语句是否正常执行
- 建议扩大时间范围或补充 `traceId` / `orderId` / `cid`

## 4. 必填内容

卡片至少包含：

1. 查询对象：`traceId` / `orderId` / `cid` / `contractNo` / 业务描述
2. 环境：生产或测试
3. 时间范围
4. 查询语句摘要
5. 命中结果：总数或采样数
6. 诊断结论
7. `🔗 跳转链接`
8. `⏱ 扩大查询范围`

> 如果结果来自采样或 count 提取失败，必须在卡片中说明“采样”或“总数未成功提取”。

## 5. 卡片结构

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "✅ 下单正常 · 05-17 09:00~10:00"},
    "template": "green"
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**查询对象**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "近一小时下单情况"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**环境**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "生产 logsvr-prod"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**下单请求总数**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "20 笔"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "✅ **成功**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "20 笔"}}
      ]
    },
    {
      "tag": "div",
      "text": {
        "tag": "lark_md",
        "content": "**诊断结论**：下单主链路正常，未发现系统错误。"
      }
    },
    {"tag": "hr"},
    {
      "tag": "note",
      "elements": [
        {"tag": "plain_text", "content": "查询范围：生产 logsvr-prod｜time=now-1h,now｜query=serviceName:\"order\" AND ..."}
      ]
    },
    {
      "tag": "action",
      "actions": [
        {
          "tag": "button",
          "text": {"tag": "plain_text", "content": "🔗 查看 CLS 完整结果"},
          "type": "primary",
          "url": "<CLS URL>"
        },
        {
          "tag": "button",
          "text": {"tag": "plain_text", "content": "⏱ 扩大查询范围"},
          "type": "default",
          "url": "<CLS URL expanded>"
        }
      ]
    }
  ]
}
```

注意：`div.fields` 数组必须为偶数，每两个元素组成一行：左侧字段名，右侧字段值。

## 6. 按钮 URL 规则

按钮 URL 必须包含：

- `topic_id`
- `time`
- `queryBase64`

推荐 URL：

```text
https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id={topic_id}&time={start},{end}&queryBase64={base64_query}
```

不要省略 `queryBase64`，否则跳转后搜索框为空。

### traceId 自动带入规则

如果查询结果中返回了明确的 `traceId`，生成 `🔗 查看 CLS 完整结果` 和 `⏱ 扩大查询范围` 时必须将该 `traceId` 带入查询条件：

- 原查询未包含 `traceId`：在查询条件中追加 `AND traceId:"{traceId}"`
- 原查询已包含相同 `traceId`：保持原查询，避免重复追加
- 如果返回多个 `traceId`：优先使用与诊断结论最相关的一条；无法判断时，在卡片中说明仅选取首个 `traceId`
- 扩大查询范围链接必须使用同一个带 `traceId` 的 `queryBase64`，仅扩大 `time`

示例：

```text
原查询：serviceName:"order" AND level:"ERROR"
返回 traceId：abc123
跳转查询：serviceName:"order" AND level:"ERROR" AND traceId:"abc123"
```

### 扩大查询范围 URL

`⏱ 扩大查询范围` 使用相同 `topic_id` 和 `queryBase64`，只扩大 `time`：

- 相对时间：`now-1h,now` → `now-1d,now`
- 绝对时间：`start,end` → `start-1d,end+1d`

如果原查询已经是较长范围（如近 7 天），可按实际场景调整，但必须在卡片中说明。

### 中文查询注意事项

如果原查询包含中文，不要直接把中文查询 base64 后放入 `queryBase64`。

正确做法：

- 按钮 URL 的 `queryBase64` 使用 ASCII 查询，例如 `serviceName:"order" AND message:"{标识符}"`
- 真实中文条件不要进入 `queryBase64`；优先从 Hermes 页面全文或本地 Chrome 备用路径提取的全文里二次过滤
- 详细规则见 `chinese-queryBase64-experiments.md` 和 `cls-react-contenteditable-injection.md`

## 7. 降级 Markdown

当飞书交互式卡片不可用时，发送 Markdown：

```markdown
### ✅ 下单正常 · 05-17 09:00~10:00

- 查询对象：近一小时下单情况
- 环境：生产 logsvr-prod
- 时间范围：now-1h,now
- 下单请求：20 笔
- 成功结果：20 笔
- 系统错误：0 条
- 业务异常：0 条
- 诊断结论：下单主链路正常，未发现系统错误。

[🔗 跳转链接 ｜ 查看 CLS 完整结果](<CLS URL>)

[⏱ 扩大查询范围 ｜ 时间前后各扩展 1 天](<CLS URL expanded>)
```

## 8. 常见注意事项

- 卡片必须体现查询对象、环境、时间范围、命中结果和诊断结论。
- `div.fields` 数组必须为偶数。
- 按钮 URL 必须包含 `topic_id`、`time`、`queryBase64`。
- 如果查询结果返回了明确 `traceId`，跳转链接和扩大查询范围链接必须将该 `traceId` 带入查询条件。
- 含中文查询时，`queryBase64` 使用 ASCII 占位查询，不要直接编码中文。
- 无结果但查询正常时用黄色卡片；查询未正常执行时用红色卡片。
- Markdown 降级时，仍必须保留两个链接：`🔗 跳转链接 ｜ 查看 CLS 完整结果` 和 `⏱ 扩大查询范围 ｜ 时间前后各扩展 1 天`。
