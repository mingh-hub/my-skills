---
name: xh-log-lookup-repay
description: 还款模块日志查询规则 — 还款/代扣/聚合支付/好友代付的入口覆盖、查询模板和失败模式
version: 1.1.0
author: xh-smart
platforms: [macos]
metadata:
  hermes:
    tags: [repay, payment, logs, xhqb]
---

# 还款日志查询 — 业务规则

## 涉及项目

**后端**: order (RepayOrderServiceImpl, ArbitrarilyRepayServiceImpl, AggregateRepayServiceImpl), account

**前端/API 层**: H5LoanProject (`RepayController.java` — 还款查询/还款发起入口。拦截逻辑、弹窗消息很多在这里，不在 order 服务日志里)

**排查陷阱**: 用户反馈的还款页面提示信息（拦截弹窗、不能还款原因）可能来自 H5LoanProject 的 `RepayController.queryRepayOrderInfo()`，不是 order 服务的返回。查不到 order 日志不代表没有拦截——先搜 H5LoanProject 源码确认消息来源。

## 核心流程链路追踪模版

> Phase A 查询统一前缀: `serviceName:"order" AND ...`（还款逻辑也在 order 服务中）

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 还款请求 | `com.xhqb.order.biz.service.impl.ArbitrarilyRepayServiceImpl#sendRepay` | `还款请求`、`支付金额` | `serviceName:"order" AND message:"还款请求" AND message:"orderId:{value}"` | | 借助 orderId 或 contractNo 值搜确认完整链路 |
| 还款状态同步 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#syncRepaySingleOrder` | `同步单个订单还款状态` | `serviceName:"order" AND message:"同步单个订单还款状态" AND message:"订单{orderId}"` | | 自动代扣/回调状态同步入口 |
| 合同还款状态 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#syncRepaySingleOrder` | `合同`、`订单状态`、`账户状态` | `serviceName:"order" AND message:"合同{contractNo}"` | | message 中的 contractNo placeholder 不参与锚点校验 |
| 还款试算 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#computeEarlyRepay` | `[还款试算]` | `serviceName:"order" AND message:"[还款试算]" AND message:"{contractNo}"` | | 正常/提前结清试算可能落在不同私有方法 |
| 任性还款（即期/提前结清） | `com.xhqb.order.biz.service.impl.ArbitrarilyRepayServiceImpl#sendRepay` | `还款请求,保存还款流水` | `serviceName:"order" AND message:"还款请求,保存还款流水" AND message:"{contractNo}"` | | 只能证明请求入库，不能证明结清成功 |
| 聚合支付 | `com.xhqb.order.biz.service.impl.AggregateRepayServiceImpl#aggregateRapaySend` | `[聚合支付]`、`还款请求` | `serviceName:"order" AND message:"[聚合支付]" AND message:"orderId:{value}"` | | 0 命中时退回 orderId/contractNo 值搜 |
| 聚合支付检查 | `com.xhqb.order.biz.service.impl.AggregateRepayServiceImpl#aggregateRepayCheck` | `[聚合支付类型]查询` | `serviceName:"order" AND message:"[聚合支付类型]查询" AND message:"orderId:{value}"` | | 模板若不匹配，以当前代码锚点为准 |
| 好友代付 | `com.xhqb.order.biz.service.impl.AggregateRepayServiceImpl#friendRepayInit` | `[好友代付]` | `serviceName:"order" AND message:"[好友代付]" AND message:"{orderId}"` | | 方法名如变更，先搜 `[好友代付]` 锚点 |
| API代扣 | `com.xhqb.order.biz.service.impl.ArbitrarilyRepayServiceImpl#sendRepay` | `orderId=[{}]是API渠道` | `serviceName:"order" AND message:"orderId=[{value}]"` | | 固定片段为 `orderId=[` 和 `是API渠道` |
| 查询异常 | `com.xhqb.order.biz.service.impl.ArbitrarilyRepayServiceImpl#queryRepayOrderInfo` | `[查询订单信息以及还款金额]` | `serviceName:"order" AND message:"[查询订单信息以及还款金额]" AND message:"cid:{cid}"` | | cid 查不到时改用 orderId/contractNo |
| 返现券 | `com.xhqb.order.biz.service.impl.ArbitrarilyRepayServiceImpl#queryRepayOrderInfo` | `[返现券]计算返现券请求` | `serviceName:"order" AND message:"[返现券]" AND message:"orderId:{value}"` | | 还款页面返现券计算入口 |
| 订单已出账（某期已到还款日） | `com.xhqb.order.biz.service.impl.ArbitrarilyRepayServiceImpl#queryRepayOrderInfo` | `订单id`、`期已出账` | `serviceName:"order" AND message:"{orderId}" AND message:"期已出账"` | | 只表示该期到还款日，不等于结清 |

