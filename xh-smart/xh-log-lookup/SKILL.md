---
name: xh-log-lookup
description: 当用户需要查询生产或测试环境 CLS/Argus 日志、定位借款/下单/签约/权益/Hold单/解H/放款/还款/债转问题，使用 traceId/orderId/cid/contractNo/mobile/idNo 排查，或基于本地源码梳理业务流程、调用链、条件分支、字段语义时使用。
allowed-tools:
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/validate_query_anchors.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/resolve_workspace.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/source_inspect.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py *)
  - Bash(python3 ${WORKBUDDY_SKILL_DIR}/scripts/resolve_hermes_session.py *)
  - Bash(LARK_CLI_NO_PROXY=1 lark-cli im +messages-search *)
  - Bash(LARK_CLI_NO_PROXY=1 lark-cli im +messages-mget *)
  - Bash(LARK_CLI_NO_PROXY=1 lark-cli im +messages-send *)
disable: false
---

# xh-log-lookup — 日志与业务逻辑分析主控

处理生产/测试环境日志查询、业务异常排查，以及借款、下单、签约、权益、Hold、放款、还款、债转八个模块的本地业务逻辑分析。结论必须优先通过飞书卡片输出，失败时降级为飞书兼容文本。主控只负责意图分类、模式选择、业务路由、强制约束和工具调用；业务细节在 `references/modules/` 和 `references/common/` 中。

## 日志服务名和项目名映射关系表

这张表是客户订单组负责的日志服务清单。`serviceName` 列用于 CLS 查询范围，`别名`列用于把用户自然语言服务名映射到一组 `serviceName`，`项目名`列只用于定位本地源码仓库；三者不要混用。

服务范围识别按以下优先级执行：
- **业务链路查询优先于服务别名扩范围**：先判断用户是否在问具体业务链路，再决定服务范围。用户说"下单异常"、"借款下单异常"、"下单成功/失败"、"下单链路异常"、"拦截"时，默认是下单业务链路查询，必须走 `references/modules/order.md` 的下单锚点，不得因为"订单"二字自动扩成 `order/order-batch/order-batch-timing` 服务组。
- 用户明确说出具体 `serviceName`（如 `order`、`protocol-batch`）时，只查该单个服务。
- 用户说出表中某个`别名`且是在问整体日志、服务异常、服务健康或服务组情况时，查所有同别名行对应的 `serviceName`。`别名`列可填写多个自然语言别名，使用中文逗号 `，` 或英文逗号 `,` 分隔。
- 用户说"我们组"、"客户订单组"、"这批服务"或没有指定具体服务但要求查看本组日志情况时，默认以本表 `serviceName` 列的全部服务作为查询覆盖范围。

同一个`别名`可对应多个 `serviceName`，同一个 `serviceName` 也可以挂多个别名。例如"订单服务异常"要展开到表中所有包含`订单服务`或`订单`别名的服务后再查询和分析；但"下单异常"属于业务链路查询，不能按"订单"别名扩成订单服务组。

`仓库路径`列是本地缓存，不是跨机器固定路径。路径为空或失效时，先执行 `scripts/resolve_workspace.py --check` 诊断；确认无误后再执行 `scripts/resolve_workspace.py` 更新映射表。

推荐通过 `XH_WORKSPACE_ROOTS` 配置工作区根目录，可配置多个根目录，用 `:` 分隔。每个根目录会按 `{root}/{项目名}` 和 `{root}/workspace/{项目名}` 查找仓库。

示例：`XH_WORKSPACE_ROOTS="/Users/user/mingh/workspace:/Users/hisense/Documents/workspace"`

| serviceName | 项目名 | 别名 | 仓库路径 |
|----|----|----|----|
|`order`|`order`|`订单服务,订单`|`/Users/user/mingh/workspace/order`|
|`order-batch`|`order`|`订单服务,订单`|`/Users/user/mingh/workspace/order`|
|`order-batch-timing`|`order`|`订单服务,订单`|`/Users/user/mingh/workspace/order`|
|`h5-loan`|`H5LoanProject`|`借款服务,借款`|`/Users/user/mingh/workspace/H5LoanProject`|
|`protocol`|`protocol`|`协议服务,协议`|`/Users/user/mingh/workspace/protocol`|
|`protocol-batch`|`protocol`|`协议服务,协议`|`/Users/user/mingh/workspace/protocol`|
|`protocol-batch-timing`|`protocol`|`协议服务,协议`|`/Users/user/mingh/workspace/protocol`|
|`cif`|`cif`|`客户信息,客户基础信息,客户信息服务`|`/Users/user/mingh/workspace/cif`|
|`account`|`account`|`账户信息,客户账户信息`|`/Users/user/mingh/workspace/account`|
|`datainquiry`|`data-inquiry`|`数据查询`|`/Users/user/mingh/workspace/data-inquiry`|
|`loki-webapp`|`loki`|`loki,loki放款`|`/Users/user/mingh/workspace/loki`|
|`fund-center`|`fund-center`|`fund-center,fundCenter,资金管理系统,资金管理平台`|`/Users/user/mingh/workspace/fund-center`|
|`weixin-h5api`|`weixin_h5api`|-|`/Users/user/mingh/workspace/weixin_h5api`|
|`app-server`|`appServer`|-|`/Users/user/mingh/workspace/appServer`|

## 强制规则

### 触发前提与来源约束

