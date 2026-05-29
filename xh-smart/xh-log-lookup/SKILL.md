---
name: xh-log-lookup
description: 当用户需要查询生产或测试环境 CLS/Argus 日志、定位借款/下单/签约/权益/放款/还款问题，或需要 traceId/orderId/cid/contractNo/mobile/idNo 排查时使用。
allowed-tools:
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/validate_query_anchors.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/resolve_workspace.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py *)
  - Bash(LARK_CLI_NO_PROXY=1 lark-cli im +messages-search *)
  - Bash(LARK_CLI_NO_PROXY=1 lark-cli im +messages-mget *)
  - Bash(LARK_CLI_NO_PROXY=1 lark-cli im +messages-send *)
disable: false
---

# xh-log-lookup — 日志查询主控

处理生产/测试环境日志查询、业务异常排查、CLS 结果及根因分析，默认优先通过飞书卡片输出，失败时降级为飞书兼容文本。主控只负责意图分类、路由、强制约束和工具调用；业务细节在 `references/modules/` 和 `references/common/` 中。

## 日志服务名和项目名映射关系表

这张表是客户订单组负责的日志服务清单。`serviceName` 列用于 CLS 查询范围，`别名`列用于把用户自然语言服务名映射到一组 `serviceName`，`项目名`列只用于定位本地源码仓库；三者不要混用。

服务范围识别按以下优先级执行：
- 用户明确说出具体 `serviceName`（如 `order`、`protocol-batch`）时，只查该单个服务。
- 用户说出表中某个`别名`时，查所有同别名行对应的 `serviceName`。`别名`列可填写多个自然语言别名，使用中文逗号 `，` 或英文逗号 `,` 分隔。
- 用户说"我们组"、"客户订单组"、"这批服务"或没有指定具体服务但要求查看本组日志情况时，默认以本表 `serviceName` 列的全部服务作为查询覆盖范围。

同一个`别名`可对应多个 `serviceName`，同一个 `serviceName` 也可以挂多个别名。例如"订单服务异常"要展开到表中所有包含`订单服务`或`订单`别名的服务后再查询和分析。

`仓库路径`列是本地缓存，不是跨机器固定路径。路径为空或失效时，先执行 `scripts/resolve_workspace.py --check` 诊断；确认无误后再执行 `scripts/resolve_workspace.py` 更新映射表。

推荐通过 `XH_WORKSPACE_ROOTS` 配置工作区根目录，可配置多个根目录，用 `:` 分隔。每个根目录会按 `{root}/{项目名}` 和 `{root}/workspace/{项目名}` 查找仓库。

示例：`XH_WORKSPACE_ROOTS="/Users/user/mingh/workspace:/Users/hisense/Documents/workspace"`

| serviceName | 项目名 | 别名 | 仓库路径 |
|----|----|----|----|
|`order`|`order`|`订单服务,订单`|`/Users/hisense/Documents/workspace/order`|
|`order-batch`|`order`|`订单服务,订单`|`/Users/hisense/Documents/workspace/order`|
|`order-batch-timing`|`order`|`订单服务,订单`|`/Users/hisense/Documents/workspace/order`|
|`h5-loan`|`H5LoanProject`|`借款服务,借款`|`/Users/hisense/Documents/workspace/H5LoanProject`|
|`protocol`|`protocol`|`协议服务,协议`|`/Users/hisense/Documents/workspace/protocol`|
|`protocol-batch`|`protocol`|`协议服务,协议`|`/Users/hisense/Documents/workspace/protocol`|
|`protocol-batch-timing`|`protocol`|`协议服务,协议`|`/Users/hisense/Documents/workspace/protocol`|
|`cif`|`cif`|`客户信息,客户基础信息,客户信息服务`|`/Users/hisense/Documents/workspace/cif`|
|`account`|`account`|`账户信息,客户账户信息`|`/Users/hisense/Documents/workspace/account`|
|`datainquiry`|`data-inquiry`|`数据查询`|`/Users/hisense/Documents/workspace/data-inquiry`|
|`loki-webapp`|`loki`|`loki,loki放款`|`/Users/hisense/Documents/workspace/loki`|
|`weixin-h5api`|`weixin_h5api`|-|`/Users/hisense/Documents/workspace/weixin_h5api`|
|`app-server`|`appServer`|-|`/Users/hisense/Documents/workspace/appServer`|

