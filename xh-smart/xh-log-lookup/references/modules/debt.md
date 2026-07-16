# 债转日志查询

债转模块只梳理账务债转成功后通知订单系统的链路：账务发送 MQ，`order-batch` 消费后按债转类型处理协议事件，并在需要时调用 `order` 同步订单、还款计划和费用。CLS 执行、分页完整性和飞书卡片输出统一交给 `xh-log-lookup` 主控。

## 涉及服务

- 主服务：`order-batch`、`order`。
- 上游边界：`账务系统` 完成债转并发送 MQ；本模块不据订单侧日志反推账务内部债转是否执行成功。
- 关联服务：`protocol`（代偿、回购、债转完成事件）、账务查询服务（`order` 同步时查询最新账户、还款计划和费项）。

## 意图边界

- 用户说`债转`、`债权转让`、`合同债转`、`债转成功通知`、`期供代偿`、`债转回购`、`债转短信`时，走本模块。
- 用户只说`扣款`、`还款`、`代扣`、`结清`、`还款失败`且没有明确债转语义时，走 `references/modules/repay.md`。
- 本模块入口是账务债转成功后的订单侧通知，不覆盖账务侧债转发起、执行和落账过程。
- `AccountDebtTransferConsumer` 收到消息后存在提前返回分支。收到 MQ 不等于 order 侧处理完成，协议事件日志不等于订单数据已同步。

## 业务入口与查询主键

订单侧入口：`com.xhqb.order.batch.service.AccountDebtTransferConsumer#consume`。

MQ topic：`account-credit-transfer`。

`contractNo` 是默认且主要的查询主键，但合同号查询只用于定位入口，不是链路查询终点。本文所称“债转短信入口”，指包含完整 MQ 消息体的 `AccountDebtTransferConsumer推进来的消息ID及消息内容:` 日志。只有用户明确提供 `traceId` 时，才直接执行 `traceId:"{value}"`，不拼 `serviceName`。

标准定位顺序：

1. 如果只提供 `orderId`，先根据订单号查询并提取 `contractNo`：`serviceName:"order" AND message:"{orderId}"`。
2. 用 `contractNo` 定位债转短信入口：`serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:" AND message:"{contractNo}"`。
3. 从入口日志提取 `traceId`，再查询整个链路日志：`traceId:"{value}"`。

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| `contractNo` | `serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:" AND message:"{contractNo}"` | 定位债转短信入口并提取 `traceId`，随后用 traceId 查询整个链路 |
| `traceId` | `traceId:"{value}"` | 全链路直查，不加 `serviceName` |
| `orderId` | `serviceName:"order" AND message:"{orderId}"` | 先从订单日志提取 `contractNo`，再按合同号定位债转短信入口并提取 `traceId` |
| `messageId` | `serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:" AND message:"{messageId}"` | 已知 MQ messageId 时使用 |

## MQ 消息关键字段

| 字段 | 含义 | 排查用途 |
|------|------|---------|
| `contractNo` | 合同号 | 主查询键，关联 `order-batch` 与 `order` |
| `originalAccountId` | 债转前合同号 | 一次债转时，`contractNo` 与 `originalAccountId` 相同 |
| `currentAccountId` | 债转后合同号 | `currentAccountId` 以 `ZC` 开头表示一次债转，以 `ZZC` 开头表示二次债转 |
| `originalChannel` | 债转前渠道编码 | 判断债转前所属渠道及协议回购分支 |
| `currentChannel` | 债转后（当前）渠道编码 | 判断当前渠道及债转完成事件分支 |
| `originalPlanCode` | 债转前资金计划编码 | 协议事件使用的原资金计划 |
| `currentPlanCode` | 债转后（当前）资金计划编码 | 短信记录和订单同步使用的当前资金计划 |
| `billNo` | 借据号 | 关联账务借据和债转记录 |
| `productClass` | 业务类型 | 非空且不等于 `sunflower` 时，消费入口记录日志后直接返回 |
| `claimType` | 债转类型 | `PERIOD`-期供代偿；`CONTRACT`-合同债转回购 |
| `periodNum` | 代偿期数 | `claimType=PERIOD` 时区分最后一期代偿和普通期供代偿 |
| `transferType` | 转换类型 | `ORIGINAL`-现状分配；`REPO`-回购 |
| `transferDate` | 债转日期 | 毫秒时间戳，传入 `syncRepaySingleOrder` 和债转短信逻辑 |
| `repoAmount` | 资方回购金额 | 有值时传入订单侧债转短信逻辑 |

