# 签约日志查询

签约模块处理自营签约绑卡、API 渠道签约绑卡、重新签约、协议状态、代扣协议失效和协议共享问题。CLS 执行、加载更多、飞书卡片优先输出和纯文本 fallback 统一交给 `xh-log-lookup` 主控。

## 意图边界

- **默认自营签约**：用户只说"签约"、"绑卡"、"借款签约"、"新增签约"、"换绑卡"、"还款签约绑卡"、"重签约"、"重新签约"、`RESIGN`、"一直提示重签"，且未明确 API 渠道时，默认按自营签约绑卡查询，主服务是 `h5-loan`。
- **API 渠道签约**：用户明确说"API 渠道"、"渠道侧"、"渠道"、"API 新增绑卡"、"API 换卡"、"快捷绑卡协议通知"、"接口绑卡"时，按 API 渠道签约查询，主服务是 `order`。
- **协议共享**：用户问"协议共享"、"协议号同步 loki"、"loki 没收到协议"、"资金平台协议推送"时，先查 `order` 生成/共享协议 MQ，再用桥接键查 `loki-webapp`。
- **还款触发重签/协议失效**：用户明确说 `SIGNING_ISSUE`、"还款失败提示重签"、"支付协议失效"时，先按自营签约定位客户和签约状态，再用 `order` 查协议失效、还款失败触发和支付侧状态，必要时联动 `repay.md`。

## 首查策略

手机号、身份证号、银行卡号可以作为定位入口，但不是最终诊断证据。查到 `cid/orderId/contractNo/applyId/agreementNo` 后，必须继续用稳定标识符追签约链路。

| 用户提供 | 推荐首查语句 | 说明 |
|----------|--------------|------|
| `traceId` | `traceId:"{value}"` | 全链路直查，不加 `serviceName` |
| `cid` | 自营/重签：`serviceName:"h5-loan" AND message:"[签约" AND message:"{cid}"`；API：`serviceName:"order" AND message:"[签约" AND message:"{cid}"` | 未指定 API 时优先自营，`RESIGN` 也先走自营 |
| 手机号/银行卡号 | 自营：`serviceName:"h5-loan" AND message:"[签约查询]cid" AND message:"签约查询请求为" AND message:"{value}"`；API：`serviceName:"order" AND message:"[卡片校验]" AND message:"api卡片校验参数" AND message:"{value}"` | 先定位 `cid/applyId/signChannel` |
| 身份证号 | `serviceName:"h5-loan" AND message:"{idCard}"`，无结果时改查手机号、银行卡号或 `cid` | 身份证可能脱敏，不能只凭身份证无结果下结论 |
| `applyId` | 自营：`serviceName:"h5-loan" AND (message:"[签约确认]" OR message:"[签约绑卡]") AND message:"{applyId}"`；API：`serviceName:"order" AND message:"[签约确认]" AND message:"{applyId}"` | 申请后确认/绑卡的桥接键 |
| `orderId` | `serviceName:"order" AND message:"{orderId}" AND (message:"签约" OR message:"SINGFAIL" OR message:"PRESIGN")` | 借款签约失败与下单链路交叉判断 |
| `contractNo` | `serviceName:"order" AND message:"{contractNo}" AND (message:"签约" OR message:"协议" OR message:"扣款失败")` | 还款协议/代扣协议问题优先 |
| `agreementNo` | `serviceName:"order" AND message:"{agreementNo}"`，再查 `serviceName:"loki-webapp" AND message:"{agreementNo}"` | 协议生成和协议共享追踪 |

## 自营签约绑卡

