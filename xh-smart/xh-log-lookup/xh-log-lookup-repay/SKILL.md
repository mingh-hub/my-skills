---
name: xh-log-lookup-repay
description: 还款模块日志查询规则，覆盖客户主动还款、账务批扣、聚合支付、API 还款、回调通知订单、结清确认和还款拦截排查。用于按 contractNo、orderId、traceId 排查还款链路、失败原因、成功时间线和结果通知。
version: 1.2.0
author: xh-smart
platforms: [macos]
metadata:
  hermes:
    tags: [repay, payment, logs, xhqb]
---

# 还款日志查询

## 关联项目

- 后端：`order`
- 自营前端入口：调用 `H5LoanProject` 的 HTTP 服务
- API 渠道入口：调用 `order` 的 Dubbo 服务

## 查询主键

| 输入 | 默认优先级 | 说明 |
|------|------------|------|
| `orderId` | 客户主动还款优先 | 适合追单笔还款发起、聚合支付和回调链路 |
| `contractNo` | 账务批扣/结果通知优先 | 适合结清确认、通知订单、日切确认 |
| `traceId` | 最高优先级直搜 | 直接 `traceId:"{value}"`，不拼 `serviceName` |

## 总体规则

- 还款分两条主线：客户主动还款、账务批扣。
- 客户主动还款再分自营和 API 渠道。
- 账务只要有结果，就会通知订单系统；没有看到订单通知日志时，不要直接下最终成功/失败结论。
- 还款请求时间不等于实际结清时间。
- `traceId` 按原值查询，支持 16 位或 32 位 hex。

## 客户主动还款

### 自营客户

| 场景 | 方法入口 | 日志锚点 | 推荐查询 |
|------|----------|----------|----------|
| 还款前可还时间校验 | `com.xhqb.h5loan.biz.service.controller.RepayController#checkRepayAvailableTime` | `校验是否可还款` | `serviceName:"h5-loan" AND message:"校验是否可还款"` |
| 列表入口还款 | `com.xhqb.h5loan.biz.service.controller.RepayController#sendRepay` | `[还款请求]客户cid` / `还款请求,request` | `serviceName:"h5-loan" AND message:"还款请求"` |
| 客户聚合支付入口（新） | `com.xhqb.h5loan.biz.service.controller.AggregateRepayController#aggrAutoSendRepay` | `aggrAutoSendRepay` / `[聚合支付]发起支付result` | `serviceName:"h5-loan" AND message:"aggrAutoSendRepay"` |
| 客户聚合支付（老）/一键还款 | `com.xhqb.h5loan.biz.service.controller.AggregateRepayController#aggregateRepaySend` | `aggregateRepaySend` / `[聚合支付]客户发起还款` | `serviceName:"h5-loan" AND message:"aggregateRepaySend"` |

### API 客户

| 场景 | 方法入口 | 日志锚点 | 推荐查询 |
|------|----------|----------|----------|
| 还款试算 | `com.xhqb.order.common.service.api.RepayService#trial` | `trial` / 试算日志 | 先查 `traceId`，没有则按 `orderId` 宽搜 |
| API 还款试算 | `com.xhqb.order.common.service.RepayOrderService#apiRepaymentRequest` | `[还款请求]` / `apiRepaymentRequest` | `serviceName:"order" AND message:"[还款请求]" AND message:"{orderId}"` |
| API 发起还款 | `com.xhqb.order.common.service.ApiRepayService#sendRepay` | `orderId=[{orderId}]是API渠道` / `还款请求` | `serviceName:"order" AND message:"orderId=[{orderId}]" AND message:"API渠道"` |

## 账务批扣与结果通知

| 场景 | 方法入口 | 日志锚点 | 推荐查询 | 结论意义 |
|------|----------|----------|----------|----------|
| 还款成功通知 | `com.xhqb.order.batch.service.apiConsumer.ApiRepayNoticeConsumer#handleMessage` | `ApiRepayNoticeConsumer推进来的消息ID` / `[账务扣款]接受到账务扣款成功信息` | `serviceName:"order-batch" AND message:"ApiRepayNoticeConsumer推进来的消息ID"` | 这是成功结果进入订单系统的强信号 |
| 还款失败通知 | `com.xhqb.order.batch.service.ZtxAccountDeductFailConsumer#handleMessage` | `ZtxAccountDeductFailConsumer推进来的消息ID` / `[还款失败]处理信息请求为` | `serviceName:"order-batch" AND message:"ZtxAccountDeductFailConsumer推进来的消息ID"` | 这是失败结果进入订单系统的强信号 |

## 结清确认

### 确认顺序

1. 先查发起日志，确认是客户主动还款还是账务批扣。
2. 再查回调/通知日志，确认订单系统是否已收到结果。
3. 最后查结清确认信号，不要把请求时间当成功时间。

### 强结论信号

| 信号 | 含义 |
|------|------|
| `"{orderId}的还款成功，恢复额度:{amount}"` | 实际结清成功 |
| `ApiRepayNoticeConsumer推进来的消息ID` | 账务成功结果进入订单系统 |
| `ZtxAccountDeductFailConsumer推进来的消息ID` | 账务失败结果进入订单系统 |
| `最近结清期数: N` | 日切确认已结清期次 |

## 查询拦截排查

当用户反馈“不能还款”或“提前结清于资金到账N天后可发起”时，优先看 H5 层拦截，不要直接只查 `order`。

| 提示 | 位置 | 说明 |
|------|------|------|
| `提前结清于资金到账N天后可发起` | `H5LoanProject.RepayController#queryRepayOrderInfo` / `needWeakenSettle` | 新客/资方规则拦截 |
| `系统维护中，请在[...]后还款` | `order` 侧时间限制 | 黑暗期拦截 |
| `当前不支持提前还款` | `order` 侧日期限制 | 提前还款日期限制 |
| 账务校验拦截 | `order` 侧账务校验 | 可能来自 `account` / `loki` |

## 推荐首查

| 用户提供 | 推荐首查语句 |
|---------|-------------|
| `orderId` | `serviceName:"order" AND message:"还款请求" AND message:"{orderId}"` |
| `contractNo` | `serviceName:"order" AND message:"{contractNo}"` |
| `traceId` | `traceId:"{value}"` |

## 常见误区

- `还款请求` 只代表发起，不代表结清。
- `DEDUCT_NOTIVE` 不是结清时间，只是同步消息。
- `最近结清期数` 是日切结果，不是实时扣款时刻。
- `traceId` 不要只按 16 位理解，原样查询。
- `BATCH_DUE`代表账务批扣通知

## References

- `references/new-customer-early-repay-intercept.md`
- `references/settled-period-tracing.md`
- `references/repay-calc-logic.md`
