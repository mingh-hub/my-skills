# 订单域详细排障归档

## 何时读取

这是 `xh-log-lookup-order/SKILL.md` 重构前的完整内容归档。当轻量子 Skill 的入口表和失败模式不足以诊断复杂订单问题时读取。

## 目录

- 查询意图分类
- 借款能力预检
- 反欺诈
- 生命周期序列
- 健康检查
- 存量状态查询

# 订单日志查询 — 业务规则

## 查询意图分类（必须先做）

> ⚠️ **进入本技能后的第一步**：判断用户的查询意图，不同意图使用不同查询策略。

| ***意图*** | ***识别特征*** | ***查询策略*** | ***禁止操作*** |
|------|---------|---------|---------|
| **流程追踪** | "下单失败"、"为什么被拒"、特定 traceId/orderId | 使用下方入口覆盖表的日志前缀查询 | — |
| **存量状态查询** | "有多少笔未结清"、"名下合同"、"当前状态" | 直接搜 cid 值 + grep 状态字段（见"存量查询"章节） | **禁止搜** `[借款下单]下单请求为` 等新增入口日志 |
| **健康检查** | "今天下单情况"、"最近有没有异常" | 使用总览式 Step A→B→C→D | — |

## 涉及项目

- order (主)
- loki-webapp
- h5-loan

## 入口覆盖表 + 查询模板（仅用于"流程追踪"意图）

> 每次查日志前必须确认覆盖了所有相关入口。
> Phase A 查询统一前缀: `serviceName:"order" AND ...`

| 场景 | 类 | 日志前缀/关键词 | Phase A 查询模板 |
|------|-----|---------|-----------------|
| **借款能力预检** | OrderServiceImpl:2174 | queryOverdueMark → UserOverDueHisHandler → queryTxInfo | 见下方案析指引 |
| 自营下单 | LoanServiceImpl:287 | [借款下单]下单请求为 | serviceName:"order" AND message:"[借款下单]下单请求为" AND message:"{值}" |
| 下单拦截 | LoanTemplate:260 | [借款下单]下单拦截请求 | serviceName:"order" AND message:"[借款下单]下单拦截请求" AND message:"{值}" |
| 下单结果 | LoanServiceImpl:291 | [借款下单]下单请求结果为 | serviceName:"order" AND message:"[借款下单]下单请求结果为" AND message:"{值}" |
| 业务异常 | LoanServiceImpl:300 | [借款下单]请求出现业务异常 | serviceName:"order" AND message:"[借款下单]请求出现业务异常" AND message:"{值}" |
| 系统错误 | LoanServiceImpl:311 | [借款下单]出现系统错误 | serviceName:"order" AND message:"[借款下单]出现系统错误" |
| 反欺诈 | CreditService:131 | 借款下单反欺诈请求 | serviceName:"order" AND message:"借款下单反欺诈" AND message:"{值}" |
| 资金路由 | LoanOrderServiceImpl | [资金路由] | serviceName:"order" AND message:"[资金路由]" AND message:"{值}" |
| 自动路由 | LoanOrderServiceImpl | [资金自动路由] | serviceName:"order" AND message:"[资金自动路由]" AND message:"{值}" |
| API借款试算 | ApiRepaymentTrialImpl:57 | [借款试算]api借款还款计划试算请求为 | serviceName:"order" AND message:"[借款试算]" AND message:"{值}" |
| 解H | ReleaseHoldOrderServiceImpl | [新解H] | serviceName:"order" AND message:"[新解H]" AND message:"{值}" |

### 借款能力预检查询指引

**触发场景**：用户说"借款返回XX提示"（如下单页就被拦住、还没走到下单流程）、"您存在不良借款记录"、"当前最高可借金额"、"您有借款已逾期"等。

**和[借款下单]的区别**：借款能力预检走的是 **`/h5-loan/loan/loanAbility`** → **`OrderService.queryOverdueMark`** → **`UserOverDueHisHandler.queryUserOverDueHis`**（T4提现门槛），这是一个不到达 `[借款下单]` 入口的前置拦截。如果日志中找不到 `[借款下单]` 相关记录，说明客户在下单页就被能力检查拦住了。

