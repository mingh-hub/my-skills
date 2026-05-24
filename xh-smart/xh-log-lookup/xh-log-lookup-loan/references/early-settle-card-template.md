# 提前结清失败 — 飞书卡片模板

## 何时读取

当放款/提前结清相关查询需要专项飞书卡片字段、按钮 URL 或错误分类时读取。通用卡片规则仍以 `../../references/feishu-card-template.md` 为准。

## 目录

- 适用范围
- 卡片字段
- 发送示例
- 错误分类

## 适用范围

适用于所有 `[提前结清]` 前缀的日志查询结果，包括：

- 资金方提前结清金额明细查询失败
- 资金方返回业务错误（有效账户不存在、合同状态异常等）
- 调用资金方接口网络异常/超时
- 服务调用链跨 `order → frontendcenter → account-gateway(资方)`

## 典型调用链

```
thor-app-gateway (env)
  → order (env, CtcfService / 相关类)
    → frontendcenter (env, RedirectService.httpRedirect)
      → account-gateway (资方域名, earlySettle/getFeeDetail)
```

## 卡片结构

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🔴 提前结清失败 · {时间范围}"},
    "template": "yellow"
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**查询对象**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "traceId: `{traceId}`"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**环境**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "{生产/测试} {topic名}"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**合同号**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "`{contractNo}`"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**资金方**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "{资方名}"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**业务编码**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "`{businessNo}`"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**错误信息**"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "❌ `{资方返回的 errMsg}`"}}
      ]
    },
    {"tag": "hr"},
    {"tag": "markdown", "content": "{调用链 markdown}"},
    {"tag": "hr"},
    {"tag": "markdown", "content": "**📋 分析结论:**\n{分析文本}"},
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {
          "tag": "button",
          "text": {"tag": "plain_text", "content": "🔗 跳转链接"},
          "type": "primary",
          "url": "{CLS URL 带 traceId}"
        },
        {
          "tag": "button",
          "text": {"tag": "plain_text", "content": "⏱ 扩大查询范围"},
          "type": "default",
          "url": "{CLS URL 扩大时间}"
        }
      ]
    },
    {
      "tag": "note",
      "elements": [
        {"tag": "plain_text", "content": "🕐 共查询到 {N} 条日志 | {HH:mm}"}
      ]
    }
  ]
}
```

## `send_feishu_card.py` 调用示例

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/send_feishu_card.py \
  --title "🔴 提前结清失败 · 05-19 14:06:33~14:06:36" \
  --color yellow \
  --cls-url "https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id=1f92a7ca-cf46-4f4f-92dd-72c5df5910dc&time=now-1d,now&queryBase64=$(python3 -c \"import base64; print(base64.b64encode(b'traceId:\\\"d3acd9c5b5207e00\\\"').decode())\")" \
  --cls-url-expanded "https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id=1f92a7ca-cf46-4f4f-92dd-72c5df5910dc&time=now-7d,now&queryBase64=$(python3 -c \"import base64; print(base64.b64encode(b'traceId:\\\"d3acd9c5b5207e00\\\"').decode())\")" \
  --data '{
    "summary_fields": [
      {"label": "查询对象", "value": "traceId: `d3acd9c5b5207e00`"},
      {"label": "环境", "value": "测试 logsvr-test-标准+低频"},
      {"label": "合同号", "value": "`CK202510210000455`"},
      {"label": "资金方", "value": "中腾信"},
      {"label": "业务编码", "value": "`20260519000000013001`"},
      {"label": "CID", "value": "`20251020000000364082`"},
      {"label": "错误信息", "value": "❌ `合同号:CK202510210000455的有效账户不存在`"}
    ],
    "call_chain": [
      {"time":"14:06:33","service":"thor-app-gateway","level":"INFO","content":"收到提前结清请求"},
      {"time":"14:06:34","service":"order","level":"INFO","content":"[提前结清]调用中腾信提前结清金额明细查询, businessNo:20260519000000013001, contractNo:CK202510210000455"},
      {"time":"14:06:35","service":"frontendcenter","level":"INFO","content":"RedirectService.httpRedirect -> POST http://sit.ctcfin.com/account-gateway/earlySettle/getFeeDetail"},
      {"time":"14:06:35","service":"account-gateway","level":"INFO","content":"收到提前结清查询请求, contractNo:CK202510210000455"},
      {"time":"14:06:36","service":"account-gateway","level":"WARN","content":"提前结清查询失败: 合同号:CK202510210000455的有效账户不存在"},
      {"time":"14:06:36","service":"order","level":"WARN","content":"[提前结清]调用中腾信提前结清金额明细查询结果, result:{\"status\":\"FAIL\",\"errMsg\":\"合同号:CK202510210000455的有效账户不存在\",\"data\":null}"}
    ],
    "analysis": "合同 CK202510210000455 在中腾信侧无有效账户记录。资金方返回 errMsg: \"合同号:CK202510210000455的有效账户不存在\"。可能是测试环境数据问题——合同数据未同步到资金方，或账户已销户/结清。",
    "log_count": 112
  }'
```

## 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `{时间范围}` | 日志时间范围 | `05-19 14:06:33~14:06:36` |
| `{N}` | 命中日志条数 | `112` |
| `{businessNo}` | 业务编码 | `20260519000000013001` |
| `{errMsg}` | 资方返回的错误描述 | `合同号:CK202510210000455的有效账户不存在` |
| `{contractNo}` | 合同号 | `CK202510210000455` |
| `{traceId}` | 全链路 traceId | `d3acd9c5b5207e00` |
| `{topic名}` | CLS topic 显示名 | `logsvr-test-标准+低频` |
| `{资方域名}` | 资金方 gateway 域名 | `sit.ctcfin.com` |
| `{环境}` | 生产/测试 | 测试 |
| `{资方名}` | 资金方简称 | 中腾信、马上消费、维信等 |

## 颜色规则

| 级别 | 颜色 | 条件 |
|------|------|------|
| 🟡 黄色 | `yellow` | 资方返回业务错误（有效账户不存在、合同状态异常等）— 默认 |
| 🔴 红色 | `red` | 网络异常、超时、系统异常、堆栈 |
| 🟢 绿色 | `green` | 提前结清成功（不使用此模板） |

## 已知失败模式

| 资方错误信息 | 诊断 | 级别 |
|-------------|------|------|
| `有效账户不存在` | 合同在资金方侧无有效账户记录 | 🟡 数据问题 |
| `合同状态异常` | 合同状态不允许提前结清 | 🟡 业务限制 |
| `结清金额计算失败` | 资金方内部计算错误 | 🔴 系统异常 |
| `HTTP 500/502/503` | 资方接口不可用 | 🔴 网络问题 |
| `timeout/read timeout` | 调用资方接口超时 | 🔴 网络问题 |

## 注意事项

1. 提前结清失败通常走 `order → frontendcenter → account-gateway(资方域名)` 链路
2. **queryBase64 必须包含 traceId**，便于跳转后直接看到完整链路
3. 卡片标题用 `🔴 提前结清失败 · {开始时间}~{结束时间}` 格式
4. 调用链先用 `traceId` 全量搜，再按时间排序提取关键节点
5. 按钮 URL 的 time 参数建议：原始 `now-1d,now`，扩大 `now-7d,now`
6. 测试环境使用 topic_id `1f92a7ca-cf46-4f4f-92dd-72c5df5910dc`（logsvr-test-标准+低频）