- 本技能只处理已由 WorkBuddy/Claw 触发的请求：私聊 Tom，或群聊中明确 `@Tom` / 被判定为对 Tom 的直接提及。
- 如果运行上下文显示这是群聊消息且未直接提及 Tom，应立即停止；不要查询 CLS、不要读取本地代码、不要发送飞书卡片，也不要输出诊断结论。
- 私聊 Tom 时不需要 `@Tom`，直接按本技能流程处理，并优先把飞书卡片发送回该私聊会话。
- 触发后，发送目标优先是当前提问来源；反查阶梯全部跑完仍无法确认来源时，默认降级为当前会话纯文本 fallback（由 WorkBuddy 回复通道送达发起人），不再自动堆到 `WORKBUDDY_HOME_CHANNEL_CHAT_ID`（该静态兜底仅在显式传 `--allow-home-channel-fallback` 时启用）。

### 分析模式选择

本技能只处理上述八个业务模块的分析和解释请求，**不处理代码修改、功能开发、重构或修 Bug**。用户要求修改实现时退出本技能，交给正常编码流程。

模式优先级如下：

1. 用户明确说“不查日志”“只看代码”“只看本地源码”时，强制使用 `local_logic`。
2. 用户同时要求梳理逻辑和核对线上/测试实际情况时，使用 `combined`。
3. 用户明确要求查日志、给出环境/时间窗口/实例标识符，或要求定位实际故障时，使用 `log_diagnosis`。
4. 用户仅询问业务流程、调用链、条件分支、字段语义、类或方法职责时，使用 `local_logic`。

### `local_logic`

- 按“业务路由”选择唯一 module reference，reference 只用于导航；最终结论必须通过 `source_inspect.py` 回到实际源码验证。
- 先执行 `source_inspect.py --project {项目名} --status`，记录仓库、当前分支、Commit 和工作区状态；未指定分支时读取当前本地分支及未提交工作区内容，不 fetch、不 pull、不 checkout。
- 用户明确指定分支但当前分支不一致时，停止源码分析并请用户自行切换或确认使用当前分支；本技能不得代为切换。
- 用 `--search` 定位类、方法、字段、MQ/RPC 调用和条件分支，再用 `--file --start-line --end-line` 读取必要片段。禁止凭 reference 内容冒充当前源码结论。
- **禁止调用 `cls_query.py`**。用户明确不查日志时，不得因结论不完整而擅自升级到日志查询。
- 源码路径失效时先执行 `resolve_workspace.py --check`；无法唯一定位时停止分析，发送阻塞说明，不得猜测业务逻辑。
- 最终调用 `send_feishu_card.py --content-mode business-logic`。`summary_fields` 必须包含：业务模块、仓库、分支、Commit、工作区状态、分析范围；`table_data` 至少包含“步骤 / 类或方法 / 关键逻辑”；`analysis` 写核心结论、外部依赖、未确认项和源码依据。

### `log_diagnosis`

- 保留现有 CLS/Argus 查询、统计完整性、SQL 条件下沉、锚点校验和日志卡片规则。
- 出现**日志无结果、证据不足、业务入口不明确、查询锚点失效、字段语义无法确认或无法仅凭日志确定根因**任一情况时，自动升级为 `combined`，无需再次询问用户。
- 日志证据已经足以支持结论时，继续使用 `send_feishu_card.py --content-mode log`。

### `combined`

- 先读取源码建立预期业务链路和判断条件，再查询日志验证实际执行路径；禁止先给日志下结论再补源码包装。
- 源码分析使用与 `local_logic` 相同的 `source_inspect.py` 只读流程；日志分析继续遵守所有 CLS 强制规则，但分支处理以本节只读规则为准，**不执行 `update-target-branch.md` 的 fetch、stash、checkout 或 pull 步骤**。
- 生产源码目标分支默认是 `master`；测试源码目标分支必须由用户给出或确认。用 `--status` 比较当前分支与目标分支；**当前分支与目标分支不一致**或测试分支未经确认时，标记“源码验证阻塞”，继续交付可用日志证据，但不得用当前源码给出确定联合结论。
- 源码不可用时可继续交付已有日志证据，但必须标记“源码验证阻塞”；日志不可用时只能输出已验证的源码预期逻辑，不得声称实际请求按该路径执行。
- 最终调用 `send_feishu_card.py --content-mode combined`，同时提供源码 `table_data`、日志 `call_chain/log_count`、CLS URL 和联合结论。

### 数据统计强制约束

本节只适用于 `log_diagnosis` 和 `combined`，规则优先级高于这两种模式的其他日志规则。违反本节规则等同于输出错误结论。

**触发条件**：用户意图含 `统计`、`汇总`、`占比`、`成功率`、`总数`、`计数`、`分布`、`趋势`、`健康检查`、`有多少`、`多少笔`、`有几条`、`总共`、`一共`、`百分比`、`比例`、`平均`、`最多`、`最少` 任一关键词时，自动进入**统计模式**。健康检查（业务模块 reference 的 Step 0-4）**始终**属于统计模式。

**先探测**：统计模式先执行 `cls_query.py --method auto --api-limit 500`，读取 `log_count/loaded_count/is_complete/has_more/fallback_method`。禁止在未说明完整性状态时输出统计结论。

**按规模分档**：

| 探测结果 | 默认口径 | 精确补齐方式 |
|----------|----------|--------------|
| `is_complete=true` 或 `log_count<=500` | 精确统计 | API 未完整但 `<=500` 时，WorkBuddy 完整加载或拆分查询补齐 |
| `500 < log_count <= 1000` | 按意图：精确口径（总数/成功率/占比/准确数量）走完整加载；趋势/分布/整体异常可采样 | `--require-complete` 或拆分查询 |
| `log_count>1000`、`has_more=true` 无法低成本补齐、或完整性未知 | 采样统计 | 用户要精确时拆分时间/服务/level，或请用户缩小范围 |

**采样输出契约**：采样必须在结论或风险提示写"采样统计，非精确统计"，数字只能以"样本 N 条中…"表述。禁止输出未限定样本口径的全量总数/占比/成功率/平均值。