自营签约绑卡流程：签约查询 -> 签约申请 -> 签约确认 -> 签约绑卡 -> 协议生成/共享。主入口在 `H5LoanProject`，日志服务为 `h5-loan`；签约查询和确认内部会调用 `order` 的签约能力。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 签约查询/重签查询 | `com.xhqb.h5loan.biz.service.controller.AgreementPayController#querySignSituation` | `[签约查询]cid`、`签约查询请求为`、`调用order签约查询结果为`、`签约查询结果为` | `serviceName:"h5-loan" AND message:"[签约查询]cid" AND message:"签约查询请求为" AND message:"{value}"` | `scene`、`needSign`、`needSignBack`、`handle`、`signInfos` | 默认首查入口，`RESIGN/重签` 也先查这里 |
| 签约申请 | `com.xhqb.h5loan.biz.service.controller.AgreementPayController#applySign` | `[签约申请]cid`、`签约申请请求`、`签约申请结果` | `serviceName:"h5-loan" AND message:"[签约申请]cid" AND message:"签约申请请求" AND message:"{value}"` | `success`、`resultCode`、`applyId`、`signChannel` | `needSign=true` 后前端发起申请 |
| 签约确认 | `com.xhqb.h5loan.biz.service.controller.AgreementPayController#submitSign` | `[签约确认]cid`、`发起签约确认信息`、`签约确认结果` | `serviceName:"h5-loan" AND message:"[签约确认]" AND message:"{applyId}"` | `verifyCode`、`applyId`、`signChannel`、确认结果 | 这是签约确认，不是协议共享 |
| 签约绑卡 | `com.xhqb.h5loan.biz.service.controller.AgreementPayController#confirmAndSaveCard` | `[签约绑卡]cid`、`请求`、`结果`、`查询到签约申请缓存信息为` | `serviceName:"h5-loan" AND message:"[签约绑卡]cid" AND message:"请求" AND message:"{applyId}"` | `applyId` 不能为空，绑卡成功后关注卡包保存/更新结果 | 客户确认后落卡/换卡 |

### 自营判断规则

- `submitSign` 是签约确认，不是协议共享；不要把它写成协议同步成功。
- `querySignSituation` 返回中 `needSign=true` 表示需要继续签约；`handle="NEXTSTEP"` 表示可跳过签约；`handle="CHANGECARD"` 表示需要换卡。
- `signInfos.signStatus` 中 `UNSIGNED` 表示未签约，`SIGNED` 表示已签约，`UNWANTED` 表示不需要签约，`SIGNIFAID` 表示签约失败。`SIGNIFAID` 是代码判断值，不要按拼写直觉改成其他枚举。
- 签约申请成功后必须提取 `applyId`，后续签约确认和签约绑卡都应带 `applyId` 追踪。
- 自营链路出现支付侧状态不清时，用同一 `cid/applyId/signChannel` 到 `order` 查询签约申请/确认和支付侧日志。
- 重签查询命中后要看 `scene` 是否为 `RESIGN`，以及 `signInfos` 中每个渠道是否仍未签完；不要只凭用户看到重签弹窗就认定支付侧异常。
- 重签缓存可能保留 10 分钟，签约成功后缓存不一定立即清除；客户只签了部分渠道时，剩余渠道仍可能继续提示重签。

## API 渠道签约绑卡

API 渠道流程：卡片校验/签约查询 -> 返回未签约渠道 -> 签约申请 -> 短信确认签约 -> 再次卡片校验 -> 签约绑卡/换卡 -> 协议生成/共享。`inspect` 既是前置校验入口，也是签约完成后的落卡/换卡入口。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 卡片校验/签约过滤 | `com.xhqb.order.biz.service.impl.api.CardInfoInspectServerImpl#inspect` | `[卡片校验]api卡片校验参数`、`当前签约的渠道信息为`、`当前需要签约的渠道信息为`、`卡片校验失败` | `serviceName:"order" AND message:"[卡片校验]" AND message:"api卡片校验参数" AND message:"{value}"` | `needSignCount`、`notSignChannel`、`isCardBind`、`failureCode` | API 渠道首查入口 |
| 换卡处理 | `com.xhqb.order.biz.service.impl.api.CardInfoInspectServerImpl#changeCard` | `[卡片校验]换卡请求`、`[卡片校验]换卡结果` | `serviceName:"order" AND message:"[卡片校验]" AND (message:"换卡请求" OR message:"换卡结果") AND message:"{value}"` | 换卡入参、换卡结果、订单/合同维度 | API 换卡时联动 |
| 签约渠道查询 | `com.xhqb.order.biz.service.impl.SignServiceImpl#query` | `[签约查询]查询签约场景`、`查询签约渠道结果`、`调用支付签约查询请求`、`调用支付签约查询结果` | `serviceName:"order" AND message:"[签约查询]" AND message:"查询签约场景" AND message:"{value}"` | `scene`、`signChannel`、`signStatus`、`fundPayChannel`、`agreementType`、`agreementNo`、`canSign` | 自营支付侧状态不清时也可补查 |
| 签约申请 | `com.xhqb.order.biz.service.impl.SignServiceImpl#apply` | `[签约申请]签约申请请求内容`、`并发请求`、`支付签约申请信息请求`、`支付签约申请信息结果`、`签约申请请求业务出错`、`签约申请请求系统出错` | `serviceName:"order" AND message:"[签约申请]" AND message:"签约申请请求内容" AND message:"{value}"` | `applyId`、`agreementType`、`formUrl/formParams`、`signChannel` | 渠道侧拿 `notSignChannel` 后发起 |
| 短信确认签约 | `com.xhqb.order.biz.service.impl.SignServiceImpl#confirm` | `[签约确认]取得签约申请缓存为`、`支付签约确认信息请求`、`支付签约确认信息结果`、`签约确认业务出错`、`签约确认系统出错` | `serviceName:"order" AND message:"[签约确认]" AND message:"{applyId}"` | 申请缓存、验证码确认结果、支付侧协议号 | 确认成功只代表支付侧签约完成 |
| 协议通知 | `com.xhqb.order.biz.service.impl.SignServiceImpl#notifyProtocol` | `notifyProtocol.redisKey`、`签约后生产协议Q, 参数` | `serviceName:"order" AND message:"notifyProtocol.redisKey" AND message:"{cid或agreementNo}"` | 频控、`agreementNo`、`payChannel`、协议 MQ 参数 | 外部已有协议号或快捷绑卡通知；成功生成协议 MQ 继续查下方 `JmsQService#signConfirmNotifyProto` |

