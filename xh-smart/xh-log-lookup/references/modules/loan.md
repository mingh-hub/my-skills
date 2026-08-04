# 放款日志查询

本 reference 只负责普通放款、资金路由、Loki 结果、放款失败/成功和换资方的日志定位。CLS 查询、统计完整性、卡片输出和无结果 fallback 由主 `xh-log-lookup` 技能执行；本页提供可直接下沉到 CLS 的稳定锚点。

## 查询边界与主键

放款跨异步边界时以 `orderId` 为**默认且主要**主键。首查：

```text
serviceName:"order" AND message:"{orderId}"
```

首查命中后按 `fundPlan`（资金计划）和轮次分组，再用稳定日志前缀下沉条件。只有用户明确提供 `traceId` 才直搜 `traceId:"{value}"`；没有明确提供时不要把猜出的 traceId 当主线，也不要用裸 `serviceName` 查询后在本地筛选。`cid`、手机号等标识先定位 `orderId`，再回到订单号主线。

## 主链路

完整流程按顺序是：`order → loki-webapp → order-batch → order`。一条消息的 receipt、发送或 Job 运行都只是边界证据，必须继续追到下一跳和订单最终状态。

1. **order 推送**：`ApplyLoanSendLokiQHandler#sendQToLoki` 负责把申请送入 Loki。查 `推给loki:`、`[推送]`，以及缓冲池停止路由日志；这些只能证明发起或被缓冲池暂停。
2. **loki-webapp 接收**：`LoanRequestMessageConsumer#consume` 消费订单消息，查 `订单系统传入 loki 消息`，确认 Loki 收到的订单、`orderId`、`fundPlan` 和轮次。
3. **loki-webapp 回传**：`DisposeLoanResultMessageProducer#send` 发送结果，查 `通知 order 放款阶段`；它是结果通知边界，不是订单已更新的证明。
4. **order-batch 消费**：`LokiResultRecvConsumer#handleMessage` 处理回调，查 `LokiResultRecvConsumer推进来的消息ID`，并核对结果 DTO 是否进入 `LokiLoanResultServiceImpl`。
5. **order 落库**：回调处理后回到 `order` 查看订单更新结果、`[放款成功]协议共享协议号订单:`、还款计划和订单状态；只有这些后置证据齐全才允许下成功结论。

