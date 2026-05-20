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

| ***意图*** | ***识别特征*** | ***查询策略*** | ***禁止操作*** |
|------|---------|---------|---------|
| 流程追踪 | 下单成功、下单失败、下单失败原因 | 使用入口日志加客户输入信息(如客户id(cid,userId),手机号(mobilePhone,mobileNo),订单号(orderId))定位 traceId，再查全链路 | - |
| 预检通过但无法借款 | 所有预检接口返回canLoan:true/success:true/accessable:1，但客户仍提示无法借款 | ①区分"预检"和"实际下单"——客户可能只查页面没提交订单；②guideCheckAbility的还款计划维度逾期检查（每个还款计划的maxOverdueDays<7）为DEBUG级别CLS不可见；③查h5-loan的queryUserInfo/miniCardInfo看前端状态；④查weixin-h5api的实验配置加载(UserInfoService.getExperimentItem)；⑤查前端业务规则/资方封禁信息(allRefuse/frozenFunds) | 不要只依赖queryCanLoan结果；预检通过≠能下单。guideCheckAbility比queryOverdueMark多一层还款计划级别的逾期检查 |
| 健康检查 | 按提示时间查看ERROR,WARN日志情况,没有时间默认近一天 | 使用健康检查 reference 的 Step 0→A→B→C→D | - |
| **异常告警** | 异常告警情况、ERROR告警、近半小时异常 | 先用 Step 0（level:"ERROR" 总览）捕获所有错误类型，再按 Step C 检查 [借款下单] 业务异常；不要只查 [借款下单] 前缀的异常 | 禁止跳过 Step 0 直接进入 Step C |

## 涉及服务

主服务：`order`。

常见关联：`h5-loan`、`loki`、`datainquiry`、`cif`、`account`、`underwriter`、`magic`、`samus-quality`。

## 首查策略

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| `traceId` / 线程号 | `traceId:"{value}"` | 直接全链路，不加 `serviceName` |
| `orderId` | `serviceName:"order" AND message:"{value}"` | 值搜，不加 `orderId:` 前缀 |
| `cid` | `serviceName:"order" AND message:"{value}"` | 值搜，不加 `cid:` 前缀 |
| `contractNo` | `serviceName:"order" AND message:"{value}"` | 值搜，不加 `contractNo:` 前缀 |
| 手机号 | 先搜手机号定位 cid/orderId | 找不到时问用户补充 cid/orderId |

日志中同一个值可能以 `cid`、`customerId`、`userId`、对象 `toString()` 等形式出现；直接搜值召回率最高。

## 流程追踪入口覆盖

Phase A 查询统一使用 `serviceName:"order" AND ...`，定位 traceId 后 Phase B 用 `traceId:"{traceId}"` 查全链路。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 说明 |
|------|----------|----------------|----------|------|
| 借款能力预检 | `com.xhqb.order.biz.service.impl.OrderServiceImpl#queryOverdueMark` | `queryOverdueMark`、`UserOverDueHisHandler`、`未通过提现门槛` | `serviceName:"order" AND message:"{cid}"` | 值搜优先，再从全文中过滤预检锚点 |
| 自营下单 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]下单请求为` | `serviceName:"order" AND message:"[借款下单]下单请求为" AND message:"{值}"` | 校验通过后作为 Phase A 入口 |
| 下单拦截 | `com.xhqb.order.biz.service.impl.loan.LoanTemplate#loan` | `[借款下单]下单拦截请求` | `serviceName:"order" AND message:"[借款下单]下单拦截请求" AND message:"{值}"` | 入口在模板方法，具体实现可能在 H5/API 子类 |
| 下单结果 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]下单请求结果为` | `serviceName:"order" AND message:"[借款下单]下单请求结果为" AND message:"{值}"` | 和自营下单同一方法入口 |
| 业务异常 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]请求出现业务异常` | `serviceName:"order" AND message:"[借款下单]请求出现业务异常" AND message:"{值}"` | 提取 ResultEnum、异常 message |
| 系统错误 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `[借款下单]出现系统错误` | `serviceName:"order" AND message:"[借款下单]出现系统错误"` | 命中后必须展开 traceId 查堆栈 |
| 反欺诈 | `com.xhqb.order.biz.service.external.credit.CreditService#loanAntiFraud` | `[借款反欺诈]借款下单反欺诈` | `serviceName:"order" AND message:"借款下单反欺诈" AND message:"{值}"` | 代码锚点含 `[借款反欺诈]`。**内置手动重试**（`retryDelays={1000,2000}`，最多 3 次尝试）。INFO 结果日志含 `第N次尝试` 标记当前尝试次数（`第1次`=首次, `第2次`=第1次重试, `第3次`=第2次重试）。WARN 日志含 `反欺诈服务调用异常, outBizId=xxx, 第N次尝试, Nms后重试`。也可用 `message:"credit.CreditService"` ASCII 查询（logger 缩写 `c.x.o.b.s.e.credit.CreditService`）验证 |
| 资金路由 | `com.xhqb.order.biz.service.impl.LoanOrderServiceImpl#loanOrder` | `[资金路由]`、`[资金自动路由]` | `serviceName:"order" AND message:"[资金路由]" AND message:"{值}"` | 自动路由场景可把锚点换成 `[资金自动路由]` |
| API 借款试算 | `com.xhqb.order.biz.service.impl.repayment.ApiRepaymentTrialImpl#trial` | `[借款试算]` | `serviceName:"order" AND message:"[借款试算]" AND message:"{值}"` | 先确认 API 试算入口仍在 order |
| 借款能力预检结果(queryCanLoan) | com.xhqb.order.common.service.loan.LoanService#queryCanLoan（Dubbo接口） | queryStatus.loanCheckResults | serviceName:order AND message:queryStatus.loanCheckResults AND message:{cid} | ASCII可查。返回格式: {canLoan:true/false, success:true/false}。查不到时去h5-loan/h5-audit反查 |
| 资方冻结检查 | com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanCheck | underFrozenCheck | serviceName:order AND message:underFrozenCheck AND message:{cid} | INFO级别提示。日志: LoanController underFrozenCheck 某个可用资金方未在冻结表里。不阻断流程 |
| 解H | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#releaseHoldOrder` | `[新解H]` | `serviceName:\"order\" AND message:\"[新解H]\" AND message:\"{值}\"` | 具体订单处理在私有方法，先用 job 入口锚定 |

