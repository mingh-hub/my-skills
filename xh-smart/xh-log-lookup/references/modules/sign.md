# 签约日志查询

专门处理签约相关问题：借款签约、还款签约、重新签约、银行卡/支付协议/代扣协议状态、签约失败和 APP 反复提示重签。CLS 执行、加载更多、飞书卡片优先输出和纯文本 fallback 统一交给 `xh-log-lookup` 主控。

## 意图分类

| 意图 | 识别特征 | 查询策略 |
|------|----------|----------|
| 借款签约 | 下单后待签约、签约失败、合同未生成、`SINGFAIL`、`PRESIGN` | 用 orderId/cid 查订单链路和签约状态 |
| 还款签约 | 还款代扣协议、支付协议失效、银行卡协议、还款失败后要求签约 | 查扣款失败、协议失效和 SIGNING_ISSUE |
| 重新签约 | 一直提示重新签约、RESIGN、needReSign、银行卡签约页反复弹出 | 查 RESIGN 查询、全渠道禁闭、签约渠道缓存和支付侧状态 |
| 绑卡/协议状态 | 绑卡失败、签约渠道未签、ZTX/宝付/易宝协议状态 | 查签约查询请求/结果和渠道返回 |

## 首查策略

| 用户提供 | 推荐首查语句 | 说明 |
|----------|--------------|------|
| `traceId` / 线程号 | `traceId:"{value}"` | 直接全链路，不加 `serviceName` |
| `cid` | `serviceName:"order" AND message:"{cid}" AND (message:"RESIGN" OR message:"签约")` | 重签/签约状态最常用 |
| `orderId` | `serviceName:"order" AND message:"{orderId}" AND (message:"签约" OR message:"SINGFAIL" OR message:"PRESIGN")` | 借款签约失败优先 |
| `contractNo` | `serviceName:"order" AND message:"{contractNo}" AND (message:"协议" OR message:"扣款失败" OR message:"签约")` | 还款协议问题优先 |
| 手机号 / `phone` / `bankPhone` | `serviceName:"order" AND message:"{phone}"` | 先定位 cid/orderId/contractNo 或签约请求，再按稳定标识符查签约/RESIGN；不要只凭手机号下结论 |
| 身份证号 / `idCard` / 证件号 | `serviceName:"order" AND message:"{idCard}"` | 先定位客户、订单或签约请求；如身份证号被脱敏导致无结果，改查手机号/cid/orderId/contractNo |

如果中文条件导致 URL 查询不稳定，优先用 ASCII 标识符值搜，再从 `cls_query.py` 提取全文中过滤 `签约`、`RESIGN`、`SIGNING_ISSUE` 等关键词。

手机号和身份证号属于定位入口，不是最终诊断证据；查到关联 cid/orderId/contractNo 后，必须继续用稳定标识符追签约链路。

## 核心流程链路追踪模版

推荐查询执行前先用 `方法入口` 校验代码锚点；不匹配时降级到 `serviceName:"order" AND message:"{标识符}"` 并重新 grep 当前代码。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 重签查询 | `com.xhqb.order.biz.service.impl.SignServiceImpl#query` | `[签约查询]查询签约场景`、`RESIGN` | `serviceName:"order" AND message:"{cid}" AND message:"RESIGN"` | | RESIGN 是稳定枚举，优先用 cid 值搜后过滤 |
| 签约渠道查询 | `com.xhqb.order.biz.service.impl.SignServiceImpl#query` | `[签约查询]查询签约渠道结果`、`调用支付签约查询结果` | `serviceName:"order" AND message:"{cid}" AND message:"签约查询"` | | 支付侧查询日志也可能在 signchannel/CtcfPaymentOService |
| 签约失效 | `com.xhqb.order.biz.service.handle.InvalidAgreementHandler#process` | `InvalidAgreementHandler`、`支付协议失效`、`签约失效` | `serviceName:"order" AND message:"{cid}" AND message:"签约失效"` | | 锚点不匹配时先搜 cid/contractNo |
| 还款失败触发重签 | `com.xhqb.order.biz.service.impl.OrderOthersServiceImpl#getRepayFailMessage` | `SIGNING_ISSUE`、`getRepayFailMessage` | `serviceName:"order" AND message:"{cid}" AND message:"SIGNING_ISSUE"` | | 该入口是失败文案映射，需结合还款失败日志判断 |
| 代扣/划扣失败 | `com.xhqb.order.biz.service.impl.AgreementPayServiceImpl#cacheNeedReSignInfo` | `cacheNeedReSignInfo`、`扣款失败` | `serviceName:"order" AND message:"{cid}" AND message:"扣款失败"` | | cid 查不到时改用 orderId/contractNo |
| 借款签约失败 | `com.xhqb.order.biz.service.impl.loan.LoanServiceImpl#loanOrder` | `SINGFAIL`、`PRESIGN`、`签约失败`、`contractNo:null` | `serviceName:"order" AND message:"{orderId}" AND message:"签约"` | | 和下单链路交叉判断，避免把下单拒绝误判为签约失败 |
| 全渠道禁闭并发提示 | `com.xhqb.order.biz.service.impl.BeforeLoanOrderServiceImpl#queryFrozenFundListByCid` | `queryFrozenFundListByCid`、`全渠道禁闭结果`、`全渠道禁闭` | `serviceName:"order" AND message:"{cid}" AND message:"全渠道禁闭"` | | 全渠道禁闭和重签是并发提示，不直接写因果 |