## 强制规则

### 触发门禁

- 群聊中只有明确 `@Tom` 或 WorkBuddy/Claw 已判定为对 Tom 的直接提及时，才触发日志查询和飞书卡片发送。
- 群聊消息未 `@Tom` 时，立即停止；不要查询 CLS、不要读取本地代码、不要发送飞书卡片，也不要输出诊断结论。
- 私聊 Tom 时不需要 `@Tom`，直接按本技能流程处理，并优先把飞书卡片发送回该私聊会话。
- 触发后，发送目标必须是当前提问来源；无法确认来源或卡片发送失败时，只能在当前会话输出纯文本 fallback。

### 数据统计强制约束

本节规则优先级高于所有其他规则。违反本节规则等同于输出错误结论。

#### 统计模式触发条件

当用户意图包含以下任一关键词时，自动进入**统计模式**：
`统计`、`汇总`、`占比`、`成功率`、`总数`、`计数`、`分布`、`趋势`、`健康检查`、`有多少`、`多少笔`、`有几条`、`总共`、`一共`、`百分比`、`比例`、`平均`、`最多`、`最少`

健康检查（见业务模块 reference 的 Step 0-4）**始终**属于统计模式。

#### 统计模式完整性铁律

1. **完整性优先，API 优先**：统计模式下必须拿到完整数据后才能做数值结论。先用 `scripts/cls_query.py --method auto` 走 CLS HTTP API；API 明确完整时可直接统计。API 返回 `is_complete=false`、`error=INCOMPLETE_DATA` 或 `source=api_failed` 时，降级到 WorkBuddy 内置浏览器打开完整 CLS URL、加载全部结果并校验完整性。

2. **本地 Chrome 备用路径才用 `--require-complete`**：只有明确切换到本地 Chrome 备用路径并调用 `cls_query.py` 执行/提取时，才必须加 `--require-complete`。无此标志的 `cls_query.py` 执行结果禁止用于任何数值统计。

3. **完整性关卡**：先检查结果是否完整；如果 `cls_query.py` 返回 JSON，检查是否存在 `"error": "INCOMPLETE_DATA"`。若存在：
   - 禁止对已加载数据做任何计数、汇总、占比计算
   - 必须按 `suggested_actions` 拆分查询后重试
   - 拆分后仍不完整：飞书兼容文本结论必须在"风险提示:"字段标注"数据不完整/采样值"，所有数值结论加"（采样值，非精确统计）"后缀

4. **禁止跳过关卡**：只要 `is_complete` 为 false，统计模式下所有百分比、总数、成功率结论都无效。不存在"先看看数据再说"——要么数据完整，要么先拆分。

#### 统计模式工作流

```
用户请求 → 识别统计关键词 → cls_query.py --method auto --require-complete
  → source=api 且 is_complete=true → 输出精确统计
  → API 不完整/失败 → WorkBuddy 内置浏览器打开 cls_url → 加载更多直到完整
  → WorkBuddy 不可用/页面操作失败/需要批量自动提取
    → 切换本地 Chrome 备用路径：cls_query.py --method local-chrome --require-complete
      → is_complete=true → 正常分析，输出精确统计
      → error=INCOMPLETE_DATA → 按 suggested_actions 拆分
        → 每段都 --require-complete → 合并完整段数据 → 输出统计
        → 某段仍不完整 → 飞书兼容文本风险提示 + "采样值" 标注
```

#### 非统计模式

流程追踪（根因分析、单笔排查）不要求 `--require-complete`。部分数据足以定位根因时，可正常分析。

### 查询方法
- **查询前置条件（强制）**：
  - **用户提供了 traceId**：可以直接到日志平台用 `traceId:"{value}"` 查询
  - **用户未提供 traceId**：**必须先分析本地业务代码**，理解业务流程和日志打印逻辑后，再构造查询到日志平台查询。禁止以任何理由（包括路径不匹配、嫌麻烦等）跳过本地业务分析