### 生产 MQ 报文示例

#### 一次债转报文

```text
2026-07-16 19:23:11,483 [- -] [-/-/-/- - -] [pulsar-external-listener-5-1] INFO  c.x.o.b.s.AccountDebtTransferConsumer - AccountDebtTransferConsumer推进来的消息ID及消息内容:101000448:176:1, {"contractNo":"CK202511090008653","originalAccountId":"CK202511090008653","currentAccountId":"ZCK202511090008653","originalChannel":"SN_RS","originalPlanCode":"SN_RS_002","currentChannel":"ctcf","currentPlanCode":"dcrd_snrs021","productClass":"sunflower","claimType":"CONTRACT","periodNum":0,"transferType":"REPO","billNo":"DU2511090066796266","transferDate":1774608161000}
```

该报文中 `contractNo=originalAccountId`，且 `currentAccountId=ZCK202511090008653` 以 `ZC` 开头，因此属于一次债转；当前渠道为 `ctcf`，当前资金计划为 `dcrd_snrs021`，业务类型为合同债转回购。

#### 二次债转报文

```json
{"contractNo":"CK202508110000003","originalAccountId":"ZCK202508110000003","currentAccountId":"ZZCK202508110000003","originalChannel":"dcrd","originalPlanCode":"dcrd_zbhp021","currentChannel":"ctcf","currentPlanCode":"ctcf_zbyhhp02","productClass":"sunflower","claimType":"CONTRACT","periodNum":0,"transferType":"REPO","billNo":"10401000093855083","transferDate":1783505100000}
```

该报文中 `contractNo` 仍是原始合同号，`originalAccountId=ZCK202508110000003` 是一次债转后的合同号，`currentAccountId=ZZCK202508110000003` 以 `ZZC` 开头，因此属于二次债转；渠道由 `dcrd` 转为 `ctcf`，资金计划由 `dcrd_zbhp021` 转为 `ctcf_zbyhhp02`。

## 首查策略

1. 用户明确提供 `traceId` 时，直接按 traceId 查询整个链路。
2. 用户只提供 `orderId` 时，先查询 `serviceName:"order" AND message:"{orderId}"`，从订单日志提取 `contractNo`。
3. 用 `contractNo` 查询 `order-batch` 债转短信入口，确认消息是否到达，并从完整消息日志提取 `traceId`、`claimType`、`periodNum`、渠道、计划和 messageId。
4. 使用提取到的 `traceId` 查询整个链路；入口日志没有 traceId 或跨服务 trace 断开时，再用 `contractNo` 分别补查 `order-batch` 和 `order`。
5. 先根据消息字段判断代码分支：`claimType=PERIOD` 时以协议事件分支为终点；`claimType=CONTRACT` 或未进入 PERIOD 分支时，再追 `saveOrderOverdueTransferMsgLog` 和 `syncRepaySingleOrder`。
6. 结论必须区分“MQ 已收到”“协议事件已触发”“订单同步已执行”“订单数据已更新”，不得用前置节点替代后置完成结论。

## 条件下沉示例

