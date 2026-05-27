---
name: xh-log-lookup
description: 当用户需要查询生产或测试环境 CLS/Argus 日志、定位借款/下单/签约/权益/放款/还款问题，或需要 traceId/orderId/cid/contractNo/mobile/idNo 排查时使用。
allowed-tools:
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/validate_query_anchors.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/resolve_workspace.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py *)
disable: false
---

# xh-log-lookup — 日志查询主控

处理生产/测试环境日志查询、业务异常排查、CLS 结果及根因分析和**飞书卡片输出**。主控只负责意图分类、路由、强制约束和工具调用；业务细节在 `references/modules/` 和 `references/common/` 中。

## 日志服务名和项目名映射关系表

`仓库路径`列为空或路径不存在时，执行 `scripts/resolve_workspace.py` 自动探测并更新映射表。
| serviceName | 项目名 | 仓库路径 |
|----|----|----|
|`order`|`order`|`/Users/hisense/Documents/workspace/order`|
|`order-batch`|`order`|`/Users/hisense/Documents/workspace/order`|
|`order-batch-timing`|`order`|`/Users/hisense/Documents/workspace/order`|
|`h5-loan`|`H5LoanProject`|`/Users/hisense/Documents/workspace/H5LoanProject`|
|`protocol`|`protocol`|`/Users/hisense/Documents/workspace/protocol`|
|`protocol-batch`|`protocol`|`/Users/hisense/Documents/workspace/protocol`|
|`protocol-batch-timing`|`protocol`|`/Users/hisense/Documents/workspace/protocol`|
|`cif`|`cif`|`/Users/hisense/Documents/workspace/cif`|
|`account`|`account`|`/Users/hisense/Documents/workspace/account`|
|`datainquiry`|`data-inquiry`|`/Users/hisense/Documents/workspace/data-inquiry`|
|`loki-webapp`|`loki`|`/Users/hisense/Documents/workspace/loki`|
|`weixin-h5api`|`weixin_h5api`|`/Users/hisense/Documents/workspace/weixin_h5api`|
|`app-server`|`appServer`|`/Users/hisense/Documents/workspace/appServer`|

## 强制规则

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
   - 拆分后仍不完整：飞书卡片用黄色（yellow），所有数值结论加"（采样值，非精确统计）"后缀

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
        → 某段仍不完整 → 黄色卡片 + "采样值" 标注
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
- **分析前必须校验完整性**：统计模式下见上方"⛔ 数据统计强制约束"。非统计模式下：对比 `log_count` 与 `loaded_count`，若 `is_complete` 为 false 或 `loaded_count` 远小于 `log_count`，在飞书卡片中标注"基于 N/M 条采样分析，结论可能不完整"并使用黄色卡片。

### 飞书输出与结论规则

- 所有诊断结论、分析报告必须通过 `scripts/send_feishu_card.py` 发送飞书卡片，禁止直接写进聊天。只有脚本执行失败时才降级为 Markdown。
- 卡片 **URL** 必须包含 `topic_id`、`time`、`queryBase64`；当结果集中在单线程时，URL 只带 `traceId` 即可。
- 每次结论须包含：查了什么代码/日志前缀、CLS 查询语句/topic/时间范围、命中摘要与未命中证据、完整性状态（`loaded_count` vs `log_count`）、关键节点时间（`timestamp` 格式）、卡片发送状态。

## 意图分类

| 意图 | 识别特征 | 查询策略 |
|------|---------|---------|
| 数据统计 | 统计、汇总、占比、成功率、总数、计数、健康检查、有多少、多少笔 | API 优先并强制完整性；API 不完整则 WorkBuddy；本地 Chrome 备用路径才用 `--require-complete` |
| 流程追踪 | 借款、下单、放款、还款、权益、签约、绑卡、指定 `traceId`/`orderId`/`contractNo` | 路由到业务模块 reference，按入口日志定位 `traceId`，再查全链路 |
| 健康检查 | 最近有没有异常、无具体标识符 | 使用业务模块 reference 的总览式查询步骤 |
| SSO/登录 | 浏览器 fallback 跳转 Argus/JANUS/PMP 登录 | 使用 `xh-sso-access` |