- **环境默认规则**：用户未指定环境时，**必须查生产环境（prod）**。只有用户明确说"查测试环境"时才使用测试 topic。禁止自行假设或优先查测试环境。
- **traceId 查询与提取**：
  - **用户提供 traceId**：直接执行 `traceId:"{value}"`（不加 `serviceName`）；查不到时扩大时间：`now-1d,now` → `now-7d,now` → `now-30d,now`
  - **用户未提供 traceId**：按后续步骤用业务标识符定位日志后，从提取的 innerText 中识别 `traceid` 列值（通常为 16 位或 32 位 hex，如 `110e6550d81fb1bc`、`b4d5cc63c42611adb4d5cc63c42611ad`），再执行 `traceId:"{提取值}"` 做全链路分析；不要自行截断成前 16 位
  - **traceId ≠ TID**：两者是不同的索引字段，不要混淆。以 `traceid` 列为准
- 日志无法获取明确结果时可结合项目代码
- 每次会话首次执行**代码锚点**校验前，按 `references/common/update-master-branch.md` 更新对应服务仓库的 master 分支（路径见映射表`仓库路径`列）
- 本组范围查询时，服务范围以"日志服务名和项目名映射关系表"的 `serviceName` 列为准；需要看代码时，再用同一行的`项目名`和`仓库路径`定位源码。
- 分析要查的数据是否在子模块的流程追踪入口，是的话可以通过日志锚点查询，不是的话分析本地项目路径，确认查询`sql`,服务名参考上面`日志服务名和项目名映射关系表`；子模块入口表格里的推荐查询只是通过代码锚点校验后的首查模板，不是唯一真相。
- 执行入口表格推荐查询前，先校验 `方法入口`、`serviceName` 和固定 `message` 片段是否仍能和当前代码匹配；可用 `scripts/validate_query_anchors.py` 辅助检查。
- 标识符值优先直接放入 `message:\"{value}\"`，禁止加 `cid:`、`orderId:`、`contractNo:`
- 日志查询 SQL 中如果包含中文，优先走 `scripts/cls_query.py --method api/auto`，API 路径直接传原始查询语句，不受 `queryBase64` 限制。只有浏览器 fallback URL 需要 ASCII `url_query`；必要时再读取 `references/common/cls-react-contenteditable-injection.md` 做页面注入。
- **分页未加载完** — CLS 每页只显示 20 条，`load_more_clicks` 是否足够？检查 `log_count` 字段
- 日志平台查询常用 key 见下文"查询语法与字段"段。

### 推荐查询锚点校验

各业务模块 reference 的`流程追踪入口`：`场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明`。

- `方法入口` 存在且 `serviceName` 与源码项目匹配、固定 `message:\"...\"` 片段仍在该入口类/方法附近命中时，才把推荐查询作为 Phase A 主查询。
- 方法存在但固定 message 不匹配时，不要把旧模板当主路径；改用 `serviceName:\"{服务}\" AND message:\"{标识符}\"`，并 grep 当前代码找新日志前缀。
- 方法不存在、源码缺失或服务不匹配时，标记模板疑似过期；先按 traceId/标识符值搜，再回代码确认入口。
- 推荐查询 0 命中时，继续扩大时间做值搜，如果能搜到日志，说明`sql`没问题，在目标查询时间段没有命中；当扩大到当前时间前一个月还没日志信息时，停止搜索，去本地项目内
 
### 日志查询无结果排查清单

查询返回 0 条时，**不要立即归因于查询语法**。按顺序排查：

1. **时间窗口** — `now-1d,now` 是否真的覆盖了日志产生时间？扩大至 `now-7d,now` 或 `now-30d,now` 验证，能查到日志，说明`sql`语法没问题；扩大到`now-30d,now`仍然查不到时，进行第2步校验
2. **topic 是否正确** — CLS hide* params 可能导致 topic 随机丢失，确认 topic_id 无误
3. **`=` 等号查询退化** — 如果查询含 `message:\"字段=值\"` 且 `log_count` 显示为 topic 总量（数百万级），说明 CLS 退化为全量返回。加 `AND level:\"WARN\"/\"INFO\"` 等额外约束可恢复精确过滤。此时应以实际加载出的日志内容为准
4. **最后才怀疑语法** — 大部分**语法问题**是时间窗口或分页导致的，此时需要将查询`sql`本地项目做关联，确认日志是否过期，若日志过期提醒用户更新

### API、内置浏览器和本地浏览器优先级