## 用户输入 → 首次查询策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| orderId | serviceName:"order" AND message:"还款请求" AND message:"orderId:{value}" | |
| contractNo | serviceName:"order" AND message:"合同{value}" | 还款模块最常用的标识符 |
| cid | serviceName:"order" AND message:"[查询订单信息以及还款金额]" AND message:"cid:{value}" | |
| traceId/线程号 | traceId:"{value}" | 直接全链路，**不加 serviceName** |

## 日志中标识符的出现形式

- **orderId**: `orderId:{xxx}` / 在 repayRecord.toString() 中
- **contractNo**: `合同{xxx}` / `contractNo:{xxx}` / `合同号:{xxx}`（还款模块最常见的标识符）
- **cid**: `cid:{xxx}` / `userId:{xxx}`

> contractNo 是还款场景中最常用的标识符，优先使用。

## ⚠️ 关键区分：还款请求时间 ≠ 实际结清成功时间

**这是一个容易犯错但非常重要的区分。** 用户问"某期什么时候结清"时，要的是**扣款实际成功的时间**，不是客户发起还款请求的时间。发起还款可能失败，不能以请求时间为准。

### 哪条日志才是"实际结清成功"的确认信号？

| 日志 | 类 | 可作确认信号？ |
|------|----|:---:|
| `还款请求,保存还款流水` | ArbitrarilyRepayServiceImpl | ❌ 仅表示请求被收到 |
| `订单id:{orderId}的N期已出账` | ArbitrarilyRepayServiceImpl | ❌ 该期到还款日 |
| `[聚合支付类型]查询` | AggregateRepayServiceImpl | ❌ 支付检查通过 |
| `查询微信订阅结果` | ArbitrarilyRepayServiceImpl | ⚠️ 中间态 |
| **`{orderId}的还款成功，恢复额度:{amount}`** | **RepayOrderServiceImpl** | **✅ 确凿** |
| `[返现券]还款成功处理请求 (stageNbr=N)` | CashBackEventListen | ✅ 佐证 |
| `REPAYMENT_SUCCESS` (SQS推送微信模板) | JmsQService | ✅ 佐证 |
| `最近结清期数: N` (日切) | account-swift-app-job | ✅ 但延迟至凌晨 |
| `syncType:DEDUCT_NOTIVE` | JmsQService | ⚠️ 不一定等于成功 |

### 判断原则

> **⛔ 不要用「还款请求」时间当结清时间。** 请求可能失败、超时、被回调拒绝。
> **✅ 结清确认的唯一铁证**：`RepayOrderServiceImpl` 打印的 `{orderId}的还款成功，恢复额度:{amount}`。看到这条日志才是系统确认扣款成功的时刻。

如果只有请求日志没有"还款成功"日志，说明请求还在处理中、支付未确认、或已失败。需要进一步查 `DEDUCT_NOTIVE` 回调和 `pay-app-bill` 对账状态。

## 已结清期次查询（"第一期什么时候结清"类问题）

当用户问某合同的某期次是否已结清/何时结清时，分三步查：

### Phase A：确认已结清期次 — 查 account-swift-app-job 日切日志

```
message:"{contractNo}" AND message:"最近结清期数"
```

这个关键词出现在 account-swift-app-job 服务的日切（daily cutover）任务中。示例输出：

```
账户: CK202604090001010, 最近结清期数: 1, 剩余未还本金: 4339.6
```

**含义**：系统确认最近一次结清的是第 N 期。剩余未还本金是下一期的本金。

> 日切任务每天跑一次（凌晨），所以日志中的「最近结清期数」反映的是截至日切点的状态。

### Phase B：搜 orderId 追溯完整还款时间线

通过 orderId（可从 Phase A 的结果中提取）反向查找整个还款流程：

```
serviceName:"order" AND message:"{orderId}"
```