### API 判断规则

- `inspect` 返回 `notSignChannel` 时，渠道侧通常取未签约渠道发起 `apply`；签约确认成功后还要再次调用 `inspect`，确认所有渠道已签后才完成落卡或换卡。
- `SignServiceImpl#confirm` 从 `applyId` 缓存读取申请信息；缓存不存在会返回"请先发起短信验证"，确认时 `signChannel` 必须和申请一致，否则要求重新发起短信验证。
- `apply` 对 `银行卡 + 签约渠道` 做 50 秒防并发；部分渠道还会限制 60 秒内重复申请。
- `notifyProtocol` 不调支付确认，只按已有协议号生成协议 MQ；`payChannel=baofu` 会转换为 `baofu#payChannel`；同一客户同一协议号一分钟内只能通知一次。

## 通用协议共享

协议共享常见于签约绑卡或解绑后，`order` 生成协议共享消息发给 `loki`，`loki` 再调资金平台 HTTP 服务处理。`loanApplyNo` 是 `order` 发 MQ 和 `loki` 接 MQ 的桥接键。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 签约后生成协议 MQ | `com.xhqb.order.biz.service.impl.others.JmsQService#signConfirmNotifyProto` | `签约后生产协议Q, 参数` | `serviceName:"order" AND message:"签约后生产协议Q" AND message:"{cid或agreementNo}"` | `agreementNo`、`payChannel` | 签约确认后通知生成协议 |
| order 发送 loki MQ | `com.xhqb.order.biz.service.handle.SharingAgreementLokiQtHandle#sendQToLoki` | `[协议共享]协议号共享请求loki`、`协议号共享请求loki结束` | `serviceName:"order" AND message:"[协议共享]协议号共享请求loki" AND message:"{value}"` | `loanApplyNo`、`agreementNo`、`cid` | `value` 优先用 `loanApplyNo/agreementNo/cid` |
| loki 接收 MQ | `com.xhqb.loki.message.tdmq.consumer.SharingAgreementMessageConsumer#sharingAgreementConsumer` | `[协议共享]order推送协议号消息`、`order推送协议号处理出错` | `serviceName:"loki-webapp" AND message:"[协议共享]order推送协议号消息" AND message:"{loanApplyNo}"` | `orgCode`、`loanApplyNo`、`creditApplyNo`、`transType` | 命中后继续追资金平台推送 |
| loki 推资金平台 | `com.xhqb.loki.funds.platform.sharingagreement.http.HttpService#shareAgreement` | `[协议共享]推送协议签约请求体`、`[协议共享]推送协议签约结果为` | `serviceName:"loki-webapp" AND message:"[协议共享]推送协议签约" AND message:"{loanApplyNo}"` | HTTP 请求体、资金平台返回 | 判断资金平台是否接收成功 |

## 重签和还款签约补充

这部分只作为签约模块的补充排查，不替代自营/API 主链路。用户明确问还款发起、扣款成功、结清时，按 `repay.md` 主线查询。