**精确失败处理**：精确路径返回 `error=INCOMPLETE_DATA` 时按 `suggested_actions` 拆分重试；仍不完整则不输出精确数值，只说明阻塞原因、已加载样本范围和下一步建议。

**多类别 OR 拆分**：查询含多个互斥类别（多 `level`、多 `serviceName`、多业务锚点）且 `has_more=true`/`is_complete=false`/`loaded_count>=api-limit`/完整性未知时，禁止基于合并样本输出分类结论。拆分顺序固定：先按 `level`（`ERROR`/`WARN` 必须分开查），再按 `serviceName`，最后按业务锚点/时间窗口。异常/健康检查场景默认先单查 `level:"ERROR"` 再单查 `level:"WARN"`，禁止把合并 OR 查询的 500 条样本当作 `ERROR`/`WARN` 全量分布。

**非统计模式**：流程追踪（根因分析、单笔排查）不要求 `--require-complete`，部分数据足以定位根因时可正常分析。

### 查询方法
- **查询前置条件（强制）**：
  - **用户提供了 traceId**：可以直接到日志平台用 `traceId:"{value}"` 查询
  - **用户未提供 traceId**：单笔根因分析、业务入口不明确、推荐锚点不可用时，必须先分析本地业务代码，理解业务流程和日志打印逻辑后再构造查询。统计/健康检查可先按模块 reference 和服务范围查询，再按需要做锚点校验
- **环境默认规则**：用户未指定环境时，**必须查生产环境（prod）**。只有用户明确说"查测试环境"时才使用测试 topic。禁止自行假设或优先查测试环境。
- **traceId 查询与提取**：
  - **用户提供 traceId**：直接执行 `traceId:"{value}"`（不加 `serviceName`）；查不到时扩大时间：`now-1d,now` → `now-7d,now` → `now-30d,now`
  - **用户未提供 traceId**：按后续步骤用业务标识符定位日志后，从提取的 innerText 中识别 `traceid` 列值（通常为 16 位或 32 位 hex，如 `110e6550d81fb1bc`、`b4d5cc63c42611adb4d5cc63c42611ad`），再执行 `traceId:"{提取值}"` 做全链路分析；不要自行截断成前 16 位
  - **traceId ≠ TID**：两者是不同的索引字段，不要混淆。以 `traceid` 列为准
- 日志无法获取明确结果时可结合项目代码
- 每次会话首次执行**代码锚点**校验前，只复用 `references/common/update-target-branch.md` 的目标分支选择与结论标注规则，不执行其中的仓库更新步骤。生产目标分支为 `master`；测试环境读代码前分支**必须已确认**（用户已给出则直接用，否则先问；禁止默认 `master`）。用 `source_inspect.py --status` 只读核对；当前分支不匹配时标记源码验证阻塞，不 fetch、不 stash、不 checkout、不 pull。
- 本组范围查询时，服务范围以"日志服务名和项目名映射关系表"的 `serviceName` 列为准；需要看代码时，再用同一行的`项目名`和`仓库路径`定位源码。
- 分析要查的数据是否在子模块的流程追踪入口，是的话可以通过日志锚点查询，不是的话分析本地项目路径，确认查询`sql`,服务名参考上面`日志服务名和项目名映射关系表`；子模块入口表格里的推荐查询只是通过代码锚点校验后的首查模板，不是唯一真相。
- 执行入口表格推荐查询前，先校验 `方法入口`、`serviceName` 和固定 `message` 片段是否仍能和当前代码匹配；可用 `scripts/validate_query_anchors.py` 辅助检查。
- 标识符值优先直接放入 `message:\"{value}\"`，禁止加 `cid:`、`orderId:`、`contractNo:`
- 日志查询 SQL 中如果包含中文，优先走 `scripts/cls_query.py --method api/auto`，API 路径直接传原始查询语句，不受 `queryBase64` 限制。只有浏览器 fallback URL 需要 ASCII `url_query`；必要时再读取 `references/common/cls-react-contenteditable-injection.md` 做页面注入。
- **分页未加载完** — CLS 每页只显示 20 条，`load_more_clicks` 是否足够？检查 `log_count` 字段
- 日志平台查询常用 key 见下文"查询语法与字段"段。

### SQL 条件下沉强制约束

执行 CLS 查询前，必须先把可确定条件拼进查询 SQL，再执行查询、加载和分析。除非用户明确要求"原始日志"、"全部日志"或"随机采样"，禁止先查裸服务范围（如 `serviceName:"order"`）再从返回样本中筛 `ERROR`、`WARN`、成功、失败或业务异常。

SQL 构造顺序：
1. 解析环境、时间范围、标识符、业务意图、日志级别和服务范围；业务意图必须先于服务别名扩范围确认。
2. 用户提供 `traceId` 时，直接执行 `traceId:"{value}"`，不额外拼 `serviceName`。
3. 用户明确日志级别或异常意图时，必须拼入 `level:"ERROR"`、`level:"WARN"` 等条件；例如"订单服务近半小时 ERROR"应查询 `serviceName:"order" AND level:"ERROR"`，"下单近半小时 ERROR"仍必须同时拼入下单业务锚点。
4. 用户描述业务链路场景时，必须先拼入该业务模块的稳定日志锚点；例如"查下单异常"应优先查询下单异常锚点，不能只查 `serviceName:"order" AND level:"ERROR"` 后把通用订单服务错误当作下单异常。
5. 用户描述业务场景但 SQL 条件不明确时，先按业务路由只读取对应模块 reference 的推荐查询和日志锚点；不要无差别扫描所有模块。
6. reference 中存在推荐锚点时，先校验 `方法入口`、`serviceName` 和固定 `message:"..."` 片段；校验通过后把稳定日志前缀拼入 SQL。
7. reference 锚点缺失、过期或不匹配时，再按服务映射表定位本地仓库，搜索业务代码中的日志打印语句，优先提取稳定日志前缀拼成 `message:"固定日志前缀"`。
8. 仍找不到稳定锚点时，才允许使用较宽 SQL 兜底；结论中必须写明"未找到稳定日志锚点，使用保守查询"，并标注完整性和采样风险。

