# xh-log-lookup Hold 单模块设计

## 目标

为 `xh-log-lookup` 增加独立的 `references/modules/hold.md`，覆盖 Hold 单从进入 H 单到最终解 Hold 状态的完整日志排查生命周期。模块必须能够指导按 `orderId` 或业务场景构造收窄后的 CLS 查询，并区分单笔链路排查与 Hold 服务健康检查。

业务术语统一使用“进入 H 单”。

## 范围

模块覆盖以下服务：

- `order`：进入 H 单判断、Hold 状态维护、解 H 规则校验、资方/Loki 推送、继续 Hold、失败处理和重路由。
- `order-batch-timing`：解 H、取消 Hold、特殊渠道取消、Hold 重路由、推送和监控任务。

模块覆盖以下生命周期：

1. 订单命中 Hold 条件并进入 `HOLD_ON`。
2. 定时任务筛选可解 H 订单。
3. `order` 执行订单维度和资金维度解 H 校验，并标记可解 H 订单。
4. 推送任务将订单发送至资方/Loki，或因规则、额度和状态原因继续 Hold。
5. Hold 单取消、超时转单、特殊渠道处理或重路由。
6. Hold 单监控任务检查积压和异常。

不在本模块重复描述普通下单、资金路由和最终放款结果。正式下单仍由 `order.md` 负责；普通资金路由和放款结果仍由 `loan.md` 负责。

## 文件结构

### 新增 `references/modules/hold.md`

按现有业务模块格式组织，包含：

- 意图边界和涉及服务。
- 查询主键及首次查询策略。
- 生命周期链路表，记录场景、方法入口、稳定日志锚点、推荐查询、关键字段和结论意义。
- 进入 H 单、解 H、推送、继续 Hold、取消/超时、重路由和监控的诊断步骤。
- 常见失败模式和状态判断规则。
- 无具体标识符时的健康检查步骤。
- 与 `order.md`、`loan.md` 的边界说明。

推荐查询必须遵守主 skill 的 SQL 条件下沉规则。Hold 单排查以 `orderId` 为默认且主要的查询主键，单笔查询优先组合 `serviceName`、稳定日志锚点和 `orderId`。统计或健康检查必须遵守完整性约束。

### 更新 `SKILL.md`

- 在 description 和流程追踪意图中加入 Hold 单场景。
- 在业务路由表新增 Hold 单模块，关键词至少包含：`Hold单`、`H单`、`HOLD_ON`、`进H`、`解H`、`继续hold`、`解H推送`、`取消Hold`、`Hold超时`、`超时转单`、`CRM催促解H`。
- Hold 单关键词优先路由到 `references/modules/hold.md`，避免“解 H”继续落到放款模块。
- “拒就赔解 H”等同时包含权益或放款关键词与 Hold 动作的意图，按更具体的 Hold 生命周期语义路由到 `hold.md`；单独的“拒就赔”仍沿用现有权益/放款路由。
- 在 References 列表增加 Hold 单模块导航。

### 更新 `references/modules/loan.md`

- 移除“解H”生命周期锚点，避免与 `hold.md` 双重维护。
- 从涉及项目描述中移除 `ReleaseHoldOrderServiceImpl`。
- 增加简短边界说明：Hold 单、进入 H 单、解 H、继续 Hold、取消和超时问题读取 `references/modules/hold.md`。
- 保留资金路由、放款、拒就赔 JOB 和提前结清等放款职责。

## 核心日志锚点

实现时只选取源码中存在且不依赖动态值的稳定前缀。候选锚点包括：

- 进入 H 单判断：`非白名单校验结果`、`资产比例控制处理结果`，并结合订单号追踪进入 `HOLD_ON` 的原因。
- 解 H 任务：`[新解H]job开始`、`[新解H异常]`。
- 单笔解 H：`[新解H]订单:`、`订单维度解h校验结果`、`资金维度校验结果`、`进入解H状态`。
- 推送资方：`[新解H推送]订单:`、`推送给资方`、`需要继续h单`、`订单状态不为hold`。
- 重路由：`当前批次` 与 `重路由` 相关日志，并组合订单号查询。
- 定时任务和监控：各 Job 的 `.process.start`、`.process.end` 与异常日志。