关键日志序列（从请求到成功，按时间排序）：

| 时间点 | 日志 | 含义 |
|--------|------|------|
| T+0s | `订单id:{orderId}的N期已出账` (ArbitrarilyRepayServiceImpl) | 该期已到还款日，账已出 |
| T+1s | `还款请求,还款记录` (ArbitrarilyRepayServiceImpl) | 收到还款请求 |
| T+2s | `还款请求,保存还款流水` (ArbitrarilyRepayServiceImpl) | 还款流水入库 |
| T+3s | `[聚合支付类型]查询 repayStageDetail=N` (AggregateRepayServiceImpl) | 聚合支付检查通过 |
| T+1~3s | `查询订单信息以及还款金额,获取提前还款金额` (ArbitrarilyRepayServiceImpl) | 计算待还金额 |
| **T+3~4s** | **`{orderId}的还款成功，恢复额度:{amount}`** (**RepayOrderServiceImpl**) | **✅ 实际结清成功** |
| T+3~4s | `[返现券]还款成功处理请求 stageNbr=N` (CashBackEventListen) | 返现事件确认 |
| T+3~4s | `REPAYMENT_SUCCESS` 模板消息推送 (JmsQService) | 微信还款成功通知 |
| T+1h~next day | `syncType:DEDUCT_NOTIVE` (JmsQService MQ) | 同步扣款状态（可能延迟） |

> 从实际案例来看，请求到成功仅需 **3~4 秒**。微信订阅支付回调（DEDUCT_NOTIVE）可能延迟 1 小时以上，但那不是结清的时间点。

### Phase C：确认发起系统 — 查调用链

找到 `ArbitrarilyRepayService.sendRepay` 的 SR（Service Request）调用记录：

```
SR [callerIP:port] [com.xhqb.order.common.service.ArbitrarilyRepayService.sendRepay]
```

调用链：

```
APP客户端（APPWECHAT/微信小程序/Android/iOS/H5）
  → h5-loan 服务 RepayController.sendRepay()  [POST /repay/sendRepay]
    → order 服务 ArbitrarilyRepayService.sendRepay()  [Dubbo RPC]
```

**代码入口**：h5-loan 项目的 `RepayController.java`（`@RequestMapping(value = "/sendRepay")`），会设置 `appChannel`（如 APPWECHAT）、`repayType`（PERIOD_REPAY/EARLY_REPAY）等参数。

**如何判断用户主动 vs 系统代扣**：
- `ArbitrarilyRepayServiceImpl` = 用户主动任性还款
- `RepayOrderServiceImpl.syncRepaySingleOrder` = 自动代扣/扣款回调

### 完整还款链路（从请求到扣款完成）

```
APP客户端（微信APP/小程序等）
  → h5-loan.RepayController.sendRepay()      [POST /repay/sendRepay]
    → order.ArbitrarilyRepayServiceImpl       [Dubbo: 任性还款请求]
      → order.AggregateRepayServiceImpl       [聚合支付类型检查]
        → 微信订阅支付/银行卡代扣              [支付通道]
          → 易宝(yeepay)等网关                [实际扣款]
            → ✅ 扣款成功 → 恢复额度
            → JmsQService MQ发送 DEDUCT_NOTIVE [异步回调]
              → account-swift-app-job 日切     [更新最近结清期数]
              → pay-app-bill 对账              [对账记录]
```

### 示例：查询合同第一期结清时间

```text
Step 1: 宽搜 contractNo
   message:"CK202604090001010"
   → 找到 orderId（如 20260402003723692743）
   → 找到 account-swift-app-job 日切确认「最近结清期数: 1」

Step 2: 搜 orderId 精细定位
   serviceName:"order" AND message:"20260402003723692743"
   → 找到关键日志行：
     11:16:10.084 — 还款请求（ArbitrarilyRepayServiceImpl）
     11:16:13.935 — ✅ 还款成功，恢复额度:360.4（RepayOrderServiceImpl）← 真正结清时间

Step 3: 确认结论
   实际结清时间 = 2026-05-17 11:16:13.935（而非请求时间 11:16:10）
   来源系统 = h5-loan.POST /repay/sendRepay → order.ArbitrarilyRepayServiceImpl（任性还款）
   渠道 = APPWECHAT（微信APP）
```

