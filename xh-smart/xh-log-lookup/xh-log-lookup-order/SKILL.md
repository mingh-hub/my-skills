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

订单模块子 Skill 只提供入口、首查策略和关键失败模式。CLS 执行、加载更多、飞书卡片输出统一交给 `xh-log-lookup` 主控工具。

## 意图分类

| 意图 | 识别特征 | 查询策略 | 禁止操作 |
|------|---------|---------|---------|
| 流程追踪 | 下单成功、下单失败、下单失败原因 | 使用入口日志加客户输入信息(如客户id(`cid`，`userId`)，手机号(`mobilePhone`，`mobileNo`)，订单号(orderId))定位 traceId，再查全链路 | - |
| 健康检查 | 按提示时间查看INFO、ERROR、WARN日志情况，没有时间默认近一天 | 使用健康检查 reference 的 Step 0→A→B→C→D | - |
| **异常告警** | 异常告警情况、ERROR告警、近1小时异常 | 先用 `level:"ERROR"` 捕获系统异常，再结合`LoanOrderResult`对象中字段`success`的值为`false`捕获业务异常 |

## 涉及服务

主服务：`order`。

常见关联：`h5-loan`、`loki-webapp`、`datainquiry`、`cif`、`account`、`underwriter`、`magic`、`member`。

## 首查策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| `traceId` / `线程号` | `traceId:"{value}"` | 直接全链路，不加 `serviceName` |
| `orderId` / `订单号` | `serviceName:"order" AND message:"{value}"` | 值搜，不加 `orderId:` 前缀 |
| `cid` / `客户id` | `serviceName:"order" AND message:"{value}"` | 值搜，不加 `cid:` 前缀 |
| `contractNo` / `合同号` | `serviceName:"order" AND message:"{value}"` | 值搜，不加 `contractNo:` 前缀 |
| `mobilePhone` / `手机号` | 根据手机号定位 `cid`/`orderId` | 找不到时问用户补充 `cid`/`orderId` |
| `identityNo` / `身份证号` | 根据身份证号定位 `cid`/`orderId` | 找不到时问用户补充 `cid`/`orderId` |

手机号、身份证号查询可能无法查到准确信息，可以通过日志查询将手机号、身份证号转成客户`cid`再查；
日志中同一个值可能以 `cid`、`customerId`、`userId`、对象 `toString()` 等形式出现；直接搜值召回率最高。

## 流程追踪入口