**查日志步骤**：

1. **查入口**：先搜 cid 值看来自 h5-loan 的调用
   ```
   serviceName:"order" AND message:"查询result:cannotLoan" AND message:"{cid值}"
   ```
   或直接搜 cid 值定位 traceId：
   ```
   serviceName:"order" AND message:"{cid值}"
   ```

2. **查 queryOverdueMark 链路**：提取 traceId 搜全链
   ```
   traceId:"{traceId}"
   ```
   在结果中找：
   - `queryOverdueMark` 请求（类 `OrderServiceImpl`）
   - `UserOverDueHisHandler` 日志 → 看 T4 规则命中详情
   - `未通过提现门槛` → 记录了驳回原因和聚合反欺诈数据

3. **查 guideCheckAbility 链路**：同 traceId 找：
   - `CustomerLoanAvailableService.guideCheckAbility` → 注意此接口与 queryOverdueMark **不同**，可能返回 success=true 而 queryOverdueMark 返回失败
   - 检查是否因 `BooleanUtils.isFalse()` 反转逻辑导致 guideCheck 通过但 queryOverdueMark 拦截

4. **h5-loan 响应映射**：在 h5-loan 的日志中找 `RespMappingAspect` 找到最终对外返回码（`FAILURE_RESPONSE`）和对应的 `innerRespCode`（如 `HLLA1163`）

**关键日志格式**：

```
cid:{cid},hisMaxOverdueDay:{N},aggrAntifraudAnlyzService queryTxInfo result is:{JSON}
  → 包含 mob_i, settle_flag_i, max_overdue_day_3year, his_max_overdue_days_i 等

cid:{cid},未通过提现门槛,历史最大逾期天数:{N},...
  → T4规则拦截

cid:{cid},贷中提现门槛查询结果，是否逾期:{true/false}
  → 最终判定

借款能力guideCheck查询result:{...}
  → guideCheck结果（可能为 success:true，不等于借款能通过）

RespMappingAspect track loan ability data, resultCode:{code}, resultMsg:{msg}
  → h5-loan对外响应映射结果
```

**完整链路的服务跳转**：
```
客户端(223.x.x.x) → h5-loan(loan/loanAbility)
  → order.queryOverdueMark → UserOverDueHisHandler → aggrAntifraudAnlyzService.queryTxInfo
  → order.guideCheckAbility → accountInfoService.queryByCid, etc.
```

### 签约/重新签约问题排查（"一直提示重新签约"场景）

**触发场景**：用户反馈手机号 APP 反复弹出"重新签约"页面，或提示"请至银行卡签约页面重新签约"。

**常见根因（按优先级排查）**：

1. **全渠道禁闭（最频繁）** — 所有资金方拒绝该客户借款。**注意：全渠道禁闭和重新签约是两套独立机制，APP 会同时并行触发两者检查**，而非禁闭导致了重新签约。客户看到「无法借款」和「请重新签约」两个提示，是因为 APP 的借款能力检查和签约检查同时返回了否定结果。此时重新签约无法解决禁闭问题，需等禁闭到期自动解除。详见 `references/re-sign-troubleshooting-20260519.md`。
2. **签约失效** — 支付协议（宝付/易宝等）已失效，`InvalidAgreementHandler` 发短信通知用户重新签约。需要排查还款失败历史（`OrderOthersServiceImpl.getRepayFailMessage`，SIGNING_ISSUE 场景）。
3. **扣款失败触发重签** — 还款代扣失败 → 系统缓存 needReSign 标记 → APP 持续提示重新签约。

**排查步骤**：