包含动态订单号的日志不得把完整格式作为固定全文锚点。推荐查询应使用稳定前缀，再追加 `message:"{orderId}"`。

## 查询与结论规则

- 用户提供 `orderId`：首查 `serviceName:"order" AND message:"{orderId}"`；若用户明确关注解 H、推送或取消，再加入对应稳定前缀收窄。
- 不主动把 `traceId` 作为 Hold 单常规查询入口。只有用户明确提供 `traceId` 时，才沿用主 skill 的标识符查询规则；定位到 `orderId` 后，后续 Hold 生命周期分析仍以订单号为主线。
- 用户只描述“为什么还在 H 单”：依次检查进入 H 单原因、解 H 筛选、订单和资金校验、继续 Hold 原因、推送状态。
- 用户描述“解 H 失败”：检查 `[新解H异常]`、订单状态、可用资方、资金计划、额度、资产缓冲池、解 H 状态标记和后续推送任务。
- 用户描述“Hold 单积压/异常”：按 `order`、`order-batch-timing` 分服务执行健康检查，不用宽查询结果在本地筛选。
- 只有日志证明订单已经进入后续状态或成功推送，才能下“已解 H”结论；仅命中解 H Job 或候选订单日志不代表解 H 成功。

## 失败与边界处理

- 无可用资方、资金计划关闭、额度不足、资产缓冲池控制、标签策略不允许、订单状态已变化等场景必须分别归因。
- “需要继续 H 单”不是系统异常，应输出具体业务规则或资金限制。
- `order-batch-timing` Job 成功执行不代表每笔订单成功解 H。
- 0 命中时按主 skill 的时间窗口、环境、topic、锚点有效性和标识符检查顺序回退。

## 遗留链路处理

源码仍保留 `order-batch` 的 `HandleHoldOrderConsumer` 和 `LoanOrderService.handleHoldOnOrder` 老解 H 链路，但当前生产未观察到消费者日志，且 2025 年新增的主流程已由 `ReleaseHoldOrderJob`、`ReleaseHoldOrderServiceImpl.releaseHoldOrder` 和 `ReleaseHoldSendToLokiJob` 直接完成解 H 筛选、校验与推送。

因此：

- 不把 `HandleHoldOrderConsumer推进来的消息ID` 作为生产 Hold 单排查锚点。
- 不把 `order-batch` 纳入默认解 H 生命周期或健康检查范围。
- 只有用户明确调查老流程、历史订单或生产日志重新出现该消费者证据时，才将其作为遗留分支分析。

## 验证方案

### 修改前基线

以以下检索场景检查现有文档无法完整路由或回答：

- “订单为什么进入 H 单？”
- “这个 orderId 为什么一直 HOLD_ON？”
- “解 H 后为什么没有推送 Loki？”
- “Hold 单是否有积压或超时转单异常？”

基线应显示当前主路由只把“解H”指向 `loan.md`，且缺少进入 H 单、继续 Hold、取消/超时和监控链路。

### 修改后验证

- 静态检查主 `SKILL.md` 的 Hold 关键词均指向 `hold.md`。
- 检查 `loan.md` 不再维护独立解 H 锚点，只保留边界链接。
- 运行 `scripts/validate_query_anchors.py --all --summary`，确认 `hold.md` 被自动发现并校验方法入口、服务名和日志锚点。
- 对校验脚本无法识别的动态日志格式进行人工源码核对，并使用保守查询作为 fallback。
- 运行现有 Python 测试，确认主 skill 的脚本行为未回归。
- 运行 skill 基础结构校验并检查最终 diff，不引入无关文件或修改。

## 验收标准

- `hold.md` 能独立指导完整 Hold 生命周期排查。
- “进入 H 单”术语在新增和修改内容中保持一致。
- Hold 单单笔排查默认以 `orderId` 为主键，不主动依赖 `traceId`。
- 主路由能把 Hold 单相关自然语言稳定路由到 `hold.md`。
- `loan.md` 与 `hold.md` 没有重复维护解 H 细节。
- 推荐查询均使用 CLS 支持的字段和引号格式，并尽量下沉筛选条件。
- 锚点校验、现有测试和结构校验完成；不能校验的锚点明确标注保守 fallback。
