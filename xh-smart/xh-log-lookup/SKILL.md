---
name: xh-log-lookup
description: 当用户需要查询生产或测试环境日志时，启用此技能。此技能为生产和测试环境日志查询流程主控，可以通过：线程号（traceId），订单号（orderId），用户ID（cid，userId），合同号（contractNo），手机号（mobileNo，mobilePhone），身份证号（idNo，identityNo）等信息查询借款能力，借款内容（借款试算），签约，下单，权益，放款，还款各业务模块日志，帮助用户快速定位问题根因。
metadata:
  hermes:
    version: 2.0.2
    author: xh-smart
    platforms: [macos]
    tags: [logs, cls, argus, traceId, orderId, cid, contractNo, feishu]
---

# xh-log-lookup — 日志查询主控

处理生产/测试环境日志查询、业务异常排查、CLS 结果及根因分析和**飞书卡片输出**。主控只负责意图分类、路由、强制约束和工具调用；业务细节在子 Skill 和 references 中。

## 强制规则

### 查询方法
- 每次会话首次执行**代码锚点**校验前，按 `references/update-master-branch.md` 更新对应服务仓库的 master 分支（路径：`/Users/user/mingh/workspace/{服务名}`，服务名参考业务路由表）
- 看代码确认日志格式，再查 CLS；不要凭空猜日志关键词。本地仓库代码入口在:/Users/user/mingh/workspace下
- 子模块入口表格里的推荐查询只是通过代码锚点校验后的首查模板，不是唯一真相。若在子模块未定位到代码锚点, 需要提问用户来获取更详细的信息,直到能定位到代码入口
- 执行入口表格推荐查询前，先校验 `方法入口`、`serviceName` 和固定 `message` 片段是否仍能和当前代码匹配；可用 `tools/validate_query_anchors.py` 辅助检查。
- 标识符值优先直接放入 `message:\"{value}\"`，禁止加 `cid:`、`orderId:`、`contractNo:`
- `traceId:\"{value}\"`。
- 日志查询sql中如果包含中文, 查询不要直接放入 `queryBase64`。使用注入方案：先用 ASCII queryBase64 URL 加载页面，再通过 contenteditable + `execCommand('insertText')` + `String.fromCharCode()` 注入中文查询（详见 `references/cls-react-contenteditable-injection.md`）
- 日志平台查询常用key:

| ***key*** | ***包含的值*** | ***说明*** |
|----|----|----|
| **serviceName** | `order`,`order-batch`,`order-batch-timing`,`h5-loan,protocol`,`protocol-batch`,`protocol-batch-timing`,`account`,`cif`,`datainquiry`,`loki-webapp` | 服务名,日志查询sql拼装条件之一,如:serviceName:"order"
| **level** | `INFO`,`ERROR`,`WARN`,`DEBUG` | 日志级别,异常查询时常用 `ERROR` 级别 |
| **env** | `prod`,`uat`,`test1`,`test2`,`test3`,`test4`,`test5`,`test6`,`test7`,`test8`,`test9`,`test10`,`test11`  | 用户不指定时默认使用`prod`，如果查测试环境,若用户未指定查哪个`test`环境, 默认不加该条件,指定后格式：`env:\"{value}\"`  |
| **traceId** | 格式: 数字，字母，字母+数字组合 | 通常用户输入或者根据其它条件能确认`tractId`时。注意：根据`traceId`查询时一般不拼接其它查询条件 |

### 浏览器和 CLS

- CLS/Argus URL 只能通过用户本地 Chrome + AppleScript 访问，禁止使用 Hermes 云端 `browser_*` 工具访问 `argus.xhdev.xyz` 或 `datasight-*.clsconsole.tencent-cloud.com`。
- 禁止默认操作 `active tab of front window`。首次查询创建新的 Chrome window，后续查询复用该窗口，通过 window id 定向操作。发送飞书卡片后调用 `tools/cls_query.py --close` 关闭窗口。若页面跳转到 argus.xhdev.xyz 登录页，提示用户在 Chrome 中完成登录后重试。
- 优先使用 `tools/cls_query.py` 构造 URL、打开专用窗口、加载更多、提取 `document.body.innerText`。
- 不要用 `document.body.innerText.substring(0,N)` 判断结果；CLS 日志数据在页面文本后部。
- `traceId` 查询也可能超过 20 条；必须加载更多直到按钮消失或达到合理上限。

### 飞书输出

- 初始查询结果、跟进追查结果、根因分析、深度钻取结果和分析结论必须通过 `tools/send_feishu_card.py` 发送飞书交互式卡片。
- 卡片按钮 **URL** 必须包含 `topic_id`、`time`、`queryBase64`。
- 非统计类查询（结果跨多个线程时除外），当查询结果集中在单个线程时，返回的飞书卡片必须带上 `traceId`，卡片 **URL** 只带 `traceId` 即可
- 只有脚本执行失败时，才降级为 Markdown。

 
### ⚠️ 0 条结果排查清单

查询返回 0 条时，**不要立即归因于查询语法**。按顺序排查：