```text
Step 1: 确定 cid
   只给了手机号 → 搜 message:"{手机号}" 找到 cid
   日志中的 cid 通常出现在: "cid":"{value}" 或 "customerId":"{value}"

Step 2: 搜 cid 找到签约查询记录
   serviceName:"order" AND message:"{cid值}" AND message:"RESIGN"
   或直接搜: serviceName:"order" AND message:"{cid值}"
   找 SignService.query 调用, scene="RESIGN" 表示重新签约场景
   注意客户可能有多张银行卡，每张都会触发 RESIGN 查询

Step 3: 查资金路由禁闭状态
   在 cid 的全量日志中找 queryFrozenFundListByCid 的 SS 日志
   关键字段:
   - allRefuse: true → 全渠道禁闭
   - false → 未禁闭
   frozenFunds[].unfrozenDate → 解禁时间
   日志: "{cid}全渠道禁闭结果：1" → 禁闭中
         "{cid}全渠道禁闭" → 触发了禁闭检查

Step 4: 若不禁闭 → 查签约失效和还款失败
   搜 message:"{cid值}" AND message:"签约失效"/"InvalidAgreement"/"扣款失败"
   以及搜 message:"{cid值}" AND message:"还款失败"/"SIGNING_ISSUE"
   看 OrderOthersServiceImpl.getRepayFailMessage 中是否触发了 SIGNING_ISSUE 场景

Step 5: 查重新签约结果
   搜 traceId:"{RESIGN查询的traceId}" 看完整链路
   在 CR 响应中找需要签约的渠道列表和签约状态

**🔴 缓存陷阱**：ReSignChannel 使用 Redis 缓存签约渠道列表（RESIGN_CACHE_CHANNEL:{MD5(卡信息)}），TTL=10 分钟。签约成功后无任何代码清除该缓存，且缓存命中后的 ZTX 再查结果不回写缓存。因此客户签了部分渠道后，缓存仍保持旧列表，APP 在 10 分钟内继续提示重签。需要等缓存过期（或客户签完所有渠道）才能消除提示。详见 references/re-sign-troubleshooting-20260519.md。

关键日志格式:
   queryFrozenFundListByCid → SS → {"allRefuse":true,"frozenFunds":[{"fundSource":"WPXJ_RS","unfrozenDate":"..."}]}
   [签约查询]查询签约场景:RESIGN → 请求内容包含 cardNo, phone, scene
   全渠道禁闭结果：1 → 确认全渠道禁闭
```

## 用户输入 → 首次查询策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| orderId | serviceName:"order" AND message:"{value}" | 直接用值搜，不加 `orderId:` 前缀 |
| cid | serviceName:"order" AND message:"{value}" | 直接用值搜，不加 `cid:` 前缀 |
| contractNo | serviceName:"order" AND message:"{value}" | 直接用值搜，不加 `contractNo:` 前缀 |
| traceId/线程号 | traceId:"{value}" | 跳过 Phase A，直接全链路，**不加 serviceName** |

## 订单生命周期期望序列

### 完整生命周期节点（从预检到结清）

```
Step 0: 借款能力预检 (pre-loan ability check)
        ├── queryOverdueMark → T4提现门槛校验（OrderServiceImpl:2174）
        │   └── 拦截返回: CHECK_USER_OVERDUE_HIS / CHECK_USER_OVERDUE / ...
        └── guideCheckAbility → 额度/逾期/其他校验（CustomerLoanAvailableServiceImpl）
            └── 拦截返回: 不良借款记录 / 额度不足 / ...

Step 1: [借款下单]下单请求为 — 入口 (LoanServiceImpl:287)
Step 2: cid:xxx,开始处理借款下单 — 处理开始 (H5LoanService:317)，显示 orderExtendType
Step 3: [借款下单]下单拦截请求 — 拦截检查 (LoanTemplate:260)
Step 4: 借款下单反欺诈请求/结果 — 反欺诈 (CreditService:131/133)
Step 5: [借款下单]下单请求结果为 — 最终结果 (LoanServiceImpl:291)
Step 6: [通知合作方]下单成功 — 合作方通知
Step 7: 推送资方 / 放款相关日志 — 资金路由和放款
```

