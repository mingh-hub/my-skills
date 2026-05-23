---
name: xh-log-lookup-order
description: 订单模块日志查询规则。Use when investigating order/loan 下单, 续签, 借款能力预检, T4 提现门槛, 反欺诈, 资金路由, orderId/cid/contractNo, 存量未结清合同, or order health checks.
metadata:
  hermes:
    version: 2.1.0
    author: xh-smart
    platforms: [macos]
    tags: [order, loan, logs, cid, orderId, contractNo]
---

# 订单日志查询

订单模块子 Skill 只提供`首查策略`、`核心流程追踪入口`、`关键失败场景`、`健康检查`。CLS 执行、加载更多、飞书卡片输出统一交给 `xh-log-lookup` 主控工具。

## 涉及服务

主服务：`order，order-batch，order-batch-timing`。

常见关联服务：`h5-loan`、`loki-webapp`、`datainquiry`、`cif`、`account`、`underwriter`、`magic`、`member`。

## 首查策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| 线程号：`traceId` | `traceId:"{value}"` | 值搜，全链路查询，不加 `serviceName` |
| 订单号：`orderId` | `serviceName:"order" AND message:"{value}"` | 值搜 |
| 客户id：`cid`，`userId`，`customerId` | `serviceName:"order" AND message:"{value}"` | 值搜 |
| 合同号：`contractNo` | `serviceName:"order" AND message:"{value}"` | 值搜 |
| 手机号：`mobilePhone，mobileNo` | 根据手机号定位 `cid`、`orderId`后再根据`cid`或者`orderId`来搜 | 找不到时扩大查询时间`now-7d,now`->`now-30d,now` |
| 身份证号：`identityNo` | 根据身份证号定位 `cid`、`orderId`后再根据`cid`或者`orderId`来搜 | 找不到时扩大查询时间`now-7d,now`->`now-30d,now` |