## 业务路由

| 关键词 | 业务模块 reference | 业务模块 |
|--------|---------|--------|
| 签约、重签、重新签约、RESIGN、SIGNING_ISSUE、协议、绑卡、银行卡签约、代扣协议、支付协议 | `references/modules/sign.md` | 签约模块 |
| 下单、端内（自营）下单、api下单、订单、拦截、反欺诈、借款能力预检、预检、借款试算、试算 | `references/modules/order.md` | 下单模块 |
| 权益、会员、VIP、优惠券、乐活卡、coupon、尊享卡、拒就赔、加速卡、获额卡、返现券 | `references/modules/benefit.md` | 权益模块 |
| 放款、资金路由、route、解H、loki放款、拒就赔、提前结清、特项额度 | `references/modules/loan.md` | 放款模块 |
| 还款、扣款、逾期、代扣、结清、repay、债转、好友代付、聚合支付 | `references/modules/repay.md` | 还款模块 |

匹配不到业务模块时，先问用户确认。

## 标准工作流

1. 提取环境、时间范围、标识符 → 分类意图 → 路由到业务模块 reference。
2. 代码锚点校验（规则见上文"推荐查询锚点校验"），组装 CLS 查询。
3. **判断是否为统计模式（见"数据统计强制约束"）。是 → `cls_query.py --method auto --require-complete`；API 完整才可统计。**
4. 非统计模式默认 `cls_query.py --method auto`。API 不可用或结果不完整时，用返回的 `cls_url` 交给 WorkBuddy 内置浏览器；必要时再显式切换本地 Chrome 备用路径。
5. 0 命中时按"无结果排查清单"回退。
6. 分析日志 → `scripts/send_feishu_card.py` 发卡片。仅使用本地 Chrome 备用窗口时，最后调用 `cls_query.py --close` 关窗口。

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

## 飞书卡片

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py \
  --title "[emoji] 场景简述 · 时间范围" --color green \
  --cls-url "{cls_url}" --cls-url-expanded "{expanded_url}" \
  --data '{"summary_fields":[...],"analysis":"...","log_count":N}'
```

颜色：

| 颜色 | 使用条件 |
|------|----------|
| `red` | ERROR、堆栈、流程阻断、查询未正常执行 |
| `yellow` | WARN、业务异常、逾期、无结果但查询正常、不完整采样 |
| `green` | 全部正常、全部 SUCCESS |
| `blue` | 常规信息查询 |

### 结果输出前自检

当你准备在聊天中写出诊断结论时——**停下来**，把结论写进 `send_feishu_card.py` 的 `--data '{"analysis":"..."}'`，不要写进聊天。

## References

- `references/common/update-master-branch.md`：更新本地 `master` 分支代码
- `references/common/cls-local-chrome-access.md`：备用：本地 Chrome 专用窗口访问 CLS
- `references/common/cls-dom-extraction.md`：全文提取、加载更多、CK/CS 合同号解析
- `references/common/cls-query-pitfalls.md`：CLS 高频坑和恢复方式
- `references/common/cls-api-query.md`：CLS HTTP API 直查 payload、返回结构和 fallback 规则
- `references/common/chinese-queryBase64-experiments.md`：中文 queryBase64 限制
- `references/common/cls-react-contenteditable-injection.md`：React contenteditable 中文注入方案（String.fromCharCode + execCommand）
- `references/common/feishu-card-template.md`：飞书卡片结构和按钮 URL 规则
- `references/common/feishu-card-callback-handling.md`：飞书卡片按钮回调
- `references/common/trace-dubbo-profile-filter.md`：Dubbo 全链路追踪（ProfileFilter CS/CR/SS/SR 标记解读 + 溯源方法论）
- `references/common/cls-topic-field-reference.md`：CLS Topic 字段对照表（生产/测试环境 topic 属性与索引字段）
- `references/common/efficient-query-pattern-20260517.md`：高效查询工作流（查询耗时优化、CLS 页面异常处理）
- `references/common/cls-iframe-crossorigin-workflow.md`：历史废弃 iframe 方案，只作背景