## 诊断流程

### 借款签约

1. 用 orderId/cid 查订单链路，确认是否停在 `PRESIGN`、`SINGFAIL` 或合同号为空。
2. 查同一 traceId 下是否有签约请求、签约结果、资方/支付侧返回。
3. 区分“签约失败”与“下单被拒”：如果无合同号但已有风控/资金路由拒绝，优先回业务主链路。
4. 输出订单状态、签约状态、是否生成合同、下一步需要用户操作还是后端/支付侧处理。

### 还款签约

1. 用 contractNo/orderId/cid 查还款失败链路。
2. 找 `SIGNING_ISSUE`、`InvalidAgreementHandler`、`AgreementPayServiceImpl`、`扣款失败`。
3. 确认是否是支付协议失效、银行卡协议过期、代扣失败缓存，还是单次支付失败。
4. 不要把“还款请求时间”当成签约/扣款成功时间；成功信号仍以还款模块成功日志为准。

### 重新签约

1. 先查 `serviceName:"order" AND message:"{cid}" AND message:"RESIGN"`。
2. 查 `SignService.query(scene="RESIGN")` 的请求和结果，确认涉及哪些卡和渠道。
3. 并行查全渠道禁闭：`queryFrozenFundListByCid`、`allRefuse:true`、`全渠道禁闭结果`。
4. 如果全渠道禁闭为 true，说明“无法借款”和“请重新签约”可能是并发提示，不要认定禁闭导致重签。
5. 如果不禁闭，再查协议失效、还款失败、`SIGNING_ISSUE` 和 `RESIGN_CACHE_CHANNEL` 缓存。
6. 关注 ReSignChannel 10 分钟缓存：签约成功后缓存未必立即失效，用户可能短时间内继续看到重签提示。

## 常见结论

| 现象 | 结论方向 |
|------|----------|
| RESIGN 查询很多 | 不一定异常，APP 可能轮询签约状态 |
| 全渠道禁闭和重签同时出现 | 两套独立检查并发，不要写成因果关系 |
| 签了部分渠道仍提示重签 | 可能还有渠道未签，或 RESIGN 缓存未过期 |
| `SINGFAIL` | 借款签约失败或用户未完成签约，继续查支付/资方签约结果 |
| 支付协议失效 | 需要重新签约或支付侧同步协议状态 |
| 还款失败提示重签 | 查 `SIGNING_ISSUE` 和扣款失败链路 |

## 输出要求

结论必须说明：

- 用户问题属于借款签约、还款签约还是重新签约
- 查到的标识符：cid/orderId/contractNo/traceId，以及用于定位的手机号/身份证号是否命中
- 签约请求、渠道查询、支付协议、全渠道禁闭各自是否命中
- 是否存在缓存或时间窗口限制
- 应该用户操作、等待缓存过期、等待禁闭解封，还是联系支付/资方侧

## References

- `references/modules/sign/re-sign-troubleshooting-20260519.md`：重新签约、全渠道禁闭、RESIGN 缓存实录
- `references/modules/order/order-status-glossary.md`：订单签约状态如 `PRESIGN`、`SINGFAIL`
- `references/modules/repay.md`：还款成功/失败链路和扣款确认信号