可在日志返回后做内存解析的范围仅限：
- 解析已由 SQL 缩小后的返回对象字段，例如下单结果里的 `success=true`。
- 处理 CLS 难以可靠表达的中文、JSON 内部字段或复杂结构字段。
- 对已命中的日志做验证、归类和证据提取。

### 推荐查询锚点校验

各业务模块 reference 的`流程追踪入口`：`场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明`。

- `方法入口` 存在且 `serviceName` 与源码项目匹配、固定 `message:\"...\"` 片段仍在该入口类/方法附近命中时，才把推荐查询作为 Phase A 主查询。
- 方法存在但固定 message 不匹配时，不要把旧模板当主路径；改用 `serviceName:\"{服务}\" AND message:\"{标识符}\"`，并 grep 当前代码找新日志前缀。
- 方法不存在、源码缺失或服务不匹配时，标记模板疑似过期；先按 traceId/标识符值搜，再回代码确认入口。
- 推荐查询 0 命中时，继续扩大时间做值搜；如果能搜到日志，说明查询语法可用但目标时间段无命中；扩大到当前时间前一个月仍无日志时，停止扩大时间，回本地项目确认日志是否已下线、模板是否过期或入口是否变更。
- 无可用源码根目录时，`validate_query_anchors.py` 将该行标为 `verification_status=unverified`，不得计入有效或无效；默认校验为 advisory，只有显式 `--strict` 才因 unverified 或告警返回非零。
 
### 日志查询无结果排查清单

查询返回 0 条时，**不要立即归因于查询语法**。按顺序排查：

1. **时间窗口** — `now-1d,now` 是否真的覆盖了日志产生时间？扩大至 `now-7d,now` 或 `now-30d,now` 验证，能查到日志，说明`sql`语法没问题；扩大到`now-30d,now`仍然查不到时，进行第2步校验
2. **topic 是否正确** — CLS hide* params 可能导致 topic 随机丢失，确认 topic_id 无误
3. **`=` 等号查询退化** — 如果查询含 `message:\"字段=值\"` 且 `log_count` 显示为 topic 总量（数百万级），说明 CLS 退化为全量返回。加 `AND level:\"WARN\"/\"INFO\"` 等额外约束可恢复精确过滤。此时应以实际加载出的日志内容为准
4. **最后才怀疑语法** — 大部分**语法问题**是时间窗口或分页导致的，此时需要将查询`sql`本地项目做关联，确认日志是否过期，若日志过期提醒用户更新

### API、内置浏览器和本地浏览器优先级

- 优先用 `scripts/cls_query.py --method auto`。默认先请求 CLS 内部 HTTP API，不需要浏览器、不需要 `secret_id/secret_key`，查询中可直接包含中文。
- API 返回 `source=api_failed` 或 `is_complete=false` 时，按统计分档规则或非统计完整性风险决定下一步；需要页面 fallback 时，使用输出中的 `cls_url` 交给 WorkBuddy 内置浏览器打开。URL 必须包含 `topic_id`、`time`、`queryBase64`，避免依赖页面默认状态。
- 本地 Chrome + AppleScript 是最后备用路径：当 WorkBuddy 登录态不可用、页面操作失败、需要脚本自动加载更多或批量全文提取时，显式使用 `scripts/cls_query.py --method local-chrome --use-local-chrome`。
- 使用本地 Chrome 备用路径时，禁止默认操作 `active tab of front window`。首次查询创建新的 Chrome window，后续查询复用该窗口，通过 window id 定向操作；调查结束后调用 `scripts/cls_query.py --close` 关闭窗口。
- 不要用 `document.body.innerText.substring(0,N)` 判断结果；CLS 日志数据在页面文本后部。
- `traceId` 查询也可能超过 20 条；必须加载全部数据进行解析
- **分析前必须校验完整性**：统计模式下见上方"⛔ 数据统计强制约束"。非统计模式下：对比 `log_count` 与 `loaded_count`，若 `is_complete` 为 false 或 `loaded_count` 远小于 `log_count`，在"风险提示:"字段标注"基于 N/M 条采样分析，结论可能不完整"。

### 结论输出规则

> 卡片必须先调发送脚本、退出码语义、来源反查均见下方「来源识别与飞书卡片发送」。本段只约束卡片内容契约和纯文本 fallback 格式。

- 飞书卡片格式：可用 native table、lark_md、代码块、链接、按钮；群聊卡片正文 @ 提问者，私聊不需要。
- 内容模式：
  - `log`：日志结论；CLS 链接含 `topic_id`/`time`/`queryBase64`，结果集中在单线程时只带 `traceId` 即可。
  - `business-logic`：纯源码结论；不得伪造 CLS 查询、日志条数或“无匹配日志”文案。
  - `combined`：源码与日志联合结论；必须区分“源码预期逻辑”和“日志实际证据”。