| 场景 | 推荐查询 | 说明 |
|------|----------|------|
| 重新签约/RESIGN | `serviceName:"h5-loan" AND message:"[签约查询]cid" AND message:"签约查询请求为" AND message:"{value}"` | 默认自营首查；必要时再用同一 `cid/银行卡/signChannel` 补查 `order` 的 `SignServiceImpl#query(scene="RESIGN")` |
| 还款失败提示重签 | `serviceName:"order" AND message:"{cid}" AND message:"SIGNING_ISSUE"` | 结合还款失败日志判断，不要只凭提示文案下结论 |
| 支付协议失效 | `serviceName:"order" AND message:"{cid或contractNo}" AND (message:"支付协议失效" OR message:"签约失效")` | 命中后继续查签约查询和协议状态 |
| 借款签约失败 | `serviceName:"order" AND message:"{orderId}" AND (message:"SINGFAIL" OR message:"PRESIGN" OR message:"签约失败")` | 和下单链路交叉判断，避免把下单拒绝误判为签约失败 |
| 全渠道禁闭并发提示 | `serviceName:"order" AND message:"{cid}" AND message:"全渠道禁闭"` | 全渠道禁闭和重新签约可能并发出现，不要直接写成因果 |

常见判断：

- `RESIGN` 查询很多不一定异常，APP 可能轮询签约状态。
- 签了部分渠道仍提示重签，可能是仍有渠道未签，或重签缓存未过期。
- 重签缓存通常按分钟级时间窗口生效，签约成功后缓存不一定立即失效；10 分钟内重复看到重签提示时，优先确认缓存和剩余未签渠道。
- 全渠道禁闭和重新签约可能在同一时间窗口被 APP 并发触发，不能直接写成"禁闭导致重签"或"重签导致无法借款"。
- 还款失败提示重签时，先确认是否存在支付协议失效、银行卡协议过期或扣款失败缓存；不要把还款请求时间当成签约/扣款成功时间。
- `SINGFAIL/PRESIGN` 要结合订单状态和支付/资方签约结果判断，不能只按订单状态下最终根因。

## 健康检查

签约健康检查属于统计模式，必须遵守主控的完整性和采样输出规则。先按用户目标区分自营签约、API 渠道签约、协议共享；未指定时按自营优先，并把 API/协议共享作为背景风险分区输出。

| 场景 | 查询 SQL | 说明 |
|------|----------|------|
| 自营签约 ERROR | `serviceName:"h5-loan" AND level:"ERROR" AND (message:"[签约查询]" OR message:"[签约申请]" OR message:"[签约确认]" OR message:"[签约绑卡]")` | 自营签约链路异常主查 |
| 自营签约 WARN | `serviceName:"h5-loan" AND level:"WARN" AND (message:"[签约查询]" OR message:"[签约申请]" OR message:"[签约确认]" OR message:"[签约绑卡]")` | 自营签约链路告警补充 |
| API 签约 ERROR | `serviceName:"order" AND level:"ERROR" AND (message:"[卡片校验]" OR message:"[签约申请]" OR message:"[签约确认]")` | API 渠道签约异常主查 |
| API 签约 WARN | `serviceName:"order" AND level:"WARN" AND (message:"[卡片校验]" OR message:"[签约申请]" OR message:"[签约确认]")` | API 渠道签约告警补充 |
| 协议共享 ERROR | `(serviceName:"order" OR serviceName:"loki-webapp") AND level:"ERROR" AND message:"[协议共享]"` | 协议号同步 loki/资金平台异常 |
| 协议共享 WARN | `(serviceName:"order" OR serviceName:"loki-webapp") AND level:"WARN" AND message:"[协议共享]"` | 协议共享告警补充 |

## 输出要求

结论必须说明：

- 用户问题属于自营签约、API 渠道签约、协议共享、重新签约还是还款签约补充。
- 查到的标识符：`cid/orderId/contractNo/traceId/applyId/agreementNo/loanApplyNo`，以及手机号、身份证号、银行卡号是否只是定位入口。
- 签约查询、签约申请、签约确认、签约绑卡、协议生成/共享各节点是否命中。
- 关键状态：`needSign`、`handle`、`signStatus`、`needSignCount`、`notSignChannel`、`signChannel`、`agreementType`、`agreementNo`、`isCardBind`。
- 是否存在并发锁、短信申请缓存、协议通知频控、重签缓存或全渠道禁闭等时间窗口/并发因素。
- 下一步动作：用户继续确认/换卡/重签、等待缓存或频控过期、联系支付侧/资金侧，还是回订单/还款主链路继续排查。

## References

- `references/modules/order.md`：借款下单、订单状态和 `SINGFAIL/PRESIGN` 交叉判断
- `references/modules/order/re-sign-troubleshooting-20260519.md`：重签缓存、全渠道禁闭与重签并发关系实录
- `references/modules/repay.md`：还款成功/失败链路和扣款确认信号