## 关键失败模式

| 现象 | 优先诊断 |
|------|----------|
| 您存在不良借款记录，无法借款 | T4 提现门槛拦截。查 `queryOverdueMark`、`UserOverDueHisHandler`、`未通过提现门槛` |
| 您有借款已逾期噢 | 当前逾期拦截。查 `orderLocalService.getUserOverDueMark()` |
| 一直提示重新签约 | 交给 `xh-log-lookup-sign`，该场景需要同时看 RESIGN、协议失效、还款失败和全渠道禁闭 |
| 序列到拦截步骤停止 | 看拦截条件和 checkCode |
| 序列到反欺诈停止 | 看反欺诈请求/结果，注意区分首次失败（第1次尝试）vs 重试后仍然失败（第2/3次尝试） |
| 反欺诈服务调用异常（订单变 SINGFAIL） | `LoanTemplate.unifiedLoanAfter()` 调 `creditService.loanAntiFraud()` 返回空或 `sameDevice=false` → 订单置为 **SINGFAIL** 并抛 `BusinessRuntimeException("反欺诈服务调用异常")`。反欺诈内置重试（最多3次，延迟1s/2s），全部失败才会抛异常。排查：搜 WARN 日志 `反欺诈服务调用异常` 看重试是否触发；搜 INFO 结果日志 `第2次尝试` / `第3次尝试` 看最终结果。如果 `CreditService` 完全无日志 → 说明反欺诈路径未被调用（可通过 `message:"credit.CreditService"` 确认） |
| 反欺诈拒绝导致 api-order-change-notice 重复发送 | `LoanOrderServiceImpl#antiFraudConfirm` 反欺诈拒绝（LOAN_REFUSE）时，`api-order-change-notice` MQ 会被发送 **两次**（`orderChangeNotice-1` 和 `orderChangeNotice-2` 两个异步线程）。同一下单链路内两条独立 LOAN_FAIL 通知路径重叠：**路径A**: `antiFraudConfirm` → `orderOthersService.loanRefuseReasonDeal()` (line 419, ALL_REFUSE 判断) → `publishEvent(LOAN_FAIL)` with `loanFailReason=ALL_FUND_REFUSE`；**路径B**: `antiFraudConfirm` → `handleReject()` → `singFailNotify()` (line 2286) → `loanFailNoticePartner()` → `publishEvent(LOAN_FAIL)` without `loanFailReason`。可通过 `message:"api-order-change-notice" AND message:"{orderId}"` 验证两条 MQ 的 `loanFailReason` 不同（一个有值一个 null）。这是代码设计上的通知路径重叠，非偶发问题。其他通知类型（SMS、App推送、活动触发）不受影响 |
| 出现业务异常 | 提取错误码和异常信息 |
| 出现系统错误 | 提取堆栈 |
| `[资金路由]查询订单定价为null` | 定价异常 |
| `[资金自动路由]被xx借款渠道拒绝` | 资方拒绝，确认是否重新分配 |
| `XhCardService.dynamicXhCardView` + `ReCreditService Dubbo超时` | **非下单类最频发ERROR**。`ReCreditService.reCredit` 方法 timeout(10s)，影响 huika card 视图渲染。涉及多个 provider 节点（172.18.26.40 等），每条产生双条 ERROR（XhCardServiceImpl + ProfileFilter）。排查：查 ReCreditService 所在 pod 健康状态，或确认 drools 服务是否降级 |
| `[协议共享]根据身份证查询CID失败` | `SharingAgreementServiceImpl` 持续报错，多个身份证号均查不到 CID。不是偶发问题，需确认数据源或缓存同步状态 |
| `AccountOService - [释放客户冻结额度]异常` | `CreditManagerService.unfreeze` Dubbo 超时。偶发，不影响主流程 |
| `[借款试算]api借款还款计划试算请求参数不对` | 优先检查 apiCheck 四条件和 `EmbeddedPartnerEnum` 部署版本 |
| 异常日志数 > 入口数但结果全部 SUCCESS | 重试后成功，通常是健康信号。常见来源：**反欺诈重试**（CreditService 内建手动重试，最多3次，WARN日志含 `第N次尝试, Nms后重试`；若重试后成功即继续流程，不抛异常） |
| `queryOverdueMark` 拦截但 `guideCheckAbility` success | 两接口语义不同，以 `queryOverdueMark` 为准 |
| 预检全部通过(canLoan:true/T4通过)但客户仍无法借款 | **关键盲区检查**：①`guideCheckAbility`比`queryOverdueMark`多一层还款计划级别逾期检查（`orderRepayplanMapper.queryMaxOverdueDays(orderIdList)`，maxOverdueDays<7拦截），该检查为DEBUG级别CLS不采集 → 合同状态REPAYING+逾期0天不代表每个还款计划都没近7天逾期；②查h5-loan的miniCardInfo中资方封禁信息(frozenFunds)和allRefuse字段；③查weixin-h5api的getExperimentItem Dubbo超时(实验配置加载失败可能导致借款入口异常)；④确认客户有实际提交订单而非仅查看页面 |