## 流程追踪入口

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| order 发起 Loki 推送 | `com.xhqb.order.biz.service.handle.ApplyLoanSendLokiQHandler#sendQToLoki` | `推给loki:` | `serviceName:"order" AND message:"推给loki:" AND message:"{orderId}"` | `fundPlan`、轮次、推送结果 | `[推送]` 只说明 order 发起消息；缓冲池停止路由要作为等待原因记录 |
| Loki 接收订单消息 | `LoanRequestMessageConsumer#consume` | `订单系统传入 loki 消息` | `serviceName:"loki-webapp" AND message:"订单系统传入 loki 消息" AND message:"{orderId}"` | `orderId`、资金计划、请求阶段 | 确认 loki-webapp 收到，不等于授信或用信成功 |
| Loki 通知 order 结果 | `DisposeLoanResultMessageProducer#send` | `通知 order 放款阶段` | `serviceName:"loki-webapp" AND message:"通知 order 放款阶段" AND message:"{orderId}"` | 结果阶段、消息 ID、发送结果 | MQ receipt 不等于放款完成，必须继续查消费者和订单状态 |
| order-batch 进入回调处理 | `LokiResultRecvConsumer#handleMessage` | `LokiResultRecvConsumer推进来的消息ID` | `serviceName:"order-batch" AND message:"LokiResultRecvConsumer推进来的消息ID" AND message:"{orderId}"` | 消息 ID、消费结果、重试 | 只证明消费者推进消息，后续以结果服务和 order 落库为准 |
| Loki 结果服务分支 | `LokiLoanResultServiceImpl` | `LokiResultRequest OrderDataDTO is:` | `serviceName:"order" AND message:"LokiResultRequest OrderDataDTO is:" AND message:"{orderId}"` | `regCode`、`regReason`、`fundPlan`、状态 | DTO 是授信/用信失败和换资方判断的主要证据 |
| Loki 状态步进 | `BaseLoanEntity` | `放款状态步进中`、`当前状态为` | `serviceName:"loki-webapp" AND message:"放款状态步进中" AND message:"{orderId}"` | Loki 当前阶段、资金计划、重试时间 | `BaseLoanEntity` 是 Loki 资金渠道状态步进，不是 order 订单落库；订单最终状态必须回到 order 核对 |
| 缓冲池阻断推送 | `ApplyLoanSendLokiQHandler#isBufferBlocked` | `缓冲池内存在停止路由或暂停路由的控制记录，不进行推送` | `serviceName:"order" AND message:"缓冲池内存在停止路由或暂停路由的控制记录，不进行推送" AND message:"{orderId}"` | `orderId`、资金计划、路由控制 | 这是等待/暂停证据，不是 Loki 推送失败；继续查缓冲池 Job |
| 失败回调清理当前计划 | `LokiLoanResultServiceImpl#exitPoolWhenLoanFailed` | `授信失败，缓冲池出池成功`、`用信失败，缓冲池出池成功` | `serviceName:"order" AND message:"缓冲池出池成功" AND message:"{orderId}"` | 当前 `fundPlan`、失败阶段 | 只清理当前计划的匹配记录，不代表订单已失败或已换资方 |
| 再分发规则匹配/入池 | `RedistributionHandler#inbound` | `再分发规则匹配开始,请求参数:{}`、`再分发规则匹配结束,匹配结果:{}`、`再分发规则入池成功` | `serviceName:"order" AND message:"再分发规则匹配开始" AND message:"{orderId}"` | `fundPlan`、失败原因、`APPLY/USE`、`bufferId` | 规则命中或入池不等于已生成新的 Loki 推送 |
| 缓冲池 Job 触发 | `HandleRedistributeBufferJob#process` | `process.start`、`process.end` | `serviceName:"order-batch-timing" AND message:"process.start"` | Job 开始/结束时间 | 只能证明调度触发，不包含订单处理结果 |
| 缓冲池异步处理 | `HandleRedistributeBufferServiceImpl#handleRedistributeBufferJob` | `再分发缓冲记录处理开始`、`待再分发处理缓冲记录数:{}`、`开始再分发`、`再分发结束` | `serviceName:"order" AND message:"再分发缓冲记录" AND message:"{orderId}"` | `bufferId`、订单状态、路由状态、再分发结果 | 没有后续 `推给loki:` 时，先查 Job 是否执行及为何跳过 |
| 放款成功清理缓冲池 | `LokiLoanResultServiceImpl#useCreditSuccess` | `订单{}放款成功，缓冲池出池成功` | `serviceName:"order" AND message:"放款成功，缓冲池出池成功" AND message:"{orderId}"` | 当前/其他资金计划、清理结果 | 这是成功后的缓冲池清理证据，仍需核对 `REPAYING`、还款计划和成功落库 |

## Loki 状态机

`BaseLoanEntity` 的阶段日志应按同一 `orderId`、资金计划和轮次排序。可查的关键锚点包括：

BaseLoanEntity 是 Loki 资金渠道状态步进，不是 order 订单落库；订单最终状态必须回到 order 核对。

- `确认放款起点从授信申请开始`：进入授信申请阶段。
- `确认放款起点从用信申请开始`：授信完成后进入用信申请阶段。
- `授信申请成功` / `授信申请失败`：分别表示授信接口结果；失败时读取 `CREDIT_APPLY_FAIL`、`regCode`、`regReason`。
- `授信成功`：授信完成，不等于资金已放出。
- `用信申请成功` / `用信申请失败`：读取用信阶段结果和资方信息。
- `用信成功`：用信成功，继续查放款收敛和还款计划。
- `放款循环处理中`：当前轮次仍在处理，属于放款中，不能当失败或成功。
- `放款失败`：必须关联失败 DTO、失败码和当前轮次。