> **⚠️ 关键区别**：Step 0 由 h5-loan 的 `/h5-loan/loan/loanAbility` 接口触发，在用户看到下单页面之前执行。如果在 CLS 中找不到 `[借款下单]` 日志，说明客户在 Step 0 就被拦截了，应该查 `queryOverdueMark` 或 `guideCheckAbility` 的日志。

常见失败节点：
- 转账失败：放款转账被银行拒绝，statusDes="转账失败"
- 签约失败：用户未完成签约或签约校验不通过，orderStatus="SINGFAIL"
- 征信拒绝：风控规则拦截，orderStatus="REFUSE"
```

### 时间范围建议

| 场景 | 推荐时间窗口 | 说明 |
|------|------------|------|
| 当天创建的订单 | `申请日 00:00 ~ now` | 快速定位 |
| 前一天创建的订单 | `申请日 00:00 ~ 次日 23:59` | 涵盖当天全部流程 |
| 多天跨度的订单 | `创建日 ~ 当前日期` | 最多 7 天，避免超时 |

### 关键状态码字段

| 字段 | 含义 | 常见值 |
|------|------|--------|
| `orderStatus` | 订单状态码 | `SINGFAIL`（签约失败）、`REFUSE`（拒绝） |
| `statusDes` | 状态中文描述 | `转账失败`、`签约失败` |
| `contractNo` | 合同号 | null=未签约，有值=已签约放款 |
| `loanAmount` | 放款金额 | null=未放款 |
| `realAmount` | 合同金额 | 有值=合同已生成 |
| `loanDate` | 放款日期 | null/有值 |

> 完整订单状态定义（已结清/未结清/理赔/已退单）见 `references/order-status-glossary.md`

## 失败模式

| 现象 | 诊断 |
|------|------|
| 用户看到"您存在不良借款记录，无法借款。" | **T4提现门槛拦截**。查 `queryOverdueMark` → `UserOverDueHisHandler` 日志，看 `未通过提现门槛` 和 `isOverdue=true`。根因是用户的逾期历史记录超过 T4 规则的某个维度阈值（见 `references/t4-withdrawal-threshold.md`）。 |
| 用户看到"您有借款已逾期噢，请还款后再来借款~" | **当前逾期拦截**。`orderLocalService.getUserOverDueMark()` 返回 true，有在贷逾期订单且逾期天数 < 7。先去还款再借款。 |
| 客户一直提示"重新签约"（APP 反复弹出签约页面） | **全渠道禁闭** 或 **签约失效**。排查步骤：① 搜手机号找 cid → 搜 cid 找 RESIGN 签约查询日志 → 找出 `queryFrozenFundListByCid` 看 `allRefuse` 是否为 true。若 allRefuse=true 且所有资金方冻结日统一，则是全渠道禁闭，需等解禁时间自动解除。如果不禁闭，再排查还款失败 → 签约失效（`InvalidAgreementHandler`）链路。详细排查方法见下方「签约/重新签约问题排查」章节。 |
| 序列到第 3 步停止 | 被拦截，检查拦截条件和 checkCode |
| 序列到第 4 步停止 | 反欺诈拒绝 |
| 出现"请求出现业务异常" | 提取错误码和异常信息 |
| 出现"出现系统错误" | 提取堆栈 |
| `[资金路由]查询订单定价为null` | 定价异常 |
| `[资金自动路由]被xx借款渠道拒绝` | 资方拒绝，看是否有重新分配 |
| `[借款下单]出现并发请求` | 并发冲突 |
| `[借款下单]订单号:{}因定价问题拦截但返回成功` | 定价问题，但前端显示成功 |
| `[借款试算]api借款还款计划试算请求参数不对` | **apiCheck() 校验失败**。检查 request 参数：① cid 非空 ② loanChanel 必须在 EmbeddedPartnerEnum 中有定义 ③ applyAmount>0 ④ applyStage>0。最常见根因：**EmbeddedPartnerEnum 缺少该渠道编码**（如新增 huijuapi01 但未部署）。诊断：对比本地源码 vs target 编译类 vs 测试环境实际行为。 |
| `[借款试算]api借款还款计划试算结果:所有字段均为null` | 试算结果为空，检查渠道配置或资方定价 |
| 异常日志数 > 入口数，但 Step B 全部 SUCCESS | **重试-成功模式**：部分 traceId 在异常查询中多次出现 → 首次 WARN → 重试 → 成功。健康信号，不是故障。 |
| `queryOverdueMark` 返回 `isOverdue=true` + `CHECK_USER_OVERDUE_HIS`，但 `guideCheckAbility` 返回 `success:true` | **两个接口逻辑不同**：`queryOverdueMark` 在 OrderServiceImpl 中调用 `UserOverDueHisHandler.queryUserOverDueHis()` 返回 true 就直接阻塞；`guideCheckAbility` 在 CustomerLoanAvailableServiceImpl 中对同一方法的结果加了 `BooleanUtils.isFalse()` 反转，语义相反。查问题以 `queryOverdueMark` 返回值为准。 |

## 其他驳回提示词映射

| 用户看到的提示 | 后端枚举 | 拦截点 |
|---------------|---------|--------|
| 您存在不良借款记录，无法借款。 | `CHECK_USER_OVERDUE_HIS` | `OrderServiceImpl.queryOverdueMark` → T4提现门槛 |
| 您有借款已逾期噢，请还款后再来借款~ | `CHECK_USER_OVERDUE` | `OrderServiceImpl.queryOverdueMark` → 当前逾期校验 |
| 您有一笔借款正在处理中，暂时无法发起借款 | `CHECK_LOAN_SUCESS_PRE_WP` | 进行中订单检查 |
| 当前最高可借金额为%s，请降低借款申请额度 | `MAX_BORROWIN_AMOUNT` | 额度上限检查 |
| 一直提示"重新签约"/弹出签约页面 | 无直接枚举 | 全渠道禁闭 → `BeforeLoanOrderService.queryFrozenFundListByCid` allRefuse=true 或 签约失效 → `InvalidAgreementHandler` / 还款失败 → `DeductFailActionEnum.RESIGN` |

## 健康检查解读

**重试模式识别：** 当 Step C 异常日志数 > Step A 入口数，且 Step B 结果全部 SUCCESS 时：
- 统计去重 traceId 数（高频重复 = 重试证据）
- 高频 traceId（出现 >=3 次）标记为重试链路
- 结论：业务异常走重试后全部成功，系统健康

> 参考执行记录: `references/order-health-check-examples-20260517.md`

## 关键字段

traceId, requestId, cid, orderId, orderExtendType, applyAmount, loanSourceEnum, channelEnum

## 日志中标识符的出现形式

> ⚠️ **以下是日志中的写法，不是查询中的写法。** 查询时只用值本身（如 `message:"20161002000002677537"`），不加 `cid:`、`orderId:`、`contractNo:` 等字段前缀。因为同一个值可能以多种形式出现在日志中，直接搜值的召回率最高。

- **orderId**: `orderId:xxx` / `订单号:xxx` / `订单xxx` / 在 request.toString() 中
- **cid**: `cid:xxx` / `客户[xxx]` / `userId:xxx`（老代码）
- **request 对象**: Lombok @ToString 序列化，格式 `ClassName(field1=val, field2=val, ...)`

> cid 和 userId 在不同类中指同一个人，但**查询时直接用值搜**就能同时命中两种写法。
> 只在确认值搜无结果时，才用 OR 尝试：`message:"cid:{value}" OR message:"userId:{value}"`

## 关联服务

order, underwriter, h5-loan, magic, samus-quality（同 topic `f6748b3a`）, datainquiry

> datainquiry 服务的 FundDecisionInfoService 追踪见 `references/data-inquiry-fund-decision-tracing.md`

## 总览式下单健康检查（无指定 traceId/orderId 时）

当用户只问"今天/最近下单情况"而未提供具体标识符时，按以下 4 步渐进查询：

### Step A: 查下单入口量
```
serviceName:"order" AND message:"[借款下单]下单请求为"
```
统计总数、渠道分布、金额区间

### Step B: 查结果状态
```
serviceName:"order" AND message:"[借款下单]下单请求结果为"
```
统计 success=true/false、errorCode、resultCode

### Step C: 查异常
```
serviceName:"order" AND (message:"[借款下单]出现系统错误" OR message:"[借款下单]请求出现业务异常")
```
提取业务异常和系统错误的 traceId，进入 traceId 钻取

### Step D: traceId 钻取（针对异常）
```
traceId:"{提取到的hex值}" AND message:"[借款下单]"
```
看该 traceId 完整生命周期，确认失败原因

### 输出模板（飞书卡片）

| 维度 | 数值 |
|------|------|
| 下单请求总数 | N 笔 |
| 成功 | N 笔 |
| 成功金额合计 | X,XXX |
| 业务异常 | N 笔 |
| 系统错误 | N 笔 |

渠道分布、金额区间、异常详情一并列出。

## 已知坑

- traceId 在 underwriter 服务中会双倍拼接，取第一个出现的值
- orderExtendType 推导逻辑较复杂（TOC_PAY_MAX 等）
- **EmbeddedPartnerEnum 部署版本不一致**：本地 target 编译类可能有新枚举（如 HUIJUAPI01），但源码未提交 OR 测试环境未部署。诊断用"三层对比"：① 源码 EmbeddedPartnerEnum.java ② javap 反编 target 编译类 ③ 测试环境实际行为（调 apiCheck() 会否报参数不对）。仅靠本地源码不可靠。
- **API 借款试算 failed by apiCheck()**：`[借款试算]api借款还款计划试算请求参数不对` 时，不要直接看下游，先确认 apiCheck() 四条件。new channel 最容易漏掉 EmbeddedPartnerEnum 枚举注册。
- **queryOverdueMark vs guideCheckAbility 逻辑分歧**：两个接口都调用 `UserOverDueHisHandler.queryUserOverDueHis()` 但判断逻辑相反：\n  - `queryOverdueMark`（OrderServiceImpl:2180）：`if (queryUserOverDueHis() == true) → 拦截`（正确语义）\n  - `guideCheckAbility`（CustomerLoanAvailableServiceImpl:119）：`if (BooleanUtils.isFalse(queryUserOverDueHis())) → 拦截`（语义反转）\n  - 查问题时以 `queryOverdueMark` 的返回值为准。如果客户在借款能力页被拦截，trace 中会同时出现两个调用，注意区分哪个 actually 触发了错误。`guideCheckAbility` 返回 success:true 不代表客户能借款，`queryOverdueMark` 可能已拦截。\n- **签约后仍提示「重新签约」（RESIGN 缓存陷阱）**：`ReSignChannel` 使用 Redis 缓存签约渠道列表（`RESIGN_CACHE_CHANNEL:*`），TTL=10 分钟，**签约成功后无任何代码清除该缓存**。缓存命中后，返回值**不回写缓存**，缓存中始终存着签约前的旧列表。客户需签署全部渠道（默认 6 个 + 银行特定渠道），仅签部分则其余渠道 ZTX 仍返回未签 → 继续弹重签。10 分钟后缓存过期，ZTX 全已签 → 正常。详见 `references/re-sign-troubleshooting-20260519.md`。

## 测试数据库直连查询

当用户问 `这个cid名下有多少笔未结清合同` / `查这个客户有哪些在还的合同` 等数据问题时，可以直连测试库。凭据见 `references/order-database-access.md`。

**注意**：测试库仅 ~1.5~1.7 万条订单记录，全为测试数据。生产客户（如 `2016...` 开头的 cid）在测试库中不存在。

**生产数据**目前仍无法直连，替代方案：
1. **CLS 日志推断**：搜索 `serviceName:"order" AND message:"{值}"` 看最近订单的 orderStatus（值直接放 message，不加 field 前缀）
2. **连接信息复用**：如果用户提供了生产库连接，按 `references/order-database-access.md` 中的 SQL 查询

## 存量状态查询（"有多少笔未结清合同"类问题）

> ⚠️ **意图分类为"存量状态查询"时使用本章节，不使用入口覆盖表。**
> 核心原则不变：**先看代码确认哪些日志包含合同状态信息，再用代码中的日志模式去 CLS 查。**

### 正确做法

```text
Step 1: grep 代码 — 找到打印合同状态的日志语句
   搜索关键词: contractNoState / orderStatus / order_status / isNotSettle / REPAYING
   目标: 找到哪些类、哪些方法会在日志中打印合同状态
   记录: 这些日志属于哪个项目(serviceName)、日志前缀是什么

