# Hold 单日志查询

Hold 单模块只提供 `orderId` 首查策略、完整生命周期追踪入口、回 H 判断规则、取消/重路由诊断和健康检查。CLS 执行、完整性判断、飞书卡片输出和 fallback 统一交给 `xh-log-lookup` 主控工具。

## 目录

- 涉及服务与意图边界
- 查询主键、首查策略与条件下沉示例
- 核心流程链路追踪模版
- 生命周期诊断顺序
- 常见失败与结论规则
- 健康检查与 0 命中回退
- 遗留链路与 References

## 涉及服务

- `order`：进入 H 单判断、解 H 校验、推送 Loki、Loki 结果回调、失败回 H、取消和重路由的业务日志。
- `order-batch-timing`：解 H、推送、取消、重路由和监控 Job 的运行日志。

`order-batch` 的旧消费者不属于当前生产主链，详见“遗留链路”章节。

## 意图边界

- **本模块负责**：Hold 单、H 单、`HOLD_ON`、进入 H 单、进 H、解 H、继续 Hold、解 H 推送、取消 Hold、Hold 超时、超时转单、CRM 催促解 H，以及“推送 Loki 后为什么又进入 H 单”。
- **正式下单**：订单生成、下单拦截和反欺诈由 `references/modules/order.md` 负责。
- **普通放款**：普通资金路由、资方放款结果、拒就赔 JOB 和提前结清由 `references/modules/loan.md` 负责。只要问题包含明确 Hold 动作，如“拒就赔解 H”，优先留在本模块。
- **结果边界**：本模块跟踪到订单离开 Hold、推送 Loki、失败后再次进入 H 单或被取消/重路由。成功进入普通授信、用信和放款后，继续读取 `loan.md`。

## 查询主键与首查策略

Hold 单排查以 `orderId` 为默认且主要的查询主键。不要为了串联 Hold 生命周期而主动寻找 `traceId`。

| 用户提供 | 推荐首查语句 | 说明 |
|---------|-------------|------|
| 订单号：`orderId` | `serviceName:"order" AND message:"{orderId}"` | 默认首查，先确认进入 H 单、解 H 校验、推送和回调分别走到哪一步 |
| 明确的 Hold 阶段和 `orderId` | `serviceName:"order" AND message:"{稳定锚点}" AND message:"{orderId}"` | 按下方生命周期表把条件下沉到 CLS |
| 线程号：`traceId` | `traceId:"{value}"` | 只有用户明确提供 `traceId` 时才直搜，不加 `serviceName`；提取到 `orderId` 后回到订单号主线 |
| `cid`、手机号、身份证号 | 先定位 `orderId`，再执行订单号首查 | Hold 日志通常以订单号打印，不把客户标识作为长期主线 |

只有用户明确提供 `traceId` 时才沿用主 skill 的 trace 查询规则；查询到订单号后，后续步骤仍使用 `orderId`。

## 条件下沉示例