Phase A 查询统一使用 `serviceName:"order" AND ...` 定位 `traceId` 
Phase B 用 `traceId:"{traceId}"` 查全链路。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 说明 |
|------|----------|----------------|----------|------|
| 下单请求 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]下单请求为` | `serviceName:"order" AND message:"[借款下单]下单请求为" AND message:"{value}"` | 校验通过后作为 Phase A 入口。相关 WARN 锚点：`[借款下单]出现并发请求`（Redis 锁拦截）、`[借款下单]请求参数有误`，业务模式通过入参字段`loanSourceEnum`来区分，`API：api借款流程，SELF_SUPPORT：自营借款流程` |
| 下单核心 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loan` | - | - | **下单核心流程总控，包含流程：`下单拦截`、``、``、``、``** |
| 下单拦截 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanCheck` | `[借款校验]进入` | `serviceName:order AND message:"[借款校验]进入"` | **下单核心流程之一** |
| 下单拦截结果 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loan` | `[借款下单]下单拦截请求` | `serviceName:order AND message:"[借款下单]下单拦截请求"` | 区分下单拦截结果，`intercept=false`：未拦截；`intercept=true`：拦截，`interceptFilter`：拦截器，`interceptMessage`：拦截原因，`errorCode`：下单失败code |
| 合规拦截 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#regulatoryBlockFilter` | `下单命中新拦截试算页` | `serviceName:order AND message:"下单命中新拦截试算页"` | 合规业务拦截 |
| 反欺诈 | `com.xhqb.order.biz.service.external.credit.CreditService#loanAntiFraud` | `[借款反欺诈]借款下单反欺诈` | `serviceName:"order" AND message:"借款下单反欺诈" AND message:"{value}"` | 代码锚点含 `[借款反欺诈]`。**内置手动重试**（可用 `message:"com.xhqb.order.biz.service.external.credit.CreditService"`查询，**重点强调：这里的反欺诈只是调用风控反欺诈服务，返回的是服务调用是否成功，并不代表反欺诈通过，结果参考下面的`反欺诈结果`行** |
| 反欺诈结果 | `com.xhqb.order.batch.service.AntifraudNoticeConsumer#handleMessage` | `AntifraudNoticeConsumer推进来的消息ID` | `serviceName:"order-batch" AND message:"AntifraudNoticeConsumer推进来的消息ID"` | 消息中字段`antifraudResult`:`PASS`-风控审批通过，`REFUSE`-风控审批拒绝，其它值可参考这个枚举`com.xhqb.order.common.service.model.enums.AntiFraudResultEnum` |
| 业务异常 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]请求出现业务异常` | `serviceName:"order" AND message:"[借款下单]请求出现业务异常" AND message:"{value}"` | 提取 ResultEnum、异常 message，定位业务失败根因 |
| 系统错误 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]出现系统错误` | `serviceName:"order" AND message:"[借款下单]出现系统错误"` | 命中后必须展开 traceId 查堆栈，定位异常根因 |
| 下单结果 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]下单请求结果为` | `serviceName:"order" AND message:"[借款下单]下单请求结果为" AND message:"{value}"` | 返回对象中如果属性`success`为`true`，说明**下单成功** |

## 关键失败场景

| 现象 | 优先诊断 |
|------|----------|
| 您存在不良借款记录，无法借款 | T4 提现门槛拦截。查 `未通过提现门槛`、`UserOverDueHisHandler`、`queryOverdueMark` |
| 您有借款已逾期噢 | 当前逾期拦截。查 `orderLocalService.getUserOverDueMark()` |
| 一直提示重新签约 | 交给 `xh-log-lookup-sign`，该场景需要同时看 RESIGN、协议失效、还款失败和全渠道禁闭 |
| 序列到拦截步骤停止 | 看拦截条件和 checkCode |
| 序列到反欺诈停止 | 看反欺诈请求/结果，注意区分首次失败（第1次尝试）vs 重试后仍然失败（第2/3次尝试） |
| 反欺诈服务调用异常（订单变 SINGFAIL） | `LoanTemplate.unifiedLoanAfter()` 调 `creditService.loanAntiFraud()` 返回空或 `sameDevice=false` → 订单置为 **SINGFAIL** 并抛 `BusinessRuntimeException("反欺诈服务调用异常")`。反欺诈内置重试（最多3次，延迟1s/2s），全部失败才会抛异常。排查：搜 WARN 日志 `反欺诈服务调用异常` 看重试是否触发；搜 INFO 结果日志 `第2次尝试` / `第3次尝试` 看最终结果。如果 `CreditService` 完全无日志 → 说明反欺诈路径未被调用（可通过 `message:"credit.CreditService"` 确认） |
| 反欺诈拒绝导致 api-order-change-notice 重复发送 | `LoanOrderServiceImpl#antiFraudConfirm` 反欺诈拒绝（LOAN_REFUSE）时，`api-order-change-notice` MQ 会被发送 **两次**（`orderChangeNotice-1` 和 `orderChangeNotice-2` 两个异步线程）。同一下单链路内两条独立 LOAN_FAIL 通知路径重叠：**路径A**: `antiFraudConfirm` → `orderOthersService.loanRefuseReasonDeal()` (line 419, ALL_REFUSE 判断) → `publishEvent(LOAN_FAIL)` with `loanFailReason=ALL_FUND_REFUSE`；**路径B**: `antiFraudConfirm` → `handleReject()` → `singFailNotify()` (line 2286) → `loanFailNoticePartner()` → `publishEvent(LOAN_FAIL)` without `loanFailReason`。可通过 `message:"api-order-change-notice" AND message:"{orderId}"` 验证两条 MQ 的 `loanFailReason` 不同（一个有值一个 null）。这是代码设计上的通知路径重叠，非偶发问题。其他通知类型（SMS、App推送、活动触发）不受影响 |
| 出现业务异常 | 提取错误码和异常信息 |
| 出现系统错误 | 提取堆栈 |
| `[资金路由]查询订单定价为null` | 定价异常 |
| `XhCardService.dynamicXhCardView` + `ReCreditService Dubbo超时` | **非下单类最频发ERROR**。`ReCreditService.reCredit` 方法 timeout(10s)，影响 huika card 视图渲染。涉及多个 provider 节点（172.18.26.40 等），每条产生双条 ERROR（XhCardServiceImpl + ProfileFilter）。排查：查 ReCreditService 所在 pod 健康状态，或确认 drools 服务是否降级 |
| `[协议共享]根据身份证查询CID失败` | `SharingAgreementServiceImpl` 持续报错，多个身份证号均查不到 CID。不是偶发问题，需确认数据源或缓存同步状态 |
| `AccountOService - [释放客户冻结额度]异常` | `CreditManagerService.unfreeze` Dubbo 超时。偶发，不影响主流程 |
| `[借款试算]api借款还款计划试算请求参数不对` | 优先检查 apiCheck 四条件和 `EmbeddedPartnerEnum` 部署版本 |
| 异常日志数 > 入口数但结果全部 SUCCESS | 重试后成功，通常是健康信号。常见来源：**反欺诈重试**（CreditService 内建手动重试，最多3次，WARN日志含 `第N次尝试, Nms后重试`；若重试后成功即继续流程，不抛异常） |

## 健康检查

无具体标识符时，按 Step 0→A→B→C→D。**Step 0 是"异常告警"查询的必做步骤**，常规健康检查也建议先执行 Step 0 排除非 [借款下单] 类异常。

Step 0 使用 `level:"ERROR"` 通用查询，不依赖代码锚点，可直接执行。Step A/B/C 的中文日志前缀（`[借款下单]下单请求为` 等）依赖代码，首次使用前必须用 `validate_query_anchors.py` 或 grep 本地代码确认锚点仍存在。

| Step | 查询sql | 说明 |
|------|------|------|
| step1：借款下单异常总览 | `serviceName:"order" AND (message:"[借款下单]出现系统错误" OR message:"[借款下单]请求出现业务异常")` | 包含`业务异常`和`系统异常` |
| A 入口量 | `serviceName:"order" AND message:"[借款下单]下单请求为"` | 中文查询，需要浏览器注入 |
| B 结果状态 | `serviceName:"order" AND message:"[借款下单]下单请求结果为"` | 中文查询，需要浏览器注入 |
| C 异常 | `serviceName:"order" AND (message:"[借款下单]出现系统错误" OR message:"[借款下单]请求出现业务异常")` | 中文查询，需要浏览器注入 |
| D 钻取 | `traceId:"{提取到的hex值}"` | 从 Step 0/C 中提取异常 traceId 展开分析 |

输出统计：请求总数、成功数、成功金额、**非下单类ERROR（Step 0）**、业务异常、系统错误、渠道分布、异常 traceId。

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