状态码含义：`CREDIT_APPLY_FAIL` 是授信申请失败；`USE_CREDIT_ING` 是用信处理中；`USE_CREDIT_FAIL` 是用信失败；`USE_CREDIT_SUCCESS` 是用信成功。`当前状态为` 只反映 Loki 打印时刻，按时间排序并和后续 order 订单状态核对。

## order-batch 分支与结果服务

`order-batch` 收到 Loki 结果后，先查失败 DTO 锚点 `LokiResultRequest OrderDataDTO is:`，提取 `regCode`、`regReason`、`fundPlan` 和结果阶段，再定位 `LokiLoanResultServiceImpl` 的授信/用信分支。

- 可用资金检查查 `orderId:{},可用资金列表结果:{}`。没有可用资金时，按阶段区分：授信无资方 SINGFAIL，用信无资方 FAIL（即授信无资方为 `SINGFAIL`、用信无资方为 `FAIL`）。`SINGFAIL` 在该实现分支仅表示授信无可用资方后的失败收敛；它只适用于该分支，不是通用状态。
- 有资方时会记录“重新分配”，并进入后续新轮次；“重新分配”只表示重新计算/选择，必须再看到新轮次的 `推给loki:` 才能证明已向新资方推送。
- 成功分支会尝试把订单更新为 `REPAYING`；成功 MQ 通知本身不等于已更新，必须查 order 的更新结果、`USE_CREDIT_SUCCESS`、还款计划或 `[放款成功]协议共享协议号订单:`。

## Loki 结果与缓冲池/再分发

### 失败回调前后的顺序

`LokiLoanResultServiceImpl#creditApplyFail` 和 `LokiLoanResultServiceImpl#useCreditFail` 收到失败 DTO 后，都会先按 `orderId + fundPlan` 调用 `exitPoolWhenLoanFailed`，再进入再分发判断。授信失败使用 `LoanStageEnum.APPLY`，用信失败使用 `LoanStageEnum.USE`；因此必须按资金计划和阶段分组，不能把旧资方的缓冲记录与新资方结果混为一轮。

`exitPoolWhenLoanFailed` 的“缓冲池出池成功”只表示当前计划符合出池条件的缓冲记录被置为无效。它不是订单失败证据，也不是换资方证据；若订单仍有其他有效缓冲记录或路由队列，仍要继续查后续事件和 Job。

### 再分发匹配与三个结果

失败结果构造 `MappingLogModel` 后调用 `RedistributionHandler#inbound`。只有 `systemCode = fund-center` 才会进入规则匹配；请求会带上 `orderId`、资金渠道、资金计划、失败原因、借款阶段和借款金额。建议依次查询：

- `再分发规则匹配开始,请求参数:{}`、`再分发规则匹配结束,匹配结果:{}`：确认匹配输入和返回结果。
- `再分发规则匹配成功`、`再分发规则入池成功`：确认规则命中及 `bufferId`，但不能当成再次推送。
- `再分发缓冲池命中..., 对订单进行hold处理`、`再分发缓冲池路由结束需要再分发, 对订单进行hold处理`：确认缓冲池把订单显式置为 Hold。

结果字段必须按代码含义解读：

| 字段 | 含义 | 查询结论 |
|------|------|----------|
| `inboundedNeedRedistribute` | 本次新入池记录的 `redistributeStatus != NONE` | 只说明本次记录后续需要再分发 |
| `needRedistribute` | 订单现有有效缓冲记录中存在 `redistributeStatus != NONE` 的记录 | 只说明订单还有待处理缓冲状态 |
| `isHoldOn` | 路由状态不是 `CONTINUE`，或路由队列结束且仍需再分发 | 在缓冲池分支中，这是明确进入/保持 `HOLD_ON` 的结果 |