- 优先用 `scripts/cls_query.py --method auto`。默认先请求 CLS 内部 HTTP API，不需要浏览器、不需要 `secret_id/secret_key`，查询中可直接包含中文。
- API 返回 `source=api_failed` 或 `is_complete=false` 时，使用输出中的 `cls_url` 交给 WorkBuddy 内置浏览器打开。URL 必须包含 `topic_id`、`time`、`queryBase64`，避免依赖页面默认状态。
- 本地 Chrome + AppleScript 是最后备用路径：当 WorkBuddy 登录态不可用、页面操作失败、需要脚本自动加载更多或批量全文提取时，显式使用 `scripts/cls_query.py --method local-chrome --use-local-chrome`。
- 使用本地 Chrome 备用路径时，禁止默认操作 `active tab of front window`。首次查询创建新的 Chrome window，后续查询复用该窗口，通过 window id 定向操作；调查结束后调用 `scripts/cls_query.py --close` 关闭窗口。
- 不要用 `document.body.innerText.substring(0,N)` 判断结果；CLS 日志数据在页面文本后部。
- `traceId` 查询也可能超过 20 条；必须加载全部数据进行解析
- **分析前必须校验完整性**：统计模式下见上方"⛔ 数据统计强制约束"。非统计模式下：对比 `log_count` 与 `loaded_count`，若 `is_complete` 为 false 或 `loaded_count` 远小于 `log_count`，在"风险提示:"字段标注"基于 N/M 条采样分析，结论可能不完整"。

### 结论输出规则

- 诊断结论必须先调用 `scripts/send_feishu_card.py` 发送飞书交互式卡片到当前提问来源；发送脚本返回非 0 时，才降级为当前会话纯文本 fallback。禁止在未调用发送脚本前直接输出最终文本结论。
- 飞书卡片消息格式：
  - 可以使用卡片 native table、lark_md、代码块、链接和按钮。
  - 群聊卡片可在正文中 @ 提问者；私聊场景不需要 @。
  - CLS 链接必须包含 `topic_id`、`time`、`queryBase64`；当结果集中在单线程时，URL 只带 `traceId` 即可。
- 纯文本 fallback 格式契约：
  - 允许：普通文本、换行、简单分段、短横线列表、数字编号、粗体标签、普通 URL 或 `[文本](URL)` 链接、@。
  - 禁止：Markdown 表格、表格分隔线、代码块、HTML 表格、复杂嵌套列表、飞书卡片语法。
  - 输出前必须自检：如果最终回复中出现 `| 时间 | 服务 | 事件 |`、`|---|---|`、`|-----|-----|`、任意以 `|` 开头且包含多个 `|` 分隔列的行，必须改写成逐行列表；如果出现 fenced code block，必须改写成普通文本。
- 每次结论须包含：查了什么代码/日志前缀、CLS 查询语句/topic/时间范围、命中摘要与未命中证据、完整性状态（`loaded_count` vs `log_count`）、关键节点时间（`timestamp` 格式）、CLS URL 链接、卡片发送状态。

### 来源识别与飞书卡片发送

技能被触发后，在输出最终结论前执行以下流程：

1. **必须先调用发送脚本**：最终结论生成后，先执行 `send_feishu_card.py`。不要先输出普通文本结论；只有发送脚本返回非 0 或明确失败状态时，才输出纯文本 fallback。

2. **来源优先级**：`--chat` 是人工显式指定目标，优先级最高。WorkBuddy 正常路径必须使用 `--resolve-chat --query "{用户原始问题}"`，并以精确反查得到的唯一 `chat_id` 作为发送目标。`FEISHU_CURRENT_CHAT_ID` / `AGENT_CURRENT_CHAT_ID` 等环境变量只作为未传 `--resolve-chat` 时的兼容路径，不能覆盖或短路精确反查结果。