## 核心流程链路追踪模版

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 下单请求 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]下单请求为` | `serviceName:"order" AND message:"[借款下单]下单请求为" AND message:"{value}"` | <ul><li>`loanSourceEnum`：借款来源，区分自营还是API，`SELF_SUPPORT`-自营，`API`-API</li><li>`cid`：客户ID</li><li>`orderId`：订单号，`API`渠道才有值，自营是在接口内部生成</li><li>`applyAmount`：借款金额</li><li>`stage`：借款期数</li><li>`loanChannel`：借款渠道</li><li>`orderPrice`：订单定价</li><li>`channelPrice`：渠道定价</li><li>`choiceMember`：是否购买权益，`true`-已购买，`false`-未购买</li><li>`orderExtendType`：订单类型</li><li>`lhkId`：乐活卡ID</li><li>`rejectCompensateId`：拒就赔ID</li><li>`isJSmode`：是否极速模式借款，`true`-是，`false`-否</li><li>`isOpenMarketing`：是否勾选尊享卡，`true`-是，`false`-否</li><li>`ssyPageType`：试算页标识，`8`-会进入合规拦截业务</li></ul> | 校验通过后作为首查入口。相关 WARN 锚点：`[借款下单]出现并发请求`（Redis 锁拦截）、`[借款下单]请求参数有误` |
| 下单核心 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loan` | - | - | | **下单核心流程总控，包含流程：`下单拦截`、`合规拦截/极速模式校验`、`前置处理`、`业务处理`、`后置处理（含反欺诈）`** |
| 下单拦截 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanCheck` | `[借款校验]进入` | `serviceName:"order" AND message:"[借款校验]进入"` | | **下单核心流程之一** |
| 下单拦截结果 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loan` | `[借款下单]下单拦截请求` | `serviceName:"order" AND message:"[借款下单]下单拦截请求"` | <ul><li>`intercept`：`true`-拦截，`false`-未拦截</li><li>`interceptFilter`：拦截器名称，被拦截后才有值</li><li>`errorCode`：拦截编码</li><li>`interceptMessage`：拦截原因</li></ul> | - |
| 合规拦截 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#regulatoryBlockFilter` | `下单命中新拦截试算页` | `serviceName:"order" AND message:"下单命中新拦截试算页"` | <ul><li>`ssyPageType`：`8`-试算标识，合规拦截</li></ul> | 合规业务拦截，被拦截后会订单表内落`SINGFAIL`订单，`t_intercept_order_record`和`t_intercept_order`表内都会落数据 |
| 极速模式校验 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#jsModeCheck` | - | - | <ul><li>`isJSmode`：是否极速模式借款，`true`-是，`false`-否</li><li>`isOpenMarketing`：是否勾选尊享卡，`true`-是，`false`-否</li></ul> | <ul><li>如果是极速模式客户下单但未勾选尊享卡，会进行拦截</li><li>订单表内落`SINGFAIL`订单</li><li>发`MQ`通知权益（高晶），可用`sql`查询日志：`serviceName:"order" AND message:"[MQ发送]消息名" AND message:"activity-triggerAction"`</li></ul> |
| 下单业务前置处理 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loanBefore` | - | - | | <ul><li>根据下单入参`loanSourceEnum`字段决定走`自营`前置处理流程还是`API`前置处理流程</li><li>`API`前置处理重点是**下单信息查询组装**业务处理</li><li>`自营`前置处理重点是**下单信息查询组装**，**乐活卡**和**拒就陪**业务处理</li></ul> |
| 下单业务处理 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loanOrder` | - | - | | <ul><li>根据下单入参`loanSourceEnum`字段决定走`自营`处理流程还是`API`处理流程</li><li>`API`主要处理**订单定价**，**API渠道新老客**，**客群标签**，**优惠券（列表）保存**</li><li>`自营`主要处理**订单定价（含KA渠道）**，**重新设定orderExtendType订单类型**，**客群标签**，**优惠券（列表）保存**</li></ul> |
| 下单业务后置处理 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loanAfter` | - | - | | <ul><li>根据下单入参`loanSourceEnum`字段决定走`自营`后置处理流程还是`API`后置处理流程</li><li>`API`主要处理**反欺诈**，**冻结额度**，**会员额度扣除**，**专项提额**，**特殊获额渠道24定价用户处理**，**优惠券处理**，**自营权益**，**渠道权益**，**oppojjapi01渠道撞库（调支付服务）**</li><li>`自营`主要处理**权益包**，**优惠券处理**，**反欺诈**，**冻结额度**，**会员额度扣除**，**专项提额**，**优惠券状态更新**，**下单后通知活动（MQ通知）**</li></ul> |
| 反欺诈 | `com.xhqb.order.biz.service.external.credit.CreditService#loanAntiFraud` | `[借款反欺诈]借款下单反欺诈` | `serviceName:"order" AND message:"[借款反欺诈]借款下单反欺诈"` | <ul><li>`outBizCode`：请求业务ID，可用于后续风控反欺诈MQ结果通知的查询条件</li><li>`afBizCode`：风控返回的业务ID，取的就是查询入参的`outBizCode`</li><li>`success`：风控反欺诈服务调用结果，`true`-调用成功，`false`-调用失败</li></ul> | <ul><li>在 `loanAfter` 中被调用</li><li>**内置手动重试**（可用 `serviceName:"order" AND message:"[借款反欺诈]反欺诈服务调用异常"` 查询）</li><li>**重点强调：这里的反欺诈只是调用风控反欺诈服务，返回的是服务调用是否成功，并不代表反欺诈通过，结果参考下面的`反欺诈结果`行**</li></ul> |
| 反欺诈结果 | `com.xhqb.order.batch.service.AntifraudNoticeConsumer#handleMessage` | `AntifraudNoticeConsumer推进来的消息ID` | `serviceName:"order-batch" AND message:"AntifraudNoticeConsumer推进来的消息ID"` | <ul><li>`antifraudResult`：风控反欺诈返回结果</li></ul> | 消息中字段`antifraudResult`：`PASS`-风控审批通过，`REFUSE`-风控审批拒绝，`CANCEL`-订单取消，主要是这三种状态，如果是其它值可参考这个枚举`com.xhqb.order.common.service.model.enums.AntiFraudResultEnum` |
| 业务异常 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]请求出现业务异常` | `serviceName:"order" AND message:"[借款下单]请求出现业务异常" AND message:"{value}"` | | 提取 ResultEnum、异常 message，定位业务失败根因 |
| 系统错误 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]出现系统错误` | `serviceName:"order" AND message:"[借款下单]出现系统错误"` | | 命中后必须展开 traceId 查堆栈，定位异常根因 |
| 下单结果 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]下单请求结果为` | `serviceName:"order" AND message:"[借款下单]下单请求结果为" AND message:"{value}"` | | 返回对象中如果属性`success`为`true`，说明**下单成功** |

## 关键失败场景

| 现象 | 优先诊断 |
|------|----------|
| 序列到反欺诈停止 | 看反欺诈请求/结果，注意区分首次失败（第1次尝试）vs 重试后仍然失败（第2/3次尝试） |
| 反欺诈服务调用异常（订单变 SINGFAIL） | `LoanTemplate.unifiedLoanAfter()` 调 `creditService.loanAntiFraud()` 返回空或 `sameDevice=false` → 订单置为 **SINGFAIL** 并抛 `BusinessRuntimeException("反欺诈服务调用异常")`。反欺诈内置重试（最多3次，延迟1s/2s），全部失败才会抛异常。排查：搜 WARN 日志 `反欺诈服务调用异常` 看重试是否触发；搜 INFO 结果日志 `第2次尝试` / `第3次尝试` 看最终结果。如果 `CreditService` 完全无日志 → 说明反欺诈路径未被调用（可通过 `message:"credit.CreditService"` 确认） |
| 出现业务异常 | 提取错误码和异常信息 |
| 出现系统错误 | 提取堆栈 |
| `XhCardService.dynamicXhCardView` + `ReCreditService Dubbo超时` | **非下单类最频发ERROR**。`ReCreditService.reCredit` 方法 timeout(10s)，影响 huika card 视图渲染。涉及多个 provider 节点（172.18.26.40 等），每条产生双条 ERROR（XhCardServiceImpl + ProfileFilter）。排查：查 ReCreditService 所在 pod 健康状态，或确认 drools 服务是否降级 |
| `AccountOService - [释放客户冻结额度]异常` | `CreditManagerService.unfreeze` Dubbo 超时。偶发，不影响主流程 |
| 异常日志数 > 入口数但结果全部 SUCCESS | 重试后成功，通常是健康信号。常见来源：**反欺诈重试**（CreditService 内建手动重试，最多3次，WARN日志含 `第N次尝试, Nms后重试`；若重试后成功即继续流程，不抛异常） |

## 健康检查

无具体标识符时，按 `Step 0→1→2→3→4`。**Step 0 是"异常告警"查询的必做步骤**，常规健康检查也建议先执行 Step 0 排除非 [借款下单] 类异常。

Step 0 使用 `level:"ERROR"` 通用查询，不依赖代码锚点，可直接执行。Step 1-3 的中文日志前缀（`[借款下单]下单请求为` 等）依赖代码，首次使用前必须用 `validate_query_anchors.py` 或 grep 本地代码确认锚点仍存在。

| Step | 查询sql | 说明 |
|------|------|------|
| `Step0`：异常告警总览 | `serviceName:"order" AND level:"ERROR"` | 不依赖代码锚点，通用查询，排除非下单类异常 |
| `Step1`：入口量 | `serviceName:"order" AND message:"[借款下单]下单请求为"` | 中文查询，需要浏览器注入 |
| `Step2`：结果状态 | `serviceName:"order" AND message:"[借款下单]下单请求结果为"` | 中文查询，需要浏览器注入 |
| `Step3`：下单异常 | `serviceName:"order" AND (message:"[借款下单]出现系统错误" OR message:"[借款下单]请求出现业务异常")` | 包含`业务异常`和`系统异常`，中文查询，需要浏览器注入 |
| `Step4`：钻取 | `traceId:"{提取到的hex值}"` | 从 Step 0/3 中提取异常 traceId 展开分析 |

输出统计：请求总数、成功数、成功金额、业务异常、系统异常、渠道分布、异常 traceId。

## References

- `references/precheck-passed-but-cant-borrow.md`：预检全部通过但客户仍无法借款的排查指南（含guideCheckAbility vs queryOverdueMark差异、还款计划级别逾期盲区）
- `../xh-log-lookup-sign/SKILL.md`：签约、重签约、协议状态专项排查
- `references/re-sign-troubleshooting-20260519.md`：重签约问题排查记录
- `references/t4-withdrawal-threshold.md`：T4 提现门槛规则说明
- `references/antifraud-retry-mechanism.md`：反欺诈重试机制完整说明（代码、日志锚点、CLS 查询、排查路径）
- `references/order-health-check-examples-20260517.md`：健康检查样例
- `references/order-database-access.md`：测试库 SQL 和状态定义
- `references/contract-data-from-cls.md`：CLS 合同数据提取
- `references/order-status-glossary.md`：订单状态字典
- `references/data-inquiry-fund-decision-tracing.md`：datainquiry 资金决策链路