`isHoldOn=true` 时，order 发布授信/用信失败事件并返回，不能继续按普通可用资方判断。`isHoldOn=false` 但任一 `inboundedNeedRedistribute` 或 `needRedistribute` 为真时，会记录 `需要再分发，订单id:{}` 并等待事件/Job；“需要再分发不等于换资方”。只有两个标志都为假，才进入当前可用资方查询：有资方走普通重新分配，无资方才分别收敛到授信 `SINGFAIL` 或用信 `FAIL`。

缓冲记录排查至少保留这些字段：`bufferStatus`（是否仍在池）、`routeStatus`（`END/PAUSE/CONTINUE`）、`redistributeStatus`（`NONE/RELIEVE_STOP/ROUTE_END/NEXT_DAY`）、`redistributeRequired`（是否已执行再分发）、`fundsFailStage`（`APPLY/USE`）、`bufferId` 和 `fundPlan`。

### 缓冲池 Job 与真正再次推送

`HandleRedistributeBufferJob#process` 位于 `order-batch-timing`，调用 `handleBufferStatus` 和 `handleRedistribution`：

1. `handleBufferStatus` 处理计划出池时间、订单累计缓冲时长和暂停路由恢复；出现 `再分发缓冲记录到达出池时间` 或资金计划不可用时，应记录为缓冲池结束原因。
2. `handleRedistribution` 找出可再分发的 `bufferId`，调用 `RedistributionHandler#redistribute`。该方法会检查 `bufferStatus=Y`、`redistributeRequired=N`、`routeStatus=CONTINUE`、资料补充、封禁期、资金计划可用性和订单状态是否允许再分发。
3. `renewRoute` 重新创建路由结果和路由队列，并写入“再分发发送”；之后仍需回到 `ApplyLoanSendLokiQHandler#sendQToLoki` 查新的 `推给loki:`，才能确认真正再次推送。

因此，缓冲池命中后暂时没有新的 `推给loki:` 时，继续查 `order-batch-timing` Job、`bufferId` 处理结果、路由队列及阻断原因，不能直接判定失败。

### 成功后的出池

`LokiLoanResultServiceImpl#useCreditSuccess` 在订单成功处理后调用 `exitPoolWhenLoanSuccess`，可能同时清理当前和其他资金计划的有效缓冲记录，并记录 `订单{}放款成功，缓冲池出池成功`。该日志只表示缓冲池清理完成；放款成功仍需交叉核对 `USE_CREDIT_SUCCESS`、订单 `REPAYING`/成功更新、还款计划和成功后置日志。

## 三类结果排查

### 放款失败

先查 `serviceName:"order" AND message:"LokiResultRequest OrderDataDTO is:" AND message:"{orderId}"`，按资金计划/轮次读取 `regCode`、`regReason`、阶段和可用资金结果。授信失败看 `CREDIT_APPLY_FAIL`；用信失败看 `USE_CREDIT_FAIL`；无资方分别落 `SINGFAIL`（授信）或 `FAIL`（用信）。只有 DTO 与订单最终状态一致时，才允许结论“放款失败”。

### 换资方强证据

“重新分配”不是充分证据。必须在失败后按时间和轮次找到不同 fundPlan（即**不同 `fundPlan`**）的后续 `推给loki:`，并能与新的授信/用信申请关联；强证据句式是“失败后不同 fundPlan 的后续 `推给loki:`”，不能只看“重新分配”；否则只能说发生了重新分配尝试，不能说已换资方。

### 放款成功证据

至少交叉命中 `USE_CREDIT_SUCCESS`、还款计划，以及 order 的 `REPAYING` 或 `[放款成功]协议共享协议号订单:`。`REPAYING` 在状态词典中表示正常还款中，是成功侧状态但尚未结清（非结清）；单独的成功通知、MQ receipt、协议号打印或“用信成功”均不足以证明订单已完成落库。

## 证据边界