3. **反查来源**：`--resolve-chat` 必须用用户原始问题文本精确搜索最近时间窗内的群聊 @Bot 消息和私聊 p2p 消息。`{用户原始问题}` 使用触发 Tom 的原始问题正文；群聊去掉 `@Tom` 和首尾空白，私聊直接使用用户输入正文；不要改写、总结或替换成分析后的标题。

   群聊来源搜索：
   ```bash
   LARK_CLI_NO_PROXY=1 lark-cli im +messages-search \
     --as user \
     --query "{用户问题文本}" \
     --chat-type group \
     --sender-type user \
     --at-chatter-ids "ou_ae0341a3578d833a22b5f2927b103988" \
     --start "{当前时间 - 15 分钟}" \
     --page-limit 1 \
     --format json
   ```

   私聊来源搜索：
   ```bash
   LARK_CLI_NO_PROXY=1 lark-cli im +messages-search \
     --as user \
     --query "{用户问题文本}" \
     --chat-type p2p \
     --sender-type user \
     --start "{当前时间 - 15 分钟}" \
     --page-limit 1 \
     --format json
   ```

4. **获取详情**：用 Bot 身份获取消息详情（含 chat_id、sender）。
   ```bash
   LARK_CLI_NO_PROXY=1 lark-cli im +messages-mget \
     --message-ids "{message_id}" \
     --as bot
   ```

5. **解析结果**：提取 `chat_id`、`chat_type`、`sender.open_id`。
   - 群聊和私聊合并后命中 0 条 → 搜不到来源，fallback 为当前会话纯文本
   - 群聊和私聊合并后命中 1 条，且 `messages-mget` 返回的 `chat_type` 与搜索分支一致 → 唯一匹配，发卡片到该 chat_id
   - 群聊和私聊合并后命中 ≥2 条 → 来源不唯一，不发卡片，fallback 当前会话纯文本，并说明最近 15 分钟窗口内同 query 多命中
   - 搜索分支与 `messages-mget` 的 `chat_type` 不一致 → 来源异常，不发卡片，fallback 当前会话纯文本

6. **发送卡片**：
   ```bash
   python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py \
     --resolve-chat --query "{用户原始问题}" \
     --resolve-window-minutes 15 \
     --at-sender \
     --title "..." --color "..." --data "..."
   ```
   - 正常路径必须保留 `--resolve-chat --query`；只要传入 `--resolve-chat`，脚本就必须使用原始问题 + 时间窗精确反查群聊和私聊来源，环境变量不得短路发送目标
   - `--at-sender` 只在能拿到 sender 且 `chat_type=group` 时生效；私聊不会 @
   - 需要人工指定目标时可传 `--chat "{chat_id}"`
   - 发送脚本返回 `status: "sent"` → 不再输出重复纯文本结论
   - 发送脚本非 0、`status: "unresolved"` 或 `status: "ambiguous"` → 当前会话输出飞书兼容纯文本结论，并说明卡片失败原因
   - 如果环境变量 chat_id 与精确反查 chat_id 不一致，发送脚本仍使用精确反查结果，并在状态中记录 `env_chat_conflict`
   - 最近 15 分钟窗口外的历史相同问题不算多命中；窗口内群聊/私聊合计多条相同 query 才算来源歧义
   - 如果最终结论已经以普通文本输出，但本轮没有 `send_feishu_card.py` 调用记录，视为违反本技能输出规则

## 意图分类

| 意图 | 识别特征 | 查询策略 |
|------|---------|---------|
| 数据统计 | 统计、汇总、占比、成功率、总数、计数、健康检查、有多少、多少笔 | API 优先并强制完整性；API 不完整则 WorkBuddy；本地 Chrome 备用路径才用 `--require-complete` |
| 流程追踪 | 借款、下单、放款、还款、权益、签约、绑卡、指定 `traceId`/`orderId`/`contractNo` | 路由到业务模块 reference，按入口日志定位 `traceId`，再查全链路 |
| 健康检查 | 最近有没有异常、无具体标识符 | 使用业务模块 reference 的总览式查询步骤 |
| SSO/登录 | 浏览器 fallback 跳转 Argus/JANUS/PMP 登录 | 使用 `xh-sso-access` |

## 业务路由

用户问"我们组"、"客户订单组"、"这批服务"的整体日志、异常、健康情况时，不需要再追问服务范围；按上方映射表 `serviceName` 列覆盖全部客户订单组服务。若用户同时给出具体业务关键词，再按下表选择业务模块并在该模块内覆盖相关服务。

用户问表中`别名`对应的整体日志、异常、健康情况时，不需要追问具体 `serviceName`；按同别名的全部 `serviceName` 查询。用户明确写出具体 `serviceName` 时，才只查该单个服务。

