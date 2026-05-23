---
name: xh-log-lookup-loan
description: 放款模块日志查询规则 — 资金路由/放款推送/解H的入口覆盖和查询模板
version: 1.0.0
author: xh-smart
platforms: [macos]
metadata:
  hermes:
    tags: [loan, fund-route, disbursement, logs, xhqb]
---

# 放款日志查询 — 业务规则

## 涉及项目

order (OrderRouteService, LoanOrderServiceImpl, ReleaseHoldOrderServiceImpl), loki

## 核心流程链路追踪模版

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 资金路由 | `com.xhqb.order.biz.service.impl.LoanOrderServiceImpl#loanOrder` | `[资金路由]` | `serviceName:"order" AND message:"[资金路由]" AND message:"orderId:{orderId}"` | | 资金路由主链路 |
| 自动路由 | `com.xhqb.order.biz.service.impl.LoanOrderServiceImpl#loanOrder` | `资金自动路由` | `serviceName:"order" AND message:"资金自动路由" AND message:"{orderId}"` | | 代码里前缀含动态订单/期数字段，避免硬搜完整中括号 |
| 放款成功 | `com.xhqb.order.biz.service.event.marketdeduct.MarketDeductEventListen#onApplicationEvent` | `[放款成功]` | `serviceName:"order" AND message:"[放款成功]" AND message:"{orderId}"` | | 放款成功后的权益/划扣事件 |
| 放款流程 | `com.xhqb.order.biz.service.impl.SpecFundCreditServiceImpl#loanProcess` | `[放款流程]` | `serviceName:"order" AND message:"[放款流程]" AND message:"{orderId}"` | | 特定资方额度修改放款流程 |
| 特项额度 | `com.xhqb.order.biz.service.impl.SpecFundCreditServiceImpl#saveSpecFundCredit` | `[特项额度]`、`客户` | `serviceName:"order" AND message:"[特项额度]" AND message:"客户:{cid}"` | | 查询/保存/修改额度共用锚点 |
| 解H | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#releaseHoldOrder` | `[新解H]` | `serviceName:"order" AND message:"[新解H]" AND message:"[{orderId}]"` | | 解H job 和订单维度处理日志很多，先按 orderId 值搜 |
| 拒就赔JOB | `com.xhqb.order.biz.service.impl.RejectCompensateServiceImpl#handleRecordJob` | `[拒就赔JOB]` | `serviceName:"order" AND message:"[拒就赔JOB]" AND message:"orderId:{orderId}"` | | 拒就赔解H处理 |
| 提前结清 | `com.xhqb.order.biz.service.impl.others.CtcfService#queryEarlySettleGetFeeDetail` | `[提前结清]` | `serviceName:"order" AND message:"[提前结清]" AND message:"{contractNo}"` | | 资方提前结清金额查询 |

## 用户输入 → 首次查询策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| orderId | serviceName:"order" AND message:"[资金路由]" AND message:"orderId:{value}" | |
| cid | serviceName:"order" AND message:"[特项额度]" AND message:"客户:{value}" | |
| traceId/线程号 | traceId:"{value}" | 直接全链路，**不加 serviceName** |

## 失败模式

| 现象 | 诊断 |
|------|------|
| `[资金路由]查询订单定价为null/0` | 定价数据缺失 |
| `[资金路由]根据用户定价类型查询产品结果有误` | 产品配置问题 |
| `[资金自动路由]被{x}借款渠道拒绝，重新分配` | 资方拒绝，观察是否有重新分配成功 |
| `无借款渠道可走` | 所有资方均拒绝，需人工介入 |
| `反欺诈通过` 后无放款日志 | 路由环节卡住或 loki 服务异常 |
| `反欺诈不通过` | 风控拒绝 |
| `借款复核拒绝` | 复核环节被拒 |
| `[提前结清]...有效账户不存在` | 合同在资金方侧无有效账户记录（数据问题/销户），见 `references/early-settle-card-template.md` |
| `[提前结清]调用{资方}提前结清金额明细查询结果,result:{"status":"FAIL"...` | 资方提前结清查询返回失败，需查看具体 errMsg |
| `[提前结清]...system error/http error` | 调用资方接口网络异常或超时 |

## 待补充

> 以下内容需要根据实际业务补充:
> - loki 服务的日志前缀和入口
> - 放款完整生命周期期望序列
> - 各资方的特定日志模式

## 关联服务

order, loki, underwriter, frontendcenter, account-gateway

## 提前结清飞书卡片模板

提前结清失败的标准化飞书卡片模板见：`references/early-settle-card-template.md`。包含调用链展示、资方错误、诊断结论和按钮配置。