- **MQ receipt 不等于放款完成**：只证明消息被确认或发送链路到达某一边界。
- **重新分配不等于新资方推送**：必须有不同 `fundPlan` 的新轮次 `推给loki:`。
- **需要再分发不等于换资方**：再分发规则命中、入池或 Job 开始都不是再次推送；必须看到后续新的 `推给loki:`。
- **缓冲池出池成功不是放款成功或最终失败证据**：出池只改变缓冲记录状态，最终结论仍以 Loki 结果和 order 订单状态为准。
- **缓冲池命中后无新推送不等于失败**：先查 `order-batch-timing` 的 Job、`bufferId`、路由队列和 `routeStatus`；不能直接判定失败。
- **Loki 失败不等于 Hold**：只有 order 的 Hold 证据（如 `releaseHoldStatus=Y`、`ResetOrderInfoHandler`、`OrderLoanFailHoldHandler` 或 `RedistributionHandler` 的结果）和 `HOLD_ON` 状态共同成立，才可判断回 H；详细生命周期见/读取 `references/modules/hold.md`，本页只保留结果边界。
- **成功通知不等于 REPAYING**：必须有订单更新结果或状态日志。

## 分服务健康检查

按 `order/order-batch/loki-webapp` 分服务健康检查；健康检查属于统计模式，先按服务、级别和时间窗口查询并报告完整性。建议分别核对：

| 服务 | 稳定查询 | 核对内容 |
|------|----------|----------|
| `order` | `serviceName:"order" AND (message:"推给loki:" OR message:"LokiResultRequest OrderDataDTO is:")` | 推送量、结果回调和失败 DTO；不要把推送量当成功量 |
| `order-batch` | `serviceName:"order-batch" AND message:"LokiResultRecvConsumer推进来的消息ID"` | 消费、重试、失败分支与处理延迟 |
| `loki-webapp` | `serviceName:"loki-webapp" AND (message:"订单系统传入 loki 消息" OR message:"通知 order 放款阶段")` | 接收与回传是否成对，消息 ID 是否缺失 |

## 0 命中回退

1. 核对环境（未指定默认生产）、时间窗口、topic 和日志保留期；先把窗口扩大，再保持 `orderId`。
2. 从阶段查询退回 `serviceName:"order" AND message:"{orderId}"`，然后按 `fundPlan`/轮次重新分组；逐服务检查是否误查 `order-batch-timing` 或其他别名。
3. 稳定锚点仍 0 命中时，检查代码分支、日志前缀版本和标识符格式；不要用动态整行或猜测 traceId 替代。
4. 仍无证据只能报告“未命中/无法确认”，不能把 MQ receipt、重新分配、Loki 失败或成功通知升级成最终结论。

## 特殊入口导航

- **特项额度**：检索 `[特项额度]`，再回到订单号主线确认是否进入放款。

## 订单终态词典

完整定义见 `references/modules/order/order-status-glossary.md`。放款分析至少区分以下终态集合：

| 状态 | 语义 |
|------|------|
| `REPAYING` | 成功侧状态，正常还款中但尚未结清；仍需有订单更新证据 |
| `LOAN_SUCESS_PRE_WP` | 成功侧的放款完成前置状态，需继续核对协议/还款计划 |
| `SINGFAIL` | 该实现分支的失败收敛状态，授信无可用资方时写入；不是通用授信状态 |
| `FAIL` | 失败终态，用信阶段无资方或失败收敛 |
| `REPAYED` | 成功终态，已还清 |
| `SETTLED` | 成功终态，已结清/结算完成 |

状态字面值只能作为订单状态证据，不能代替 Loki 阶段证据；`REPAYING` 是成功侧的正常还款状态，`REPAYED`、`SETTLED` 才表示结清成功终态，`SINGFAIL`、`FAIL` 属失败终态。

## References

- `references/modules/order/order-status-glossary.md`：订单状态定义与终态集合。
- `references/modules/hold.md`：Hold 进入、解 H、失败回 H 和重路由的详细生命周期。