- `send_feishu_card.py --data` schema 强制契约（违反则脚本以 `invalid_data_schema` 拒收）：
  - 顶层**只允许** `summary_fields`、`call_chain`、`log_count`、`table_data`、`analysis`；禁止 `summary`、`time_range`、`total_logs`、`error_breakdown`、`root_cause` 等自由字段。
  - 类型：`summary_fields`=`[{label,value}]`；`call_chain`=非空日志对象列表；`log_count`=`>=0` 整数；`table_data`=`[{headers:list, rows:list[list]}]`；`analysis`=字符串。
  - `call_chain` 内部字段自适应渲染（推荐 `level/time/service/content`，CLS 原生 `timestamp/serviceName/message/traceId` 也可，未识别字段追加成 `key=value`）。
  - `log_count > 0` 时至少提供 `summary_fields`/`call_chain`/`table_data`/`analysis` 之一；只有 `log_count==0` 且无内容才渲染"无匹配日志"。
  - 这是通用渲染契约：日志用 `call_chain` 表实际链路；源码分析用 `table_data` 表调用步骤和条件分支；`analysis` 表结论；`summary_fields` 放标识符或源码上下文。
- 纯文本 fallback 格式契约：
  - 允许：普通文本、换行、分段、短横线列表、数字编号、粗体标签、`[文本](URL)` 链接、@。
  - 禁止：Markdown/HTML 表格、表格分隔线、代码块、复杂嵌套列表、卡片语法。
  - 自检：出现 `|---|`、任意以 `|` 分隔多列的行 → 改写成逐行列表；出现 fenced code block → 改写成普通文本。
- `log` 卡片或纯文本必须包含：日志前缀、CLS 查询语句/topic/时间范围、命中摘要与未命中证据、完整性状态（`loaded_count` vs `log_count`）、关键节点时间、CLS URL、卡片发送状态。
- `business-logic` 卡片或纯文本必须包含：业务模块、仓库、分支、Commit、工作区状态、分析范围、源码文件与行号、核心调用链、条件分支、外部依赖、未确认项、卡片发送状态；不要求任何 CLS 字段。
- `combined` 必须同时满足上述源码证据与日志证据要求，并明确哪些结论来自源码、哪些由日志验证。

### 来源识别与飞书卡片发送

> **本节优先级最高，违反等同于交付失败。** 飞书卡片是本技能**唯一**允许的结论交付方式；当前会话的纯文本**不是可选项**，只能是 `send_feishu_card.py` 已被调用且返回非 0/失败后的降级产物。
>
> **目标状态**：本轮结束时，要么终端已有一次 `send_feishu_card.py` 调用且退出码为 0（`--quiet-success` 下成功时 stdout 为空属正常；`status:"sent"`+`message_id` 写在审计 JSON 里），要么有该脚本失败的明确证据（退出码非 0 / stderr error JSON）+ 纯文本降级。两者皆无 = 违规。
>
> **反例（禁止）**：结论分析完成后，认为"问题简单/已查清/直接答复更快"，**不调脚本就把诊断文本发给用户**——即使内容正确，也按交付失败处理。"是否发卡"不由结论复杂度决定，只由本流程决定。

**发送通道（2026-08-05 起双通道）**：`send_feishu_card.py` 的卡片发送、用户 ID 转换和消息详情读取优先使用 `lark_oapi` bot SDK；进程环境中的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 优先，缺失时读取 `~/.hermes/.env`。SDK、凭据或请求不可用时自动降级到现有 lark-cli，`--resolve-chat` 使用的 `messages-search` 仍只走 lark-cli。SDK、凭据和 lark-cli 都只在实际传输需要时惰性解析；模块导入和 `--help` 不查找 CLI、不重启解释器。OAPI 发送成功会在普通 stdout 和路由审计中记录 `"transport":"lark_oapi"`；`--quiet-success` 继续抑制成功 stdout，不改变退出码语义。

技能被触发后，在输出最终结论前执行以下流程：

1. **必须先调用发送脚本**：最终结论生成后，先执行 `send_feishu_card.py --quiet-success`。不要先输出普通文本结论；只有发送脚本返回非 0 或明确失败状态时，才输出纯文本 fallback。
2. **来源优先级**：Hermes 直传（`resolve_hermes_session.py` → `--user-id`/`--chat-id`）> `--chat`（人工显式指定）> `--resolve-chat --source-query "{用户原始问题}"` 反查选定的 `chat_id` > `FEISHU_CURRENT_CHAT_ID` / `AGENT_CURRENT_CHAT_ID`（host 若注入的当前会话）> 纯文本 fallback。反查成功时环境变量不能覆盖或短路结果。`WORKBUDDY_HOME_CHANNEL_CHAT_ID` **不再自动兜底**——他人私聊反查不到时若堆到这里会全部误发运维者 DM，仅在显式传 `--allow-home-channel-fallback`（供无来源上下文的批量/定时调用）时才用。WorkBuddy 正常路径必须用 `--resolve-chat`。
3. **`--source-query` 取值约束**：必须是触发技能的原始用户消息原文；禁止传分析摘要、关键切片、卡片标题或改写后的问题。
4. **来源安全**：群聊只能选 @Tom 的消息作为发送目标；未 @Tom 的同文本群消息只能作为噪声过滤。退化搜索（`@Tom` 候选池 + 相似度选择）仍必须通过群聊 @Tom 校验，不能绕过该规则。

发送命令按运行环境二选一；均保留 `--debug-log-dir`、`--quiet-success`，并按模式选择 `--content-mode`。

**Hermes 环境**：先执行 helper 并读取 JSON；退出码 2、私聊 `open_id` 为空或输出无法解析时，改走下方反查模板。

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/resolve_hermes_session.py --resolve-open-id
```

- `chat_type=dm`：把 `open_id` 传给 `--user-id`，并固定 `--chat-type p2p`，私聊不加 `--at-sender`。
- `chat_type=group`：把 `chat_id` 传给 `--chat-id`，并固定 `--chat-type group`。提问者 ID 优先使用 `ou_` 开头的 `sender_open_id_raw`；否则使用 `user_id` 并传 `--sender-id-type user_id`。转换失败时仅发群，不生成 @。

```bash
# 私聊直发
python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py \
  --user-id "ou_xxx" --chat-type p2p \
  --debug-log-dir "/private/tmp/xh-log-lookup-route" \
  --quiet-success --content-mode "{log|business-logic|combined}" \
  --title "..." --color "..." --data "..."