1. **时间窗口** — `now-1d,now` 是否真的覆盖了日志产生时间？扩大至 `now-7d,now` 或 `now-30d,now` 验证，能查到日志，说明`sql`语法没问题
2. **topic 是否正确** — CLS hide* params 可能导致 topic 随机丢失，确认 topic_id 无误
3. **分页未加载完** — CLS 每页只显示 20 条，`load_more_clicks` 是否足够？检查 `log_count` 字段
4. **Chrome JS 权限** — AppleScript 报 `JavaScript 的功能已关闭` 时，Chrome 无法提取页面
5. **`=` 等号查询退化** — 如果查询含 `message:\"字段=值\"` 且 `log_count` 显示为 topic 总量（数百万级），说明 CLS 退化为全量返回。加 `AND level:\"WARN\"/\"INFO\"` 等额外约束可恢复精确过滤。此时应以实际加载出的日志内容为准
6. **最后才怀疑语法** — 大部分\"语法问题\"是时间窗口或分页导致的，此时需要将查询`sql`返回给用户，让用户协助确认查询`sql`是否存在问题，用户确认完毕后再进行查询

### 推荐查询锚点校验

入口表统一使用 `场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 说明`。

- `方法入口` 存在且 `serviceName` 与源码项目匹配、固定 `message:\"...\"` 片段仍在该入口类/方法附近命中时，才把推荐查询作为 Phase A 主查询。
- 方法存在但固定 message 不匹配时，不要把旧模板当主路径；改用 `serviceName:\"{服务}\" AND message:\"{标识符}\"`，并 grep 当前代码找新日志前缀。
- 方法不存在、源码缺失或服务不匹配时，标记模板疑似过期；先按 traceId/标识符值搜，再回代码确认入口。
- 推荐查询 0 命中时，继续做值搜、扩大时间、跨服务和代码 grep，不直接下\"无日志\"结论。

## 意图分类

| 意图 | 识别特征 | 查询策略 |
|------|---------|---------|
| 流程追踪 | 借款、下单、放款、还款、权益、签约、绑卡、指定 `traceId`/`orderId`/`contractNo` | 路由到业务子 Skill，按入口日志定位 `traceId`，再查全链路 |
| 健康检查 | 最近有没有异常、无具体标识符 | 使用业务子 Skill 的总览式查询步骤 |
| SSO/登录 | Argus/CLS 要登录、JANUS/PMP 会话失效 | 使用 `xh-sso-access` |

## 业务路由

| 关键词 | 子 Skill | 业务模块 |
|--------|---------|--------|
| 签约、重签、重新签约、RESIGN、SIGNING_ISSUE、协议、绑卡、银行卡签约、代扣协议、支付协议 | `xh-log-lookup-sign` | 签约模块 |
| 下单、端内下单、自营下单、api下单、订单、拦截、反欺诈 | `xh-log-lookup-order` | 下单模块 |
| 权益、会员、VIP、优惠券、乐活卡、coupon，尊享卡，拒就得，加速卡 | `xh-log-lookup-benefit` | 权益模块 |
| 放款、资金路由、route、解H、loki放款 | `xh-log-lookup-loan` | 放款模块 |
| 还款、扣款、逾期、代扣、结清、repay、债转 | `xh-log-lookup-repay` | 还款模块 |

匹配不到业务模块时，先问用户确认。

## 标准工作流

1. 理解问题，提取环境、时间范围、标识符和业务模块。
2. 分类意图：流程追踪、存量状态查询、健康检查或 SSO。
3. 路由到对应业务子 Skill，读取其入口日志、失败模式和 reference 指引。
4. 对入口表推荐查询做代码锚点校验；不匹配时降级到标识符值搜并 grep 代码确认真实日志前缀、logger 和字段。
5. 组装 CLS 查询语句，使用 `tools/cls_query.py` 查询并提取全文。
6. 推荐查询 0 命中时，按\"值搜 → 扩大时间 → 去掉 serviceName 跨服务 → 再 grep 当前代码\"的顺序回退。
7. 分析日志，说明命中、未命中、topic、时间范围和查询限制。
8. 使用 `tools/send_feishu_card.py` 发送卡片。
9. 如查询不完整，发黄色卡片并给出下一步需要的标识符或更大时间范围。
10. 飞书卡片发送成功后，调用 `cls_query.py --close` 关闭 CLS 浏览器窗口。

## CLS 工具

### 构造 URL，不打开浏览器

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/cls_query.py \
  --env prod \
  --query 'serviceName:"order" AND message:"20161002000002677537"' \
  --no-browser
```

### 打开专用 Chrome 窗口并提取文本

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/cls_query.py \
  --env prod \
  --time 'now-7d,now' \
  --query 'traceId:"37426d42fdc699d1"' \
  --output /tmp/cls_output.txt
```

工具输出 JSON，包含：