| 用户意图 | 首查 SQL | 后续分析 |
|---------|---------|---------|
| 为什么进入 H 单 | `serviceName:"order" AND message:"订单所有queue记录进入hold单，订单置为HOLD_ON" AND message:"{orderId}"` | 再查同订单的 `非白名单校验结果`、`资产比例控制处理结果` 和 `渠道需要hold单`，提取具体规则原因 |
| 为什么一直 HOLD_ON | `serviceName:"order" AND message:"[新解H]订单:" AND message:"{orderId}"` | 按订单维度、资金维度、限额、禁闭期、缓冲池和可用资方顺序检查 |
| 是否进入可解 H 状态 | `serviceName:"order" AND message:"进入解H状态" AND message:"{orderId}"` | 仅表示解 H 校验通过并标记待推送，不代表已经推送 Loki |
| 解 H 后未推送 Loki | `serviceName:"order" AND message:"[新解H推送]订单:" AND message:"{orderId}"` | 检查可推送渠道、推送前校验、资产比例、限额冻结和订单当前状态 |
| 推送前继续 H 单 | `serviceName:"order" AND message:"[新解H推送]订单:" AND message:"需要继续h单" AND message:"{orderId}"` | 提取业务原因；继续 H 单本身不是系统异常 |
| 已发起推送 Loki | `serviceName:"order" AND message:"推送给资方:" AND message:"{orderId}"` | 说明 order 已发起推送；继续查 Loki 回调才能判断后续结果 |
| Loki 失败后又进入 H 单 | `serviceName:"order" AND message:"[新解H]放款失败，查询订单解h状态：" AND message:"{orderId}"` | 结合失败回调、`releaseHoldStatus`、`regCode` 和重路由结果判断 |
| Hold 超时转单 | `serviceName:"order" AND message:"订单hold单超时转单" AND message:"{orderId}"` | 确认是否自动取消并触发期数转换 |
| Hold 兜底重路由 | `serviceName:"order" AND message:"订单入库:" AND message:"{orderId}"` | 再看同一批次的重路由数量和异常 |

不得用裸 `serviceName:"order"` 的宽查询结果在本地筛选上述阶段。查询明确阶段时，必须把稳定锚点和订单号同时下沉。