| 关键词 | 业务模块 reference | 业务模块 |
|--------|---------|--------|
| 签约、重签、重新签约、RESIGN、SIGNING_ISSUE、协议、绑卡、银行卡签约、代扣协议、支付协议 | `references/modules/sign.md` | 签约模块 |
| 下单、端内（自营）下单、api下单、订单、拦截、反欺诈、借款能力预检、预检、借款试算、试算 | `references/modules/order.md` | 下单模块 |
| 权益、会员、VIP、优惠券、乐活卡、coupon、尊享卡、拒就赔、加速卡、获额卡、返现券 | `references/modules/benefit.md` | 权益模块 |
| 放款、资金路由、route、解H、loki放款、拒就赔、提前结清、特项额度 | `references/modules/loan.md` | 放款模块 |
| 还款、扣款、逾期、代扣、结清、repay、债转、好友代付、聚合支付 | `references/modules/repay.md` | 还款模块 |

匹配不到业务模块时，先问用户确认。

## 标准工作流

1. 提取环境、时间范围、标识符和服务范围；服务范围按"具体 `serviceName` → 表中`别名`对应服务组 → 我们组/客户订单组全表服务"识别 → 分类意图 → 路由到业务模块 reference。
2. 代码锚点校验（规则见上文"推荐查询锚点校验"），组装 CLS 查询。
3. **判断是否为统计模式（见"数据统计强制约束"）。是 → `cls_query.py --method auto --require-complete`；API 完整才可统计。**
4. 非统计模式默认 `cls_query.py --method auto`。API 不可用或结果不完整时，用返回的 `cls_url` 交给 WorkBuddy 内置浏览器；必要时再显式切换本地 Chrome 备用路径。
5. 0 命中时按"无结果排查清单"回退。
6. 分析日志 → 执行「来源识别与飞书卡片发送」→ 优先发送飞书卡片。发送失败、来源缺失或歧义时 fallback 为当前会话纯文本。仅使用本地 Chrome 备用窗口时，最后调用 `cls_query.py --close` 关窗口。

## CLS 工具

### 默认：API 优先查询

`cls_query.py` 默认使用 `--method auto`：先走 CLS HTTP API；API 失败或无法确认完整时，返回 `fallback_method: "workbuddy"` 和完整 `cls_url`。只有显式 `--method local-chrome` 或 `--use-local-chrome` 才会打开本地 Chrome。

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py \
  --env prod \
  --query 'serviceName:"order" AND message:"20161002000002677537"'
```

API 成功时输出 JSON 包含：

- `source: "api"`：来自 HTTP API
- `logs`：结构化日志数组
- `output_path`：同步写出的文本文件路径
- `loaded_count/log_count/is_complete`：完整性状态
- `fallback_method: "workbuddy"`：API 不完整时的下一步

### WorkBuddy URL fallback，不打开浏览器

旧的纯 URL 构造方式保留为 `--method workbuddy`，`--no-browser` 也会兼容转入该模式。

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py \
  --method workbuddy \
  --env prod \
  --query 'serviceName:"order" AND level:"ERROR"' \
  --no-browser
```

### 备用：本地 Chrome 专用窗口并提取文本

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py \
  --method local-chrome \
  --env prod \
  --time 'now-7d,now' \
  --query 'traceId:"37426d42fdc699d1"' \
  --output /tmp/cls_output.txt \
  --use-local-chrome
```

工具输出 JSON，包含：

- `cls_url`：本次查询跳转链接
- `expanded_url`：扩大时间范围链接
- `output_path`：本地 Chrome 备用路径提取的全文路径
- `log_count`：从\"日志条数\"解析出的结果数（注意：含 `=` 的查询可能退化为全量返回，log_count 不可靠）
- `completeness_ratio`：加载比例（0.0~1.0），统计模式下必须为 1.0
- `services`：提取到的服务名
- `contracts`：提取到的 CK/CS 合同号
- 统计模式不完整时额外返回：`error`, `error_message`, `action_required`, `suggested_actions`, `PROHIBITION`

### 备用：本地 Chrome 统计模式查询（强制完整数据）

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py \
  --method local-chrome \
  --env prod \
  --time 'now-1d,now' \
  --query 'serviceName:"order" AND level:"ERROR"' \
  --output /tmp/cls_output.txt \
  --require-complete \
  --use-local-chrome
```