# 群聊直发并 @ 提问者
python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py \
  --chat-id "oc_xxx" --chat-type group \
  --sender-open-id "{ou_xxx|租户 user_id}" --sender-id-type user_id \
  --debug-log-dir "/private/tmp/xh-log-lookup-route" \
  --at-sender --quiet-success --content-mode "{log|business-logic|combined}" \
  --title "..." --color "..." --data "..."
```

**WorkBuddy、非 Hermes 或 Hermes helper 降级**：使用消息原文反查。

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/send_feishu_card.py \
  --resolve-chat --source-query "{用户原始问题}" \
  --resolve-window-minutes 15 \
  --debug-log-dir "/private/tmp/xh-log-lookup-route" \
  --at-sender --quiet-success \
  --content-mode "{log|business-logic|combined}" \
  --title "..." --color "..." --data "..."
```

退出码语义（行为护栏，不可违反）：

- 退出码 0 → 视为卡片已发送，当前会话**不得**再输出诊断结论、摘要、证据、CLS 链接或卡片内容；宿主强制要求非空回复时，只输出 `已发送飞书卡片。`。
- 退出码非 0 或 `status: "unresolved"` → 当前会话输出飞书兼容纯文本结论。`error=missing_private_target`（退出码 2）是**私聊来源无法反查时的正常降级**（`--as user` 搜不到他人 p2p），不是配置缺失：直接输出纯文本结论，由 WorkBuddy 回复通道送达发起人，无需提示配置 `WORKBUDDY_HOME_CHANNEL_CHAT_ID`。其余退出码非 0 情形按失败降级并说明原因。
- 最终结论已用普通文本输出但本轮无 `send_feishu_card.py` 调用记录 → 视为违反输出规则。

**发送前自检（每轮必须逐条确认，缺一即停下补做，不得跳过）**：
1. 本轮是否已实际执行 `send_feishu_card.py`？未执行则现在执行，不允许"口头认为已发"。
2. 若打算在会话里输出任何诊断文本（含 CLS 链接、证据、调用链、根因），脚本是否已返回非 0 或失败状态作为依据？没有该依据就不许输出文本，回到第 1 步。
3. 判定"已成功发卡"的唯一信号是**脚本退出码 0**（`--quiet-success` 模式下成功时 stdout 为空、不打印任何内容，这是正常的，不要因为"没看到输出"就误判失败或重发）。退出码非 0 或 stderr 出现 error JSON 才算失败，按失败降级。`status:"sent"`+`message_id` 会写进 `--debug-log-dir` 的审计 JSON，仅供事后核查，不会出现在 stdout。

> 脚本反查行为（实现细节，模型无需逐条记忆）：完整原始问题先做混合搜索并按 `chat_type` 路由，0 命中时按脚本内置节奏等待索引就绪，仍 0 命中再用 `@Tom` 候选池 + 相似度退化搜索；多命中按最新有效消息选择；`--debug-log-dir` 写出 `fallback`/`searches`/`mget`/`selection` 审计 JSON；环境变量与反查冲突时以反查结果为准并记录 `env_chat_conflict`。具体重试/等待节奏以 `scripts/send_feishu_card.py` 的 `SEARCH_RETRY_DELAYS` / `ZERO_RESULT_RETRY_DELAYS` 为准。

## 意图分类

| 意图 | 识别特征 | 查询策略 |
|------|---------|---------|
| 本地业务逻辑 | 不查日志、只看代码、本地源码、业务流程、调用链、条件分支、字段语义、类/方法职责 | `local_logic`：reference 导航 + `source_inspect.py` 验证，禁止 CLS |
| 数据统计 | 统计、汇总、占比、成功率、总数、计数、健康检查、有多少、多少笔 | 先用 API 探测；<=500 精确，500-1000 按意图选择，>1000 默认采样 |
| 流程追踪 | 借款、下单、Hold单、HOLD_ON、进H、解H、放款、还款、债转、权益、签约、绑卡、指定 `traceId`/`orderId`/`contractNo` | 路由到业务模块 reference，按模块首查主键和入口日志追踪全链路 |
| 联合分析 | 同时要求梳理逻辑与验证线上/测试实际路径，或日志证据不足自动升级 | `combined`：先源码、后日志，合并证据发卡 |
| 健康检查 | 最近有没有异常、无具体标识符 | 使用业务模块 reference 的总览式查询步骤 |
| SSO/登录 | 浏览器 fallback 跳转 Argus/JANUS/PMP 登录 | 使用 `xh-sso-access` |

## 业务路由

用户问"我们组"、"客户订单组"、"这批服务"的整体日志、异常、健康情况时，不需要再追问服务范围；按上方映射表 `serviceName` 列覆盖全部客户订单组服务。若用户同时给出具体业务关键词，再按下表选择业务模块并在该模块内覆盖相关服务。

用户问表中`别名`对应的整体日志、异常、健康情况时，不需要追问具体 `serviceName`；按同别名的全部 `serviceName` 查询。用户明确写出具体 `serviceName` 时，才只查该单个服务。