| 用户意图 | 首查 SQL | 后续分析 |
|---------|---------|---------|
| 指定合同债转进度 | `serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:" AND message:"{contractNo}"` | 定位债转短信入口、提取 traceId，再按 traceId 查询整个链路 |
| 指定订单债转进度 | `serviceName:"order" AND message:"{orderId}"` | 先提取 contractNo，再按合同号定位债转短信入口和 traceId |
| 债转消费异常 | `serviceName:"order-batch" AND level:"ERROR" AND message:"AccountDebtTransferConsumer consume error."` | 展开 traceId 查异常堆栈；确认异常发生在协议事件、短信日志还是订单同步调用 |
| 债转短信日志落库失败 | `serviceName:"order-batch" AND level:"ERROR" AND message:"合同债转sms日志落库失败" AND message:"{contractNo}"` | 该失败不会阻止后续 `syncRepaySingleOrder`，继续检查订单同步 |
| order 同步并发 | `serviceName:"order" AND message:"[syncRepaySingleOrder]出现并发请求:" AND message:"{contractNo}"` | `transferType` 非空时会发送 5 秒延迟同步消息；继续查后续同步日志 |
| order 查询账务结果 | `serviceName:"order" AND message:"同步单个订单还款状态,查询中腾信账务信息,ztxAccountInfo:" AND message:"{contractNo}"` | 核对最新账户状态、合同状态、计划和费项 |
| order 债转同步结果 | `serviceName:"order" AND message:"更新订单信息," AND message:"{contractNo}"` | 核对订单状态、账户状态和计划更新；必要时展开 traceId |

## 核心流程链路追踪模版

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| MQ 入口 | `AccountDebtTransferConsumer#consume` | `AccountDebtTransferConsumer推进来的消息ID及消息内容:` | `serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:" AND message:"{contractNo}"` | `messageId`、`contractNo`、`claimType`、`periodNum`、债转前后渠道和计划 | 账务债转成功通知进入订单系统的首个强信号 |
| 最后一期代偿事件 | `AccountDebtTransferConsumer#consume` | `通知protocol最后一期代偿成功事件开始` | `serviceName:"order-batch" AND message:"通知protocol最后一期代偿成功事件开始"` | `claimType=PERIOD`、`periodNum=applyStagesNbr` | 异步通知协议服务，提交任务后消费主线程提前返回 |
| 普通期供代偿事件 | `AccountDebtTransferConsumer#consume` | `通知protocol代偿成功事件开始` | `serviceName:"order-batch" AND message:"通知protocol代偿成功事件开始"` | `claimType=PERIOD`、`periodNum!=applyStagesNbr` | 异步通知协议服务，提交任务后消费主线程提前返回 |
| 合同回购事件 | `AccountDebtTransferConsumer#consume` | `通知protocol回购成功事件开始` | `serviceName:"order-batch" AND message:"通知protocol回购成功事件开始"` | `claimType=CONTRACT`、`originalChannel!=dcrd` | 异步事件，不阻塞后续订单同步 |
| 合同债转完成事件 | `AccountDebtTransferConsumer#consume` | `通知protocol债转成功事件开始` | `serviceName:"order-batch" AND message:"通知protocol债转成功事件开始"` | `claimType=CONTRACT`、`currentChannel=ctcf/zyx` | 异步事件，不阻塞后续订单同步 |
| 短信监控记录 | `AccountDebtTransferConsumer#consume` | `合同债转sms日志落库失败` | `serviceName:"order-batch" AND level:"ERROR" AND message:"合同债转sms日志落库失败" AND message:"{contractNo}"` | `currentPlanCode`、`actionStep=INIT` | 调用 `RepayOrderServiceImpl#saveOrderOverdueTransferMsgLog`；失败只记录 ERROR，仍继续同步订单 |
| 同步单笔订单 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#syncRepaySingleOrder` | `[syncRepaySingleOrder]出现并发请求:` | `serviceName:"order" AND message:"[syncRepaySingleOrder]出现并发请求:" AND message:"{contractNo}"` | `contractNo`、`transferType` | 并发时直接返回成功；`transferType` 非空会发送 5 秒延迟同步消息 |
| 查询账务最新信息 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#syncRepaySingleOrder` | `同步单个订单还款状态,查询中腾信账务信息,ztxAccountInfo:` | `serviceName:"order" AND message:"同步单个订单还款状态,查询中腾信账务信息,ztxAccountInfo:" AND message:"{contractNo}"` | 账户状态、合同状态、还款计划、费项 | 订单侧以账务查询结果为准刷新本地数据 |
| 同步理赔账户 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#syncClaimsAccountInfo` | `RepayOrderServiceImpl syncClaimsAccountInfo outBizCode is` | `serviceName:"order" AND message:"RepayOrderServiceImpl syncClaimsAccountInfo outBizCode is" AND message:"{contractNo}"` | `outBizCode`、订单对象、账务对象、`syncType` | 账户状态非 NORMAL 时进入，债转通常走该分支 |
| 债转短信 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#sendSmsIfDebtTransfer` | `sendSmsIfDebtTransfer invoked start` | `serviceName:"order" AND message:"sendSmsIfDebtTransfer invoked start"` | `businessGroup`、`outBizCode` | 是否真正发送还受账户号、资金计划和配置控制 |
| 还款计划合并 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#syncClaimsAccountInfo` | `[同步还款]账务债转合并为一期` | `serviceName:"order" AND message:"[同步还款]账务债转合并为一期" AND message:"{orderId}"` | 本地待处理期数、账务期数 | 账务只剩一期且本地多期时，先失效本地未处理计划再插入/同步最新计划 |
| 更新订单 | `com.xhqb.order.biz.service.impl.RepayOrderServiceImpl#updateOrderAndBackTransferInfo` | `更新订单信息,` | `serviceName:"order" AND message:"更新订单信息," AND message:"{contractNo}"` | `orderStatus`、`accountStatus`、`settleDate` | 订单侧数据更新的主要完成信号，并将已有 `OrderBackTransfer` 记录置为 `done` |
| 消费异常 | `AccountDebtTransferConsumer#consume` | `AccountDebtTransferConsumer consume error.` | `serviceName:"order-batch" AND level:"ERROR" AND message:"AccountDebtTransferConsumer consume error."` | traceId、异常堆栈 | 外层捕获异常后只记录 ERROR；命中后必须确认后续是否有补偿或人工重放 |