## 存量状态查询

用户问“这个 cid 有多少笔未结清合同/名下有哪些在还合同时”，不要使用入口覆盖表。流程：

1. grep 代码找打印合同状态的日志：`contractNoState`、`orderStatus`、`accountStatus`、`isNotSettle`、`REPAYING`、`OVERDUE`。
2. 用代码中确认的日志模式 + cid 值查 CLS；没有明确前缀时退回 `serviceName:"order" AND message:"{cid}"`。
3. 用主控 `cls_query.py` 加载更多并提取全文。
4. 从全文解析 CK/CS 合同号和状态字段。
5. 说明限制：CLS 只反映日志范围内出现过的合同；30 天内无活动的存量合同可能不会出现。

状态定义：

- 未结清列表：`order_status IN ('REPAYING','OVERDUE')`
- 未结清计数排除：`REPAYED`、`REFUNDSETTLED`、`SETTLED`、`EARLY_REPAYED`、`CANCEL`、`FAIL`、`SINGFAIL`、`LOAN_REFUSE`

完整 SQL 和实操细节见 references。

## 健康检查

无具体标识符时，按 Step 0→A→B→C→D。**Step 0 是"异常告警"查询的必做步骤**，常规健康检查也建议先执行 Step 0 排除非 [借款下单] 类异常。

Step 0 使用 `level:"ERROR"` 通用查询，不依赖代码锚点，可直接执行。Step A/B/C 的中文日志前缀（`[借款下单]下单请求为` 等）依赖代码，首次使用前必须用 `validate_query_anchors.py` 或 grep 本地代码确认锚点仍存在。

| Step | 查询sql | 说明 |
|------|------|------|
| ***step1:ERROR总览*** | `serviceName:"order" AND level:"ERROR"` | ⚠️ 必做。捕获所有 ERROR 日志，不限于 [借款下单] 前缀。避免漏掉 ReCreditService 超时、协议共享CID查询失败、AccountOService 异常等非下单类错误 |
| A 入口量 | `serviceName:"order" AND message:"[借款下单]下单请求为"` | 中文查询，需要浏览器注入 |
| B 结果状态 | `serviceName:"order" AND message:"[借款下单]下单请求结果为"` | 中文查询，需要浏览器注入 |
| C 异常 | `serviceName:"order" AND (message:"[借款下单]出现系统错误" OR message:"[借款下单]请求出现业务异常")` | 中文查询，需要浏览器注入 |
| D 钻取 | `traceId:"{提取到的hex值}"` | 从 Step 0/C 中提取异常 traceId 展开分析 |

输出统计：请求总数、成功数、成功金额、**非下单类ERROR（Step 0）**、业务异常、系统错误、渠道分布、异常 traceId。

## References

- `references/precheck-passed-but-cant-borrow.md`：预检全部通过但客户仍无法借款的排查指南（含guideCheckAbility vs queryOverdueMark差异、还款计划级别逾期盲区）
- `references/order-detailed-workflows.md`：本文件重构前的完整订单排障细节
- `../xh-log-lookup-sign/SKILL.md`：签约、重签约、协议状态专项排查
- `references/antifraud-retry-mechanism.md`：反欺诈重试机制完整说明（代码、日志锚点、CLS 查询、排查路径）
- `references/order-health-check-examples-20260517.md`：健康检查样例
- `references/order-database-access.md`：测试库 SQL 和状态定义
- `references/contract-data-from-cls.md`：CLS 合同数据提取
- `references/order-status-glossary.md`：订单状态字典
- `references/data-inquiry-fund-decision-tracing.md`：datainquiry 资金决策链路