业务意图优先级固定为：标识符查询 → 业务链路查询 → 服务健康查询 → 服务别名范围查询。用户提供 `traceId/orderId/cid/contractNo` 等标识符时优先按标识符查；用户描述"借款首页、借款内容、借款试算、预检、借款能力校验、首页不展示借款额度、客户申请借款、申请前轨迹"时，按申请前链路查询处理；用户只说"借款失败"且未明确订单、下单或反欺诈时，也默认按申请前链路查询处理；用户描述"Hold单、H单、HOLD_ON、进入 H 单、进H、解H、继续hold、解H推送、取消Hold、Hold超时、超时转单、CRM催促解H"时，按 Hold 生命周期处理，**Hold 明确优先于通用订单、放款**；例如"拒就赔解H"走 Hold 模块，单独的"拒就赔"走权益模块。用户描述"债转、债权转让、合同债转、期供代偿、债转回购"时，按账务债转成功通知后的 `order-batch → order` 链路处理，优先级高于通用还款、扣款关键词。用户描述"下单、借款下单、下单成功、下单失败、订单失败、下单异常、下单链路异常、拦截"时，按正式下单链路查询处理并优先使用模块锚点。只有用户明确说"订单服务异常"、"订单组异常"、"客户订单组健康检查"、"`order-batch`"、"`order-batch-timing`"、"`mqResendJob`"、"服务健康"等服务侧语义时，才按服务健康或服务组范围处理。

业务链路查询的结论必须围绕用户目标输出。通用服务 ERROR/WARN 可以作为背景风险提示，但必须单独标注为"服务背景异常"或"订单组服务异常"，不得汇总成业务链路异常。

| 关键词 | 业务模块 reference | 业务模块 |
|--------|---------|--------|
| 签约、重签、重新签约、RESIGN、SIGNING_ISSUE、签约协议、支付协议、代扣协议、协议共享、协议号同步、绑卡、银行卡签约 | `references/modules/sign.md` | 签约模块 |
| 登录后借款、借款首页、借款入口、借款内容、借款内容页、借款申请前、客户借款申请、借款能力预检、借款能力校验、预检、借款试算、试算、首页不展示借款额度、借款失败、行为轨迹、客户轨迹、贷前链路 | `references/modules/apply.md` | 借款申请模块 |
| Hold单、H单、HOLD_ON、进入 H 单、进H、解H、继续hold、解H推送、取消Hold、Hold超时、超时转单、CRM催促解H、拒就赔解H | `references/modules/hold.md` | Hold 单模块 |
| 下单、端内（自营）下单、api下单、订单、拦截、反欺诈 | `references/modules/order.md` | 下单模块 |
| 权益、会员、VIP、优惠券、乐活卡、coupon、尊享卡、拒就赔、加速卡、获额卡、返现券 | `references/modules/benefit.md` | 权益模块 |
| 放款、放款日志、放款失败、资金路由、route、loki放款、换资方、缓冲池、再分发、缓冲池出池、特项额度 | `references/modules/loan.md` | 放款模块 |
| 债转、债权转让、合同债转、债转成功通知、期供代偿、债转回购 | `references/modules/debt.md` | 债转模块 |
| 还款、扣款、逾期、代扣、结清、提前结清、repay、好友代付、聚合支付 | `references/modules/repay.md` | 还款模块 |

匹配不到业务模块时，先问用户确认。

## 工作流索引

强制步骤只在上文维护，避免模式说明与执行流程漂移：

| 模式 | 执行入口 | 交付模式 |
|------|----------|----------|
| `local_logic` | 「分析模式选择」→「local_logic」→「本地源码工具」 | `business-logic`；禁止 CLS |
| `log_diagnosis` | 「log_diagnosis」→「数据统计/SQL/锚点/无结果/API 优先级」 | `log`；证据不足自动升级 |
| `combined` | 「combined」同时应用源码与全部日志强制规则 | `combined`；区分源码预期与日志证据 |

所有模式统一执行「来源识别与飞书卡片发送」；发送失败后才允许使用纯文本 fallback。业务细节和查询锚点只从对应 module reference 读取，CLS、源码和卡片实现细节按 `references/common/` 的索引按需读取。

## 本地源码工具

`source_inspect.py` 只允许读取映射表中的仓库，不执行 fetch、pull、checkout、stash 或文件写入。完整参数以 `--help` 为准。

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/source_inspect.py --project order --status
python3 ${WORKBUDDY_SKILL_DIR}/scripts/source_inspect.py --project order --search "LoanServiceImpl" --context 3 --max-results 50
python3 ${WORKBUDDY_SKILL_DIR}/scripts/source_inspect.py --project order --file "path/to/File.java" --start-line 120 --end-line 260
```

- `--status`：返回仓库路径、当前分支、HEAD commit、dirty 状态和变更文件。
- `--search`：按字面量搜索源码/配置文件，默认 50 条，最多 200 条；使用上下文继续判断目标文件。
- `--file`：只读取仓库内源码/配置白名单文件的指定行，单次最多 400 行；拒绝绝对路径、`../` 越界、隐藏/构建目录和仓库外符号链接。

## CLS 工具

### 默认：API 优先查询

`cls_query.py` 默认 `--method auto`：先走 CLS HTTP API（无需浏览器/`secret_id`，查询可含中文，默认最多拉 500 条用于探测和小数据精确统计），API 失败或无法确认完整时返回 `fallback_method: "workbuddy"` 和完整 `cls_url`。只有显式 `--method local-chrome` 或 `--use-local-chrome` 才打开本地 Chrome。

```bash
python3 ${WORKBUDDY_SKILL_DIR}/scripts/cls_query.py \
  --env prod \
  --query 'serviceName:"order" AND message:"20161002000002677537"'