## 核心流程链路追踪模版

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 进入 H 单规则判断 | `com.xhqb.order.biz.service.handle.OrderCheckHoldHandler#checkHold` | `非白名单校验结果` | `serviceName:"order" AND message:"非白名单校验结果" AND message:"{orderId}"` | `success`、`resultCode`、`resultMessage` | 非白名单、资金计划可用性、授信时间和渠道限制会决定是否需要 Hold |
| 资产比例 Hold 判断 | `com.xhqb.order.biz.service.handle.OrderCheckHoldHandler#handleFundAssetRateConfig` | `资产比例控制处理结果` | `serviceName:"order" AND message:"资产比例控制处理结果" AND message:"{orderId}"` | `canPush`、`canPushOrderType` | 不能推送时可能保持 Hold；先看业务返回，不要直接定性系统异常 |
| 订单进入 HOLD_ON | `com.xhqb.order.biz.service.handle.DefaultOrderRouteQueueHandler#doOnRoute` | `订单所有queue记录进入hold单，订单置为HOLD_ON` | `serviceName:"order" AND message:"订单所有queue记录进入hold单，订单置为HOLD_ON" AND message:"{orderId}"` | queue 的 `holdStatus`、`nodeStatus` | 全部可用 queue 都需要 Hold 时，订单状态更新为 `HOLD_ON` |
| 解 H 候选处理 | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#handleOrder` | `[新解H]订单:` | `serviceName:"order" AND message:"[新解H]订单:" AND message:"{orderId}"` | 订单类型、优先级 | CRM 催促、渠道优先级、标签策略和普通解 H 最终都进入该单笔处理 |
| 订单维度解 H 校验 | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#handleOrder` | `订单维度解h校验结果` | `serviceName:"order" AND message:"订单维度解h校验结果" AND message:"{orderId}"` | `success`、`resultMessage` | 失败时继续 H 单并记录原因 |
| 资金维度解 H 校验 | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#handleOrder` | `资金维度校验结果` | `serviceName:"order" AND message:"资金维度校验结果" AND message:"{orderId}"` | `fundPlan`、额度、禁闭期、资方状态 | 同一订单可能逐个检查多个资金计划 |
| 标记进入解 H 状态 | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#handleOrder` | `进入解H状态` | `serviceName:"order" AND message:"进入解H状态" AND message:"{orderId}"` | queue `releaseHoldStatus=Y`、订单扩展表 `releaseHoldStatus=Y` | 只是进入待推送集合，不能据此下“已推送”结论 |
| 解 H 推送处理 | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#releaseHoldSendToLoki` | `[新解H推送]订单:` | `serviceName:"order" AND message:"[新解H推送]订单:" AND message:"{orderId}"` | queue、资金计划、当前订单状态 | 推送任务重新检查可推送渠道和状态 |
| 推送前继续 Hold | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#releasingHoldQueue` | `需要继续h单` | `serviceName:"order" AND message:"需要继续h单" AND message:"{orderId}"` | `resultMessage`、限额冻结结果 | 常见原因是资产比例、额度、缓冲池、资金计划或订单状态，不等同于 Loki 失败回 H |
| 发起 Loki 推送 | `com.xhqb.order.biz.service.impl.ReleaseHoldOrderServiceImpl#releasingHoldQueue` | `推送给资方:` | `serviceName:"order" AND message:"推送给资方:" AND message:"{orderId}"` | `fundPlanId`、订单状态 | 随后订单进入 `PRESIGN` 并调用 Loki；还需查回调确认结果 |
| Loki 授信失败回调 | `com.xhqb.order.biz.service.impl.loki.LokiLoanResultServiceImpl#creditApplyFail` | `LokiResultRequest OrderDataDTO is:` | `serviceName:"order" AND message:"LokiResultRequest OrderDataDTO is:" AND message:"{orderId}"` | `regCode`、`regReason`、`fundPlan` | 回调内容是判断失败阶段和特殊回 H 规则的主要证据 |
| Loki 用信失败回调 | `com.xhqb.order.biz.service.impl.loki.LokiLoanResultServiceImpl#useCreditFail` | `LokiResultRequest OrderDataDTO is:` | `serviceName:"order" AND message:"LokiResultRequest OrderDataDTO is:" AND message:"{orderId}"` | `regCode`、`regReason`、`fundPlan` | 同一稳定锚点需结合前后状态和业务轨迹区分授信/用信阶段 |
| 解 H 失败后再次进入 H 单 | `com.xhqb.order.biz.service.handle.ResetOrderInfoHandler#creditFailResetOrder` | `[新解H]放款失败，查询订单解h状态：` | `serviceName:"order" AND message:"[新解H]放款失败，查询订单解h状态：" AND message:"{orderId}"` | `releaseHoldStatus`、最终 `orderStatus` | `releaseHoldStatus=Y` 时，失败重置从默认 `ON_ROUTE` 改为 `HOLD_ON`；用信失败的 `useCreditResetOrder` 规则相同 |
| Hold 兜底重路由入批次 | `com.xhqb.order.biz.service.impl.OrderHoldRouteServiceImpl#insertOrderHoldRouteRecord` | `订单入库:` | `serviceName:"order" AND message:"订单入库:" AND message:"{orderId}"` | `batchNo`、`fundPlanId`、余额、登记额度 | 后续由同批次 `batchResetOrder` 执行重路由 |
| Hold 超时取消 | `com.xhqb.order.biz.service.impl.LoanOrderServiceImpl#cancelHoldOrders` | `已hold单超过规定小时数` | `serviceName:"order" AND message:"已hold单超过规定小时数" AND message:"{orderId}"` | 超时小时数、后续状态 | 满足条件后转 `SINGFAIL` 并执行失败收尾 |
| Hold 超时转单 | `com.xhqb.order.biz.service.impl.LoanOrderServiceImpl#autuCancelHoldAndConvert` | `订单hold单超时转单orderIds` | `serviceName:"order" AND message:"订单hold单超时转单orderIds" AND message:"{orderId}"` | 订单列表、取消类型、期数转换标记 | 该逻辑由新解 H Job 前置触发 |

## 生命周期诊断顺序

### 为什么仍在 H 单