## 分支判定

### 业务类型过滤

`productClass` 非空且不等于 `sunflower` 时，入口日志已经打印，但消费者随后直接返回。此场景不能判定为“消费后丢失”，应先核对业务类型。

### 期供代偿

- `claimType=PERIOD` 且 `periodNum=applyStagesNbr`：异步触发最后一期代偿成功事件。
- `claimType=PERIOD` 且 `periodNum!=applyStagesNbr`：异步触发普通期供代偿成功事件。
- 两个 PERIOD 分支都会在提交异步协议事件后提前 `return`，因此不会继续保存债转短信日志，也不会调用 `syncRepaySingleOrder`。PERIOD 分支会提前 `return` 是预期行为。

### 合同债转回购

- `claimType=CONTRACT` 且 `originalChannel!=dcrd`：异步触发协议回购成功事件。
- `claimType=CONTRACT` 且 `currentChannel=ctcf/zyx`：异步触发协议债转成功事件。
- 两个判断相互独立，可能同时触发；之后仍继续保存短信监控记录并调用 `order` 同步。
- `originalChannel=dcrd` 时不触发回购成功事件，但不代表主链停止；继续检查债转完成事件和订单同步。

## order 侧同步逻辑

`AccountDebtTransferConsumer` 组装 `SyncInfoRequest`，传入 `contractNo`、`transferType`、`currentAccountId`、`currentPlanCode`、当天 `tranDate`，以及可选的 `transferDate`、`repoAmount`。

`RepayOrderServiceImpl#syncRepaySingleOrder` 的主要处理顺序：

1. 校验 `contractNo` 和 `tranDate`，按合同号获取 Redis 并发锁。
2. 未传 `orderId` 时按 `contractNo` 查询订单；订单不存在时记录“同步单个订单还款状态,订单...合同...不存在”并返回 `NO_DATA_FOUND`。
3. 仅处理 `REPAYING`、`OVERDUE`、`EARLYREPAYING`、`LOAN_SUCESS_PRE_WP` 等可同步状态；`XH` 前缀合同直接按已处理返回。
4. 查询账务最新账户、合同、还款计划和费项。
5. 账户状态为 NORMAL 时走普通期供同步；非 NORMAL 时走 `syncClaimsAccountInfo`。
6. 理赔账户分支发送债转短信、同步计划与费项、更新订单状态和账户状态，并将回转记录置为 `done`。

