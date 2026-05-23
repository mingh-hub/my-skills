---
name: xh-log-lookup-benefit
description: 权益模块日志查询规则 — 权益/会员/优惠券/乐活卡的入口覆盖和查询模板
version: 1.1.0
author: xh-smart
platforms: [macos]
metadata:
  hermes:
    tags: [benefit, coupon, member, logs, xhqb]
---

# 权益日志查询 — 业务规则

## 涉及项目

member, rubick, benefit, activity, order (CouponService), h5-loan (SelfLoanProcessStrategy)

## 核心流程链路追踪模版

> 权益模块跨多个服务，注意 serviceName 按实际项目切换。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 优惠券查询 | `com.xhqb.order.biz.service.impl.CouponServiceImpl#checkCouponIsAvailable` | `[优惠券处理]查询优惠券是否可用` | `serviceName:"order" AND message:"[优惠券处理]" AND message:"{orderId或cid}"` | | 私有方法锚点，查询时优先用订单/客户值搜 |
| 优惠券使用 | `com.xhqb.order.biz.service.impl.CouponServiceImpl#handleCouponDerate` | `[优惠券处理]调用账务使用优惠券` | `serviceName:"order" AND message:"[优惠券处理]调用账务" AND message:"{orderId}"` | | 账务调用失败时继续查 coupon 待处理记录 |
| 返现券 | `com.xhqb.order.biz.service.event.cashback.CashBackEventListen#onApplicationEvent` | `[返现券]` | `serviceName:"order" AND message:"[返现券]" AND message:"{orderId}"` | | 还款成功事件和页面计算都可能出现返现券日志 |
| 权益订单 | `com.xhqb.order.biz.service.impl.ChannelBenefitOrderServiceImpl#saveBenefitOrder` | `[权益订单]创建` | `serviceName:"order" AND message:"[权益订单]" AND message:"orderId:{orderId}"` | | 权益订单创建入口 |
| 乐活月卡 | `com.xhqb.order.biz.service.event.lhkmon.LhkMonEventListener#handleEvent` | `[乐活月卡]` | `serviceName:"order" AND message:"[乐活月卡]" AND message:"{cid}"` | | 放款结果事件触发 |
| 获额卡 | `com.xhqb.order.biz.service.impl.UserOrderServiceImpl#queryIsSubNewMarketUser` | `[获额卡]` | `serviceName:"order" AND message:"[获额卡]" AND message:"cid:{cid}"` | | 获额卡规则查询入口 |
| H5 权益勾选 | `待代码确认: SelfLoanProcessStrategy#loanProcess` | `是否勾选权益` | `serviceName:"h5-loan" AND message:"是否勾选权益"` | | 本地未发现 h5-loan 源码，查询前需按 h5-loan 代码确认 |
| 电商权益拦截 | `待代码确认: SelfLoanProcessStrategy#loanProcess` | `电商权益拦截` | `serviceName:"h5-loan" AND message:"电商权益拦截"` | | 本地未发现 h5-loan 源码 |
| 异常权益订单(01) | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]保存异常权益订单记录` | `serviceName:"order" AND message:"保存异常权益订单记录"` | | 勾选权益但未生成权益订单且为 24 期定价 |
| 异常权益订单(02) | `com.xhqb.order.biz.service.impl.OrderServiceImpl#getOrderPrice` | `[规则定价]保存异常权益订单记录` | `serviceName:"order" AND message:"保存异常权益订单记录"` | | 勾选权益但订单仍为 36 期定价 |
| 异常权益订单(03) | `com.xhqb.order.biz.service.event.marketdeduct.MarketDeductEventListen#onApplicationEvent` | `[未通知权益]保存异常权益订单记录` | `serviceName:"order" AND message:"保存异常权益订单记录"` | | 权益系统通知失败 |
| 权益校验异常 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loan` | `权益校验异常` | `serviceName:"order" AND message:"权益校验异常"` | | 下单模板内权益校验 |
| 渠道权益通知 | `com.xhqb.order.biz.service.impl.loan.ApiLoanService#loanOrder` | `渠道权益下单通知` | `serviceName:"order" AND message:"渠道权益下单通知"` | | API 下单权益通知 |
| 权益包查询 | `com.xhqb.order.biz.service.external.market.MarketService#queryBenefitProductInfo` | `[权益包信息]` | `serviceName:"order" AND message:"权益包信息"` | | 调 market/member 查询权益包信息 |
| 权益申请 | `com.xhqb.order.biz.service.impl.api.LoanVipServiceImpl#loanVipApply` | `[权益申请]权益申请` | `serviceName:"order" AND message:"权益申请"` | | 权益申请主入口 |

## 用户输入 → 首次查询策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| orderId | serviceName:"order" AND message:"[优惠券处理]" AND message:"{value}" | |
| cid | serviceName:"h5-loan" AND message:"是否勾选权益" AND message:"{value}" | H5 试算环节权益勾选 |
| traceId/线程号 | traceId:"{value}" | 直接全链路，**不加 serviceName** |

## 异常权益订单类型枚举

| 异常类型 | 含义 | 触发类 |
|---------|------|--------|
| `01` | 勾选购买权益但未生成权益订单且为24期定价 | LoanServiceImpl:376 |
| `02` | 勾选购买权益但订单仍为36期定价 | OrderServiceImpl:6100 |
| `03` | 勾选购买权益但未通知权益系统 | MarketDeductEventListen:541 |

## 关键字段值域

| 字段 | 值 | 含义 |
|------|---|------|
| `orderPriceType` | `1` | 普通定价（未勾选权益） |
| `orderPriceType` | `5` | 权益价（已勾选权益包） |
| `userPriceType` | `1` | 用户定价等级1 |
| `isVisibleVip` | true/false | 强制弹窗可见权益勾选 |
| `isChoiceVip` | true/false | 客户手动勾选权益 |

## 权益统计指标

| 指标 | 查询方式 |
|------|----------|
| 总权益勾选次数 | `serviceName:"h5-loan" AND message:"是否勾选权益"` |
| 已勾选权益次数 | `serviceName:"h5-loan" AND message:"是否勾选权益=true"` |
| 未勾选权益次数 | `serviceName:"h5-loan" AND message:"是否勾选权益=false"` |
| 权益勾选率 | 已勾选 / 总次数 |
| 异常权益订单 | `serviceName:"order" AND message:"保存异常权益订单记录"` |

## 失败模式

| 现象 | 诊断 |
|------|------|
| [优惠券处理]查询结果为不可用 | 检查优惠券状态、有效期、使用条件 |
| [创建记录]优惠券使用失败 | 账务侧调用失败 |
| [权益订单]创建后无后续日志 | 下游服务未响应 |
| 保存异常权益订单记录(01) | 权益订单未生成但为24期定价 |
| 保存异常权益订单记录(02) | 勾选权益但仍为36期定价，定价未生效 |
| 保存异常权益订单记录(03) | 权益系统通知失败 |
| 权益校验异常 | LoanTemplate 抛出异常，检查权益包状态 |

## 关联服务

order, h5-loan, member, rubick, benefit, activity