```

API 成功输出 JSON 关键字段：`source`、`logs`（结构化日志数组）、`output_path`（同步文本文件）、`loaded_count/log_count/is_complete`（完整性）、`fallback_method`。payload、返回结构和 fallback 规则详见 `references/common/cls-api-query.md`。

### 备用路径与参数

API 不可用或需要页面操作时按下表切换；完整参数见 `cls_query.py --help`。

| 场景 | 关键参数 | 说明 |
|------|----------|------|
| URL fallback 不开浏览器 | `--method workbuddy`（`--no-browser` 兼容转入） | 仅构造 `cls_url`/`expanded_url` 交 WorkBuddy 内置浏览器 |
| 本地 Chrome 提取全文 | `--method local-chrome --use-local-chrome --output /tmp/cls_output.txt` | WorkBuddy 不可用、需脚本自动加载更多或批量提取时;输出含 `cls_url`/`expanded_url`/`output_path`/`completeness_ratio`/`services`/`contracts` |
| 本地 Chrome 精确统计 | 上一行再加 `--require-complete` | 强制完整数据，自动加载最多 200 次;仍不完整返回 `error: INCOMPLETE_DATA` 和拆分建议，此时禁止输出精确统计 |
| 关闭备用窗口 | `--close` | 仅用本地 Chrome 备用路径时，调查结束后关窗口 |
| 校验入口表锚点 | `validate_query_anchors.py --all --summary` | 自动发现 `references/modules/*.md`;校验不通过时推荐查询只能作历史线索 |

- 含 `=` 的查询可能退化为全量返回，`log_count` 不可靠，以实际加载内容为准。
- 本地 Chrome 路径禁止操作 `active tab of front window`：首查创建新 window，后续按 window id 复用。
- 不要用 `document.body.innerText.substring(0,N)` 判断结果；CLS 日志数据在页面文本后部。`traceId` 查询也可能超 20 条，必须加载全部再解析。
- 中文查询：API 路径直接支持；浏览器 URL fallback 受 `queryBase64` 限制，工具自动生成 ASCII-safe `url_query`，必要时按 `references/common/cls-react-contenteditable-injection.md` 注入。

## CLS 环境与查询语法

| 环境 | topic_id | 默认时间 |
|------|----------|----------|
| 生产 | `f6748b3a-8ab8-4191-b848-cb90b1598901` | `now-7d,now` |
| 测试 | `1f92a7ca-cf46-4f4f-92dd-72c5df5910dc` | `now-1d,now` |

URL: `https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search?region=ap-beijing&topic_id={topic_id}&time={start},{end}&queryBase64={base64_query}`

语法：`field:"value"` + `AND` / `OR`，所有字段值统一加引号。

- 索引字段（精确匹配）：`serviceName`、`level`（`INFO/ERROR/WARN/DEBUG`）、`traceId`（按 traceId 查时一般不拼其它条件）、`requestId`。
- 全文字段：`message`——`orderId`、`cid`、`contractNo` 等非索引值通过 `message` 搜索。
- `env` 非索引，默认 `prod`；测试环境未指定具体 test 编号时不加此条件。

> topic 字段全表、误点 NGINX topic（`fg-prod`/`fg-test` 不含 `serviceName`）的判定和回退见 `references/common/cls-topic-field-reference.md`。

## 纯文本 fallback 推荐结构

仅当卡片发送失败、来源缺失或候选详情获取失败时使用（格式约束见「结论输出规则」的纯文本 fallback 契约）：

结论: 一句话说明结果、根因或当前健康状态。
查询范围: 环境、时间范围、topic、CLS 查询语句。
命中摘要: 命中数量、关键 traceId/orderId/contractNo/cid、完整性状态。
关键证据: 按时间顺序列出关键日志节点，保留原始时间戳；多条证据用换行和短横线分隔，不得使用表格。
- 15:30:50.784 thor-app-gateway: 发起还款试算，orderId=...
- 15:30:50.813 order: ERROR NullPointerException ...
风险提示: 数据不完整、采样分析、查询失败或无结果时必须说明；无风险时写"暂无"。
链接: 附 `cls_url` 和必要时的 `expanded_url`。

## References

- 借款申请前/首页/预检/试算/客户轨迹问题：读 `references/modules/apply.md`
- 订单/正式下单/下单拦截/反欺诈问题：读 `references/modules/order.md`
- Hold单/H单/HOLD_ON/进入 H 单/解H/继续Hold/取消/超时/重路由问题：读 `references/modules/hold.md`
- 签约/重签/协议/绑卡问题：读 `references/modules/sign.md`
- 权益/VIP/优惠券/乐活卡问题：读 `references/modules/benefit.md`
- 放款/资金路由/loki/缓冲池再分发问题：读 `references/modules/loan.md`
- 债转/债权转让/合同债转/期供代偿/债转回购问题：读 `references/modules/debt.md`
- 还款/扣款/结清/提前结清/逾期问题：读 `references/modules/repay.md`
- `references/common/update-target-branch.md`：只复用生产/测试目标分支选择和结论标注；本技能不执行其中的仓库更新步骤
- `references/common/cls-local-chrome-access.md`：备用：本地 Chrome 专用窗口访问 CLS
- `references/common/cls-dom-extraction.md`：全文提取、加载更多、CK/CS 合同号解析
- `references/common/cls-query-pitfalls.md`：CLS 高频坑和恢复方式
- `references/common/cls-api-query.md`：CLS HTTP API 直查 payload、返回结构和 fallback 规则
- `references/common/feishu-card-template.md`：飞书卡片内容组织、标题/颜色分级、native table 渲染和历史 Markdown 降级模板
- `references/common/chinese-queryBase64-experiments.md`：中文 queryBase64 限制
- `references/common/cls-react-contenteditable-injection.md`：React contenteditable 中文注入方案（String.fromCharCode + execCommand）
- `references/common/trace-dubbo-profile-filter.md`：Dubbo 全链路追踪（ProfileFilter CS/CR/SS/SR 标记解读 + 溯源方法论）
- `references/common/cls-topic-field-reference.md`：CLS Topic 字段对照表（生产/测试环境 topic 属性与索引字段）
- `references/common/efficient-query-pattern-20260517.md`：高效查询工作流（查询耗时优化、CLS 页面异常处理）