1. 查 `订单所有queue记录进入hold单，订单置为HOLD_ON` 和同订单的规则日志，确认最初进入 H 单原因。
2. 查 `[新解H]订单:`。未命中时，再检查解 H Job 是否运行、时间窗口是否覆盖、订单是否进入候选集合。
3. 查 `订单维度解h校验结果`；失败时直接使用 `resultMessage` 归因。
4. 查每个资金计划的 `资金维度校验结果`、`限额是否充足校验结果` 和 `需要继续h单`。
5. 命中 `进入解H状态` 后继续查 `[新解H推送]订单:`，不得在此提前停止。
6. 推送阶段仍可能因无可推送渠道、资产缓冲池、资产比例、限额冻结或订单状态变化而继续 Hold。

### 解 H 推送 Loki 后为什么又进入 H 单

1. 先用 `推送给资方:` 确认 order 已发起 Loki 推送，并记录资金计划。
2. 查 `LokiResultRequest OrderDataDTO is:`，提取 `regCode`、`regReason`、`fundPlan` 和失败阶段。
3. 查 `[新解H]放款失败，查询订单解h状态：`。若值为 `Y` 且随后订单状态是 `HOLD_ON`，说明该解 H 订单在授信/用信失败重置时再次进入 H 单。
4. 若未走重置路径，检查 `OrderLoanFailHoldHandler`：只有 `regCode` 和金额命中 `order.loanfail.hold.info` 时才执行特殊失败回 H。
5. 再检查再分发/重路由结果。只有重路由结果明确要求 Hold，才能归为重路由回 H。
6. 回 H 后应在后续时间再次出现 `[新解H]订单:`，从而形成“解 H -> 推送 Loki -> 失败回 H -> 再解 H”的循环。

**判断底线：Loki 返回失败不等于一定再次进入 H 单。** 只有以下任一证据成立才能下回 H 结论：

- `releaseHoldStatus=Y`，并经过 `ResetOrderInfoHandler` 把状态恢复为 `HOLD_ON`。
- `regCode` 和金额命中 `order.loanfail.hold.info`，`OrderLoanFailHoldHandler#updateOrderStatus` 执行特殊失败回 H。
- 重路由结果明确要求 Hold，并有订单状态或业务轨迹日志佐证。

## 常见失败与结论规则

| 现象 | 优先诊断 | 允许结论 |
|------|----------|----------|
| 只命中 `[新解H]job开始` | 继续找单笔 `[新解H]订单:` | Job 已启动，不代表该订单被处理 |
| 订单维度校验失败 | 提取 `resultMessage` | 因订单规则继续 H 单 |
| 资金维度校验失败 | 按 `fundPlan` 比较结果 | 只能说明该资金计划不可解 H；还有其他计划时继续检查 |
| `进入解H状态` 后无推送日志 | 查推送 Job 健康、候选查询和订单当前状态 | 已进入待推送，不代表已解 H |
| `需要继续h单` | 提取资产比例、额度、资金计划、缓冲池或状态原因 | 业务 Hold；除非同时有异常堆栈，否则不定性系统故障 |
| `订单状态不为hold，跳过推单处理` | 查询状态变化和重路由日志 | 订单已被其他流程更新，当前推送被主动跳过 |
| `推送给资方` 后失败 | 查 Loki 回调和三类回 H 条件 | 有条件地判断再次进入 H 单，不能把所有失败都算回 H |
| 无可用资方/无可推送渠道 | 区分是否等待缓冲池处理 | 可能继续 H、等待再分发或置失败，按后续状态定结论 |
| Hold 超时 | 区分普通取消、在贷逾期取消、18% 转 24% | 输出实际取消类型和最终状态 |

只有命中后续状态或推送证据，才能说明订单离开当前 Hold 阶段。`进入解H状态` 只是内部标记；`推送给资方` 表示发起推送；最终授信、用信和放款成功需按 `loan.md` 的结果证据判断。

## 健康检查

无具体 `orderId` 时才进入健康检查。健康检查属于统计模式，必须遵守主控的完整性规则；每个 Step 直接使用下表 SQL，按 `order` 和 `order-batch-timing` 分服务查询，不得用宽查询样本在本地统计。