Step 2: 根据代码确认的日志模式，构造 CLS 查询
   方案 A（精确）: serviceName:"{项目名}" AND message:"{日志前缀关键词}" AND message:"{cid值}"
   方案 B（宽泛）: serviceName:"order" AND message:"{cid值}"
   ← 值直接搜，不加 cid: 前缀
   ← 如果 Step 1 找到了明确的日志前缀，优先用方案 A

Step 3: 用 AppleScript + 本地 Chrome 执行查询，提取页面文本

   导航到 CLS URL 后，等待 8~12 秒加载完成。
   提取完整 innerText 保存到文件，用 Python 正则解析。

   ❌ 不要用 document.body.innerText.substring(0,500) 检查数据
      — CLS 页面前 ~2000 字符都是 sidebar/工具栏，截取前缀会完全错过日志区
      — 看起来像"0 条结果"但实际上有数据

   ✅ 正确做法：
      osascript -e '... javascript "document.body.innerText"' > /tmp/cls_out.txt
      用 Python 读文件解析

   如果日志量很大（数百到数千条），页面只显示 20 条，需要反复点击"加载更多"：
      for i in $(seq 1 10); do
        osascript -e '... javascript "[...document.querySelectorAll(\"button\")].find(b => b.textContent.trim() === \"加载更多\")?.click()"'
        sleep 1
      done