## 关键失败场景

| 现象 | 优先诊断 |
|------|----------|
| 查不到账务债转 MQ | 扩大时间后仍无入口日志，再确认账务是否发送、topic 是否正确；订单侧无日志不能证明账务债转失败 |
| 只有 MQ 入口，没有后续 | 先检查 `productClass`、`claimType` 和 PERIOD 提前返回；再查同 traceId 的 `AccountDebtTransferConsumer consume error.` |
| 有协议事件日志，没有 order 同步 | `claimType=PERIOD` 时是预期路径；`CONTRACT` 时继续查消费者异常、Dubbo 调用和 `order` 服务合同号日志 |
| `合同债转sms日志落库失败` | 只影响债转短信监控记录，代码仍继续调用订单同步；不要直接判定主链失败 |
| `[syncRepaySingleOrder]出现并发请求:` | 本次同步被并发锁短路；`transferType` 非空时应有 5 秒延迟补偿消息，继续扩大时间查询 |
| 订单不存在 | 核对 MQ `contractNo` 与订单表合同号；注意债转前后合同号及其前缀是否混用 |
| 已查询账务但没有更新订单 | 展开 traceId，重点看账务返回、计划/费项更新异常和 `syncClaimsAccountInfo` 事务回滚 |
| 有债转短信入口但未发短信 | `sendSmsIfDebtTransfer` 还受账户号前缀、资金计划、场景配置和重复发送记录控制，不代表订单同步失败 |

## 健康检查

债转健康检查属于统计模式，按主控完整性规则执行。各 Step 必须直接使用下表 SQL，不能先查裸服务日志再筛选。

| Step | 查询 SQL | 说明 |
|------|----------|------|
| `Step1`：MQ 入口量 | `serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:"` | 按 `claimType`、`productClass`、渠道和计划分组 |
| `Step2`：消费失败 | `serviceName:"order-batch" AND level:"ERROR" AND (message:"AccountDebtTransferConsumer consume error." OR message:"合同债转sms日志落库失败" OR message:"异步通知protocol")` | 消费主链、短信记录和异步协议事件分别统计 |
| `Step3`：order 查询账务 | `serviceName:"order" AND message:"同步单个订单还款状态,查询中腾信账务信息,ztxAccountInfo:"` | 只适用于应进入订单同步的非 PERIOD 分支 |
| `Step4`：理赔账户同步 | `serviceName:"order" AND message:"RepayOrderServiceImpl syncClaimsAccountInfo outBizCode is"` | 统计非 NORMAL 账户同步入口 |
| `Step5`：订单更新 | `serviceName:"order" AND message:"更新订单信息,"` | 需结合 contractNo/traceId 归属债转链路，不能把所有订单更新都算成债转完成 |
| `Step6`：钻取 | `traceId:"{提取到的hex值}"` | 从失败或不闭环样本提取 traceId，定位具体中断点 |

入口量与订单更新量不能直接做一一对比：非 `sunflower` 消息会被过滤，PERIOD 分支会提前返回，重复请求可能被并发锁短路。健康结论必须先按这些分支拆分。

## 常见误区

- 收到 MQ 不等于 order 侧处理完成。
- 协议事件日志不等于订单数据已同步。
- PERIOD 分支没有 `order` 同步日志不一定是异常。
- 债转短信未发送不等于债转同步失败。
- `currentAccountId`、`currentPlanCode` 是债转后的合同号和资金计划编码，不要与 `originalAccountId`、`originalPlanCode` 混用。
- 不要把通用还款、代扣问题路由到本模块。

## References

- `references/modules/order.md`：正式下单、订单生成和反欺诈链路
- `references/modules/repay.md`：还款、扣款、代扣、结清和账务结果通知