`order-batch-timing` 的 `ReleaseHoldOrderJob.process.start`、`ReleaseHoldSendToLokiJob.process.start` 分别对应 `order` 业务方法入口 `[新解H]job开始`、`[新解H推送]job开始`。前者证明调度触发，后者证明业务服务真正进入；健康检查应成对核对。

| Step | 查询 SQL | 说明 |
|------|----------|------|
| `Step0`：order 解 H 异常 | `serviceName:"order" AND level:"ERROR" AND message:"[新解H异常]"` | 单查业务异常前缀；提取订单号和堆栈 |
| `Step1`：解 H Job | `serviceName:"order-batch-timing" AND message:"ReleaseHoldOrderJob.process.start"` | 对比 `ReleaseHoldOrderJob.process.end`；批异常锚点为 `[新解H异常]解H批异常` |
| `Step2`：推送 Job | `serviceName:"order-batch-timing" AND message:"ReleaseHoldSendToLokiJob.process.start"` | 对比 `ReleaseHoldSendToLokiJob.process.end`，再结合 order 推送阶段异常 |
| `Step3`：取消 Job | 分别查 `serviceName:"order-batch-timing" AND message:"CancelHoldOrdersJob.process.start"`、`serviceName:"order-batch-timing" AND message:"CancelSpecialChannelHoldOrdersJob.process.start"` | 对比各自 `.process.end`；普通取消还需查 `CancelHoldOrdersJob,running error` |
| `Step4`：兜底重路由 Job | `serviceName:"order-batch-timing" AND message:"HandleOrderHoldRouteJob.process.start"` | 对比 `.process.end`，再查 order 的 `当前批次` 和 `重路由` 日志 |
| `Step5`：积压监控 Job | `serviceName:"order-batch-timing" AND message:"HandleHoldOrdersMonitorJob.process.start"` | 对比 `.process.end`；业务侧数据锚点为 `hold单卡单监控发给飞书的数据:` |
| `Step6`：继续 Hold 分布 | `serviceName:"order" AND message:"需要继续h单"` | 统计模式下完整加载或拆时间窗口，再按 `resultMessage` 分类 |

Job 的 start/end 只能证明任务运行。`order-batch-timing` Job 成功不代表每笔订单成功解 H；单笔结论必须回到 `orderId` 的 order 日志。

## 0 命中回退

1. 确认环境和时间窗口；生产默认从 `now-7d,now` 扩到 `now-30d,now`。
2. 保留 `orderId`，从阶段锚点查询退回 `serviceName:"order" AND message:"{orderId}"`。
3. 检查订单是否实际进入 `HOLD_ON`，以及问题是否应路由到 `order.md` 或 `loan.md`。
4. 校验当前代码分支中的方法和日志锚点；动态订单号日志只搜稳定片段。
5. 仍无结果时说明时间、环境、topic、日志保留期和锚点有效性风险，不编造业务结论。

## 遗留链路

源码仍保留 `order-batch` 的 `HandleHoldOrderConsumer` 和 `LoanOrderService#handleHoldOnOrder`，但生产主链已经由 `ReleaseHoldOrderJob`、`ReleaseHoldOrderServiceImpl#releaseHoldOrder` 和 `ReleaseHoldSendToLokiJob` 完成筛选、校验和推送。

- 默认排查和健康检查不查询 `order-batch`，也不使用旧消费者消息日志作为生产证据。
- 只有用户明确调查历史订单、旧流程，或生产重新出现该消费者证据时，才把它作为遗留分支展开。

## References

- `references/modules/order.md`：正式下单、下单拦截和反欺诈
- `references/modules/loan.md`：普通资金路由、授信/用信后的放款结果、拒就赔 JOB 和提前结清
- `references/modules/order/order-status-glossary.md`：`HOLD_ON`、`ON_ROUTE`、`PRESIGN`、`PRELOAN` 等订单状态定义
- `references/common/cls-api-query.md`：CLS API、完整性字段和 fallback 规则