仅在 WorkBuddy 不可用、页面操作失败或需要批量自动提取时使用此备用路径。统计模式下调用 `cls_query.py` 执行/提取必须使用 `--require-complete`；工具自动加载更多数据（最多 200 次）。仍不完整时返回 `error: INCOMPLETE_DATA` 和拆分建议，此时禁止分析已有数据。

### 中文查询

API 路径直接支持中文查询，例如 `serviceName:"order" AND message:"签约"`。浏览器 URL fallback 仍受 `queryBase64` 限制：工具会自动生成 ASCII-safe `url_query`，必要时再通过页面查询框注入中文或从提取全文中二次过滤。详见 `references/common/cls-react-contenteditable-injection.md`。

### 校验入口表锚点

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/validate_query_anchors.py \
  --all --summary
```

`--all` 自动发现 `references/modules/*.md`，`--summary` 输出汇总表。校验不通过时，推荐查询只能作为历史线索。

## CLS 环境与查询语法

| 环境 | topic_id | 默认时间 |
|------|----------|----------|
| 生产 | `f6748b3a-8ab8-4191-b848-cb90b1598901` | `now-7d,now` |
| 测试 | `1f92a7ca-cf46-4f4f-92dd-72c5df5910dc` | `now-1d,now` |

URL: `https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id={topic_id}&time={start},{end}&queryBase64={base64_query}`

语法：`field:"value"` + `AND` / `OR`，所有字段值统一加引号。

| 字段 | 类型 | 说明 |
|------|------|------|
| **serviceName** | 索引 | 参考上面映射表，如 `serviceName:"order"` |
| **level** | 索引 | `INFO`/`ERROR`/`WARN`/`DEBUG` |
| **traceId** | 索引 | 按 traceId 查时一般不拼其它条件 |
| **requestId** | 索引 | |
| **env** | 非索引 | 默认 `prod`；测试环境未指定具体 test 编号时不加此条件 |
| **message** | 全文 | orderId、cid、contractNo 等非索引字段通过 message 搜索 |

## 飞书卡片结论与纯文本 fallback

最终结论优先使用飞书卡片。只有卡片发送失败、来源缺失或歧义时，才使用字段化纯文本 fallback，避免表格、代码块、复杂嵌套列表和卡片语法。fallback 推荐结构：

结论: 一句话说明结果、根因或当前健康状态。
查询范围: 环境、时间范围、topic、CLS 查询语句。
命中摘要: 命中数量、关键 traceId/orderId/contractNo/cid、完整性状态。
关键证据: 按时间顺序列出关键日志节点，保留原始时间戳；多条证据必须用换行和短横线分隔，不得使用表格。
- 15:30:50.784 thor-app-gateway: 发起还款试算，orderId=...
- 15:30:50.813 order: ERROR NullPointerException ...
风险提示: 数据不完整、采样分析、查询失败或无结果时必须说明；无风险时写"暂无"。
链接: 附 `cls_url` 和必要时的 `expanded_url`。

## References

- `references/common/update-master-branch.md`：更新本地 `master` 分支代码
- `references/common/cls-local-chrome-access.md`：备用：本地 Chrome 专用窗口访问 CLS
- `references/common/cls-dom-extraction.md`：全文提取、加载更多、CK/CS 合同号解析
- `references/common/cls-query-pitfalls.md`：CLS 高频坑和恢复方式
- `references/common/cls-api-query.md`：CLS HTTP API 直查 payload、返回结构和 fallback 规则
- `references/common/chinese-queryBase64-experiments.md`：中文 queryBase64 限制
- `references/common/cls-react-contenteditable-injection.md`：React contenteditable 中文注入方案（String.fromCharCode + execCommand）
- `references/common/trace-dubbo-profile-filter.md`：Dubbo 全链路追踪（ProfileFilter CS/CR/SS/SR 标记解读 + 溯源方法论）
- `references/common/cls-topic-field-reference.md`：CLS Topic 字段对照表（生产/测试环境 topic 属性与索引字段）
- `references/common/efficient-query-pattern-20260517.md`：高效查询工作流（查询耗时优化、CLS 页面异常处理）
- `references/common/cls-iframe-crossorigin-workflow.md`：历史废弃 iframe 方案，只作背景