- `cls_url`：本次查询跳转链接
- `expanded_url`：扩大时间范围链接
- `output_path`：提取的全文路径
- `log_count`：从\"日志条数\"解析出的结果数（注意：含 `=` 的查询可能退化为全量返回，log_count 不可靠）
- `services`：提取到的服务名
- `contracts`：提取到的 CK/CS 合同号

### 中文查询注入

若需要中文查询（如 `[借款下单]下单请求为`），queryBase64 不支持非 ASCII。使用注入方案：

1. 先用 ASCII 查询使 CLS 页面加载、contenteditable 渲染
2. 通过 AppleScript 执行 JS，用 `String.fromCharCode()` 构造中文字符串并用 `execCommand('insertText')` 注入到 contenteditable div
3. 显式点击搜索按钮（带 SVG 图标的 button）
4. 等待 10-15s 后提取页面文本

详细步骤和代码示例见 `references/cls-react-contenteditable-injection.md`。

### 校验入口表锚点

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/validate_query_anchors.py \
  --skill /Users/user/.hermes/skills/xh-smart/xh-log-lookup/xh-log-lookup-order/SKILL.md \
  --source-root /Users/user/mingh/workspace/order
```

输出会标记每行方法入口、服务名和固定 message 锚点是否匹配，并给出建议降级查询。校验不通过时，推荐查询只能作为历史线索，不能作为主查询。

## CLS 环境

| 环境 | topic_id | UI 显示名 | 默认时间 |
|------|----------|----------|----------|
| 生产 | `f6748b3a-8ab8-4191-b848-cb90b1598901` | `logsvr-prod` | `now-7d,now` |
| 测试 | `1f92a7ca-cf46-4f4f-92dd-72c5df5910dc` | `logsvr-test-标准+低频` | `now-1d,now` |

CLS URL 格式：

```text
https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id={topic_id}&time={start},{end}&queryBase64={base64_query}
```

## 查询语法

```text
字段匹配: field:"value"         -- 所有字段统一加引号（serviceName、traceId、level 等）
与条件:   AND
或条件:   OR
```

**⚠️ 注意：** 所有字段值统一加引号（`level:\"ERROR\"`、`serviceName:\"order\"`），保持风格一致。0 命中时优先排查时间窗口是否太窄，而非怀疑语法。

索引字段：`traceId`、`serviceName`、`level`、`requestId`。

非索引字段必须通过 `message` 全文搜索：`orderId`、`cid`、`contractNo`、logger 名称等。

## 飞书卡片

使用：

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/send_feishu_card.py \
  --title "✅ 场景简述 · 05-18 00:00~23:59" \
  --color green \
  --cls-url "{cls_url}" \
  --cls-url-expanded "{expanded_url}" \
  --data '{"summary_fields":[{"label":"查询对象","value":"..."},{"label":"环境","value":"生产 logsvr-prod"},{"label":"命中日志","value":"N 条"},{"label":"诊断结论","value":"..."}],"analysis":"详细分析文本","log_count":0}'
```

颜色：

| 颜色 | 使用条件 |
|------|----------|
| `red` | ERROR、堆栈、流程阻断、查询未正常执行 |
| `yellow` | WARN、业务异常、逾期、无结果但查询正常、不完整采样 |
| `green` | 全部正常、全部 SUCCESS |
| `blue` | 常规信息查询 |

### ⛔ 输出前自检

当你准备在聊天中写出诊断结论、分析报告、根因判断时——**停下来**。这是你即将违反卡片规则的信号。把结论写进 `send_feishu_card.py` 的 `--data '{"analysis":"..."}'` 参数，不要写进聊天。

常见触发场景：
- 调试了很久终于搞清楚了，急着把结论说出来
- CLS 提取遇到困难，改用手动分析后直接口述
- 用户追问，你觉得"先快速回答再补卡片"

## 输出要求

每次结论必须说明：

- 查了什么代码、找到了哪些日志前缀或 logger
- CLS 查询语句、topic、时间范围
- 命中的日志摘要和未命中的关键证据
- 结果是否完整：是否加载更多、是否只采样、是否受时间范围限制
- 飞书卡片是否发送成功；失败时说明降级链接

## References

- `references/update-master-branch.md`：更新 `master` 分支代码
- `references/cls-local-chrome-access.md`：本地 Chrome 专用窗口访问 CLS
- `references/cls-dom-extraction.md`：全文提取、加载更多、CK/CS 合同号解析
- `references/cls-query-pitfalls.md`：CLS 高频坑和恢复方式
- `references/chinese-queryBase64-experiments.md`：中文 queryBase64 限制
- `references/cls-react-contenteditable-injection.md`：React contenteditable 中文注入方案（String.fromCharCode + execCommand）
- `references/feishu-card-template.md`：飞书卡片结构和按钮 URL 规则
- `references/feishu-card-callback-handling.md`：飞书卡片按钮回调
- `references/trace-dubbo-profile-filter.md`：Dubbo 全链路追踪（ProfileFilter CS/CR/SS/SR 标记解读 + 溯源方法论）
- `references/cls-iframe-crossorigin-workflow.md`：历史废弃 iframe 方案，只作背景