Step 4: 在结果中 grep contractNoState / orderStatus / contractNo 字段

   用 Python 正则解析全页文本:
      import re
      text = open('/tmp/cls_out.txt').read()
      unique_contracts = set(re.findall(r'contractNo":"(C[KS][^"]+)"', text))
      # contractNoState 只在特定日志类中有，不是所有合同都有
      states = {}
      for m in re.finditer(r'contractNo":"([^"]+)".*?contractNoState":"([^"]+)"', text, re.DOTALL):
          states[m.group(1)] = m.group(2)

   匹配未结清状态: contractNoState IN (REPAYING, OVERDUE)
   辅助验证: accountStatus = ACTIVE 表示合同仍活跃

Step 5: 去重统计 unique contractNo

Step 6: 说明限制 — CLS 仅保留30天日志，30天内无活动的存量合同不会出现

Step 7: ★ 发飞书卡片（必须）
```

> **Tom 之前的错误**：grep 代码时找到了 SQL/DAO 方法（`isNotSettle`、`queryNoSettleOrders`），但没有继续找**打印合同状态的 log 语句**，而是直接去连数据库。应该从 DAO 方法的调用方往上追溯，找到打印日志的地方。

### 禁止操作

**禁止搜索以下日志前缀**（这些是新下单操作的日志，不反映存量状态）：
- `[借款下单]下单请求为`
- `[借款下单]下单请求结果为`
- 入口覆盖表中的所有流程追踪查询

### 数据定义

- `isNotSettle`（未结清计数）：`order_status NOT IN ('REPAYED','REFUNDSETTLED','SETTLED','EARLY_REPAYED','CANCEL','FAIL','SINGFAIL','LOAN_REFUSE')`
- `queryNoSettleOrders`（未结清列表）：`order_status IN ('REPAYING','OVERDUE')`

> 完整 SQL 见 `references/order-database-access.md`。
> CLS 替代方案实操手法（合同数据提取/账务还款计划确认/多合同对比）见 `references/contract-data-from-cls.md`。
> 账务同步时间点确认用 `serviceName:"order" AND message:"同步单个订单还款状态,查询中腾信账务信息" AND message:"{contractNo}"`。