## 失败模式

| 现象 | 诊断 |
|------|------|
| 支付金额 ≠ 还款金额 - 溢缴金额 - 优惠券金额 | 金额计算异常 |
| "sendRepay并发请求" | 并发还款冲突 |
| "订单{x}合同{x}不存在" | 数据不一致 |
| "已结清" | 重复还款 |
| level:"ERROR" + "[查询订单信息以及还款金额]" | 查询异常，看堆栈 |
| [聚合支付]发起还款后无后续日志 | 下游支付通道超时或无回调 |
| **"提前结清于资金到账N天后可发起，如需帮助请联系在线客服"** | **新客提前结清拦截弹窗（新客提还拦截）**。H5LoanProject RepayController 的 `needWeakenSettle()` 判定，不在 order 日志中。含义：该合同是新客/特定资方，放款至今未满 N 天（配置项 `weaken.settle.rule` 中的 `oldPopWindowDays`/`newPopWindowDays`），被主动拦截了提前结清入口，**不是异常，是业务规则**。也会伴随 `setPopWindow(true)`。 |
| 页面显示"不能还款原因"但无 ERROR 日志 | 原因通常设置于 `QueryRepayOrderResult.canotRepayReason`，由后端还款校验链（`RepaymentAbility.timeLimit`/`dateLimit`/`accountingLimit`）返回。逐层检查：时间限制 → 日期限制 → 账务校验。`OrdinaryRepaymentLimit` 和 `ImperfectRepaymentLimit` 是主要实现类。 |

## 关联服务

order, account（合约/账务）, **H5LoanProject**（还款查询 API 入口）

## ⚠️ 还款查询拦截排查指南

当用户反馈"查询还款信息时提示XX不能还款"时，**不要直接去 order 日志找原因**。还款页面的拦截按以下链路排查：

### 排查链路

```
用户页面
  → H5LoanProject RepayController.queryRepayOrderInfo()    [访问 queryRepayOrderInfo 源码]
    → order.ArbitrarilyRepayServiceImpl.queryRepayOrderInfo() [order RPC]
      → RepaymentAbility.timeLimit()                         [时间限制: 黑暗期/特殊时间]
      → RepaymentAbility.dateLimit()                         [日期限制: earlyStagesRepayDays]
      → RepaymentAbility.accountingLimit()/accountLimit()    [账务校验: checkRepay/checkOrderCanRepay]
```

### 各类拦截消息的代码位置

| 提示消息关键词 | 代码位置 | 含义 |
|--------------|---------|------|
| "天后可发起"、"提前结清于资金到账" | H5LoanProject `RepayController.needWeakenSettle()` + `queryRepayOrderInfo()` 第475-477行 | 新客/特定资方提前结清拦截。`popWindowDays` 来自 Apollo 配置 `weaken.settle.rule` |
| "系统维护中，请在[...]后还款" | order `OrdinaryRepaymentLimit.timeLimit()` 第100行 | 还款黑暗期，支付系统维护 |
| "当前不支持提前还款" | order `OrdinaryRepaymentLimit.dateLimit()` 第212行 | 提前还款日期限制（`earlyStagesRepayDays` 配置） |
| 账务校验拦截（无统一消息） | order `ImperfectRepaymentLimit.accountingLimit()` | 由 `advancedRepayService.checkRepay()` 或 `repaySupportService.checkOrderCanRepay()` 返回。结果来自 loki 服务等 |

### 搜索策略

- **消息在源码内**（如"天后可发起"）→ `grep -r '关键词' /Users/user/mingh/workspace/ --include='*.java'`。消息可能不在 order 项目，需要在 H5LoanProject/loki 等其他项目搜索。
- **消息由后端接口返回**（`ResultEnum` 枚举）→ 查 ResultEnum 定义或对应枚举值。
- **消息由前端写死** → 不在此技能范围，确认后标记为前端静态文案。

## References

- `references/new-customer-early-repay-intercept.md`：新客提前结清拦截（新客提还拦截弹窗规则、`needWeakenSettle()` 代码位置）
- `references/repay-calc-logic.md`：还款订单列表和逾期金额计算逻辑（`queryRepayOrderList` 入口）
- `references/settled-period-tracing.md`：已结清期次追踪实战参考（account-swift-app-job 日切信号、出账确认）
