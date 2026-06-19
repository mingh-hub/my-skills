# 借款申请日志查询

`apply` 模块处理正式下单之前的客户借款申请链路:用户登录后进入借款首页、借款能力预检、借款内容页/试算页、提交借款申请前后的行为轨迹和失败原因定位。包含**自营借款**和**保费分期**两条独立申请前流程。CLS 执行、加载更多、飞书卡片优先输出和纯文本 fallback 统一交给 `xh-log-lookup` 主控工具。

## 模块定位

- **申请前链路**:用户登录、访问借款首页、借款能力校验、进入借款内容页/试算、提交借款申请时的页面和接口行为轨迹,默认走 `apply` 模块。
- **正式下单链路**:订单生成、下单请求、下单拦截、反欺诈、订单状态、下单成功/失败统计,继续走 `references/modules/order.md`。
- **放款链路**:资金路由、放款等,继续走 `references/modules/loan.md`。

## 涉及服务

主服务:`h5-loan`(借款能力/内容/校验/下单、保费分期),`weixin-h5api`(借款首页)。

常见关联服务:`order`、`cif`、`account`、`datainquiry`、`app-server`。

> 关联服务只作为后续链路钻取范围;首查应优先从 `h5-loan` / `weixin-h5api` 的申请前入口日志定位 `cid/traceId/mobileNo/identityNo` 等桥接标识。

## 意图边界

- **行为轨迹查询**:用户问"客户从登录到申请借款的轨迹"、"借款首页有没有进来"、"试算页卡在哪"、"客户申请前做了什么"、"借款失败"时,按 `apply` 查询。
- **申请前失败原因**:用户问"借款内容页失败"、"借款试算失败"、"借款能力校验不通过"、"首页不展示借款入口"、"首页不展示借款额度"时,按 `apply` 查询。
- **默认自营**:用户未明确说明渠道时,默认按自营借款申请查询,锚点用 `[借款能力]`/`[借款内容]`/`[借款校验]`/`[借款申请]`,主入口在 `LoanController`。
- **保费分期分流**:用户明确说"保费分期"、"保费"、"保单分期"、"保费分期借款"、"保费分期试算"、"保费分期校验不通过"时,按保费分期流程查询,锚点全部带 `[保费分期]` 前缀,主入口在 `PremiumInstallmentLoanController`。保费分期和自营是两套接口、两套锚点,不能混查。
- **提交后正式下单**:用户明确问"下单失败"、"订单为什么没生成"、"反欺诈拦截"、"下单成功/失败统计"时,按 `order.md` 查询;`apply` 只负责定位提交前后是否已进入下单链路。
- **签约/绑卡/还款/权益**:客户申请过程中如果跳转到签约、绑卡、权益勾选或还款补充链路,应按对应模块继续钻取,`apply` 只保留前置轨迹证据。

## 首查策略

手机号、身份证号等自然标识只能作为定位入口。查到 `cid/traceId` 后,必须继续用稳定标识符追踪申请前链路;`orderId` 只作为已进入正式下单后的桥接标识,不作为 apply 首查主入口。

| 用户提供 | 推荐首查语句 | 说明 |
|----------|--------------|------|
| `traceId` | `traceId:"{value}"` | 全链路直查,不加 `serviceName` |
| `cid`（自营） | `serviceName:"h5-loan" AND message:"[借款" AND message:"{cid}"` | 匹配 `[借款能力]/[借款内容]/[借款校验]/[借款申请]` 全链路 |
| `cid`（保费分期） | `serviceName:"h5-loan" AND message:"[保费分期]" AND message:"{cid}"` | 用户明确保费分期时优先,`[保费分期]` 前缀天然区分 |
| `cid`（借款首页） | `serviceName:"weixin-h5api" AND message:"BasicInfoController.queryBasicMain cid" AND message:"{cid}"` | 判断是否进入借款首页及首页展示结果 |
| 手机号 | 先在 `weixin-h5api` 或 `h5-loan` 定位 `cid`,再按 `cid` 查 apply 链路 | 手机号只是定位入口 |
| 身份证号 | 先定位 `cid`,再按 `cid` 查 apply 链路 | 身份证可能脱敏,不能只凭无结果下结论 |

## 自营借款申请链路

自营借款申请流程:借款首页 -> 借款能力校验 -> 借款内容页 -> 卡片信息查询 -> 借款校验 -> 提交申请/下单。借款首页在 `weixin-h5api`,其余节点在 `h5-loan` 的 `LoanController`(类映射 `/loan`)。这条流程都是自营业务,不含 API 渠道业务。

> 借款内容页/试算页初始化会先调借款能力校验(`/loan/loanAbility`),校验通过后调借款内容(`/loan/loanContent`)渲染试算页;客户点击借款申请会先调下单检查(`/loan/loanCheck`),通过后调下单(`/loan/loan`)。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 借款首页 | `com.xhqb.weixinh5api.biz.service.web.BasicInfoController#queryBasicMain` | `BasicInfoController.queryBasicMain cid`、`【queryBasicMain】查询卡片信息最终参数为` | <ul><li>入口:`serviceName:"weixin-h5api" AND message:"BasicInfoController.queryBasicMain cid" AND message:"{cid}"`</li><li>出口:`serviceName:"weixin-h5api" AND message:"【queryBasicMain】查询卡片信息最终参数为" AND message:"{cid}"`（中文锚点，需浏览器注入）</li></ul> | `applyStatus`、`appletApproval`、`cardDetailList.cardEnum`、`creditAmount`、`availableAmount` | 判断客户是否进入借款首页、走自营还是轻资产、首页额度展示。出口锚点必须带 `【queryBasicMain】` 前缀，避免命中其它方法的同名日志 |
| 借款能力校验 | `com.xhqb.h5loan.biz.service.controller.LoanController#loanAbility` | `[借款能力]客户cid`、`借款流程渠道`、`借款能力查询结果` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[借款能力]客户cid" AND message:"借款流程渠道" AND message:"{cid}"`</li><li>出口:`serviceName:"h5-loan" AND message:"[借款能力]客户cid" AND message:"借款能力查询结果" AND message:"{cid}"`</li></ul> | `diversion`、`canLoan`、`needUpdateIdentityPic` | 试算页初始化的能力预检,判断是否导流、是否允许借款、身份证是否过期 |
| 借款内容页 | `com.xhqb.h5loan.biz.service.controller.LoanController#loanContent` | `[借款内容]cid`、`请求`、`结果` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[借款内容]cid" AND message:"请求" AND message:"{cid}"`</li><li>出口:`serviceName:"h5-loan" AND message:"[借款内容]cid" AND message:"结果" AND message:"{cid}"`</li></ul> | 入参 `applyAmount`、`applyStage`、`couponCode`、`choiceMember`、`equityPackageId`、`chooseLhk`;返回 `couponInfoMap`、`termInfoList`、`loanTrialInfo` | 能力校验通过后渲染试算页,含期数、优惠券、权益、还款试算 |
| 卡片信息查询 | `com.xhqb.h5loan.biz.service.controller.LoanController#loanMarketCard` | `查询营销卡片请求`、`查询营销卡片结果`、`查询营销卡片业务异常`、`查询营销卡片异常` | <ul><li>入口:`serviceName:"h5-loan" AND message:"查询营销卡片请求" AND message:"{cid}"`（中文锚点，需浏览器注入）</li><li>出口:`serviceName:"h5-loan" AND message:"查询营销卡片结果" AND message:"{cid}"`</li></ul> | 入参 `applyAmount`、`loanTerm`、`chooseMember`、`orderStagesChangeMark`;返回 `flowerType`、`equityPackage`、`lhkCardBean`、`newTrialPage` | 查询乐活卡、权益包、会员、尊享卡、拒就赔等营销卡片;异常看 `查询营销卡片业务异常/异常` |
| 借款校验 | `com.xhqb.h5loan.biz.service.controller.LoanController#loanCheck` | `[借款校验]cid`、`请求`、`结果` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[借款校验]cid" AND message:"请求" AND message:"{cid}"`</li><li>出口:`serviceName:"h5-loan" AND message:"[借款校验]cid" AND message:"结果" AND message:"{cid}"`</li></ul> | `notAvailBank`、`supportBanks` | 自营下单前校验:签约检查、银行卡限额、身份证状态、人脸/联系人/交易密码、学生声明、禁闭期等;核心逻辑 `LoanCheckStrategy#check` |
| 提交申请/下单 | `com.xhqb.h5loan.biz.service.controller.LoanController#loan` | `[借款申请]cid`、`请求`、`结果`、`[借款申请]调用order请求参数` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[借款申请]cid" AND message:"请求" AND message:"{cid}"`</li><li>出口:`serviceName:"h5-loan" AND message:"[借款申请]cid" AND message:"结果" AND message:"{cid}"`</li></ul> | 入参 `applyAmount`、`applyStagesNbr`、`applyCardNo`、`loanChannel`、`purpose`;返回 `orderId`、`resultCode`（`SUCCESS_RESPONSE`-成功）、`buyEquity` | 自营下单请求,`h5-loan` 调 `order` 的 dubbo 下单服务;提取 `orderId` 后继续按 `order.md` 排查 |

## 保费分期申请链路

保费分期是**独立**的申请前流程,主入口 `com.xhqb.h5loan.biz.service.controller.PremiumInstallmentLoanController`(类映射 `/premiumLoan`),日志锚点全部带 `[保费分期]` 前缀。流程:借款能力校验 -> 借款内容试算 -> 借款校验。和自营是两套接口、两套锚点,排查时不要和自营 `[借款能力]/[借款内容]/[借款校验]` 混查。

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
|------|----------|----------------|----------|----------|------|
| 借款能力校验 | `PremiumInstallmentLoanController#loanAbility`（`/premiumLoan/loanAbility`） | `[保费分期][借款能力]查询, cid`、`[保费分期][借款能力]结果, cid`、`查询用户保费分期信息参数缺失`、`查询用户保费分期信息失败` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[保费分期][借款能力]查询" AND message:"{cid}"`</li><li>出口:`serviceName:"h5-loan" AND message:"[保费分期][借款能力]结果" AND message:"{cid}"`</li></ul> | `result`、是否参数缺失、是否查询失败 | 保费分期能力预检;参数缺失或查询失败会落 ERROR,优先看缺参/下游返回 |
| 借款内容试算 | `PremiumInstallmentLoanController#loanCent`（`/premiumLoan/loanCent`） | `[保费分期][借款内容]试算, cid`、`[保费分期][借款内容]结果, cid`、`[保费分期借款内容]借款缓存信息key` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[保费分期][借款内容]试算" AND message:"{cid}"`</li><li>出口:`serviceName:"h5-loan" AND message:"[保费分期][借款内容]结果" AND message:"{cid}"`</li></ul> | 入参 `applyAmount`、`applyStage`;返回试算 `result`;缓存 key | 注意 mapping 是 `/loanCent`（非 `loanContent`）;缓存日志变体 `[保费分期借款内容]`（无中括号分隔） |
| 借款校验 | `PremiumInstallmentLoanController#loanCheck`（`/premiumLoan/loanCheck`） | `[保费分期][借款校验]开始校验`、`[保费分期][借款校验]结果, cid`、`在途/在贷订单数`、`封禁期查询结果`、`逾期信息查询结果`、`校验通过`、`保存拦截信息` | <ul><li>入口:`serviceName:"h5-loan" AND message:"[保费分期][借款校验]开始校验"`</li><li>出口:`serviceName:"h5-loan" AND message:"[保费分期][借款校验]结果" AND message:"{cid}"`</li></ul> | `loanCheckResult`、`orderAmount`、`frozenResult`、`overdueResult`、`rejectMsg` | 保费分期下单前校验:在途/在贷订单数、封禁期、逾期、签约(`[保费分期][借款校验][签约]`);被拦截看 `保存拦截信息` 的 `rejectMsg` |

## 判断规则

### 借款首页（queryBasicMain）

- `cardDetailList` 取列表第一项的 `cardEnum`:`SELF_SUPPORT`-自营首页,`QZC_CODE`-轻资产首页。自营首页又分小程序首页和 H5 首页。判断客户走自营还是轻资产以此为准。
- `applyStatus` 是客户审批状态:`PASS`-审批通过,`REFUSE`-审批拒绝,`PRE`-未进入审批,`IN`-进入审批,`ING`-审批中,`PAUSE`-暂停审批。
- `appletApproval` 是小程序审批状态:`Y`-小程序审批中,`N`-未进入小程序审批,`0`-小程序审批中且导流关闭,`1`-未进入小程序审批且导流开启。
- 出口锚点必须用带 `【queryBasicMain】` 前缀的 `查询卡片信息最终参数为`;同服务还有不带前缀的同名日志属其它方法,不要混用。

### 借款能力校验（loanAbility）

- `diversion=true` 表示需要导流,客户会走 API 渠道导流业务,**不能**走自营借款;此时不要继续按自营 `loanContent` 判断失败。
- 走自营流程时看 `canLoan`:`false` 不允许借款,再看 `needUpdateIdentityPic`,为 `true` 说明身份证已过期或即将过期,需先更新身份证信息;`canLoan=true` 才会调 `loanContent`。

### 自营 vs API vs 保费分期

- 自营借款的能力校验、内容页、卡片信息、借款校验、下单(`[借款能力]/[借款内容]/查询营销卡片/[借款校验]/[借款申请]`)都是自营业务,不含 API 渠道业务;API 渠道导流由 `diversion=true` 触发,属其它链路。
- 保费分期和自营是两套接口、两套锚点。`[保费分期]` 前缀是天然分流器:用户问保费分期时只查带前缀的锚点,问自营时排除前缀,不能把保费分期的能力/试算/校验当成自营失败,反之亦然。
- 保费分期内容试算的 mapping 是 `/loanCent`(不是 `loanContent`),缓存日志还有无中括号分隔的变体 `[保费分期借款内容]`,grep 时两种都要覆盖。

### 试算与提交

- 试算页内容来自 `loanContent`,营销卡片(乐活卡/权益包/会员/尊享卡)来自 `loanMarketCard`,两者分开;卡片不展示先看 `查询营销卡片业务异常/异常`,不要直接归因 `loanContent`。
- 提交申请出口 `[借款申请]cid ... 结果` 命中且 `resultCode=SUCCESS_RESPONSE` 表示已进入下单;提取 `orderId` 后按 `order.md` 继续。`loanCheck` 不通过则不会进入 `loan`,先看 `[借款校验]` 结果,不要把校验拦截当成下单失败。

## 关键失败场景

| 现象 | 优先诊断 |
|------|----------|
| 登录后无法进入借款首页 | 查 `weixin-h5api` 的 `BasicInfoController.queryBasicMain cid`,确认入口是否命中;命中后看 `【queryBasicMain】查询客户信息失败` 等是否异常 |
| 借款首页无入口/卡片异常/不展示额度 | 查 `【queryBasicMain】查询卡片信息最终参数为`,确认 `cardEnum`(自营/轻资产)、`applyStatus`、`creditAmount`/`availableAmount`;`查询客户账户额度信息失败`/`获取卡片信息失败` 说明下游取数异常 |
| 借款能力校验不通过 | 查 `[借款能力]客户cid ... 借款能力查询结果`,看 `diversion`(是否被导流到 API)、`canLoan`、`needUpdateIdentityPic`(身份证过期) |
| 借款内容页失败 | 查 `[借款内容]cid ... 结果`,确认 `termInfoList`/`couponInfoMap`/`loanTrialInfo` 是否正常返回;能力校验未过则不会进内容页 |
| 营销卡片/权益不展示 | 查 `查询营销卡片结果`,异常看 `查询营销卡片业务异常`/`查询营销卡片异常`;和 `loanContent` 分开判断 |
| 借款校验拦截 | 查 `[借款校验]cid ... 结果`,确认签约/银行卡限额/身份证/人脸/联系人/交易密码/学生声明/禁闭期哪项拦截;核心逻辑 `LoanCheckStrategy#check` |
| 提交申请后未进入下单 | 查 `[借款申请]cid ... 结果` 的 `resultCode`;命中 `[借款申请]调用order请求参数` 但无结果,用 `traceId/orderId` 联动 `order.md` |
| 保费分期能力/试算/校验失败 | 查带 `[保费分期]` 前缀的对应锚点;能力查 `查询用户保费分期信息参数缺失/失败`,校验拦截看 `保存拦截信息` 的 `rejectMsg`,不要和自营锚点混查 |

## 健康检查

apply 健康检查属于统计模式,必须遵守主控的完整性和采样输出规则。先按用户目标区分自营借款、保费分期、借款首页;未指定渠道时按自营优先,把保费分期作为背景风险分区输出。

| 场景 | 查询 SQL | 说明 |
|------|----------|------|
| 自营申请前链路 ERROR | `serviceName:"h5-loan" AND level:"ERROR" AND (message:"[借款能力]" OR message:"[借款内容]" OR message:"[借款校验]" OR message:"[借款申请]")` | 只统计自营申请前链路错误 |
| 自营申请前链路 WARN | `serviceName:"h5-loan" AND level:"WARN" AND (message:"[借款能力]" OR message:"[借款内容]" OR message:"[借款校验]" OR message:"[借款申请]")` | 自营申请前链路告警补充 |
| 保费分期链路 ERROR | `serviceName:"h5-loan" AND level:"ERROR" AND message:"[保费分期]"` | 只统计保费分期申请前错误 |
| 保费分期链路 WARN | `serviceName:"h5-loan" AND level:"WARN" AND message:"[保费分期]"` | 保费分期申请前告警补充 |
| 借款首页 ERROR | `serviceName:"weixin-h5api" AND level:"ERROR" AND message:"queryBasicMain"` | 首页查询链路异常 |
| 提交申请入口量/结果量 | `serviceName:"h5-loan" AND message:"[借款申请]cid"` | 仅用于申请前到正式下单的桥接观察,结果按 `请求`/`结果` 拆分统计 |

## 输出要求

结论必须说明:

- 用户问题属于借款首页、借款能力校验、借款内容页/试算、借款校验、提交申请,还是已经进入正式下单;以及走的是**自营**还是**保费分期**流程。
- 查到的标识符:`cid/traceId`,以及手机号、身份证号是否只是定位入口;如果已经进入正式下单,再说明桥接 `orderId`。
- 按时间顺序输出客户行为轨迹:登录/首页 -> 能力校验 -> 内容页/试算 -> 卡片信息 -> 借款校验 -> 提交申请 -> 正式下单桥接(保费分期为:能力校验 -> 内容试算 -> 借款校验)。
- 关键状态:首页 `cardEnum`/`applyStatus`/`appletApproval`、能力校验 `diversion`/`canLoan`/`needUpdateIdentityPic`、借款校验 `notAvailBank`、提交 `resultCode`。
- 明确每个节点是否命中日志、返回是否成功、失败原因来自本服务还是下游服务。
- 如果已经进入正式下单,必须说明后续应按 `references/modules/order.md` 的下单链路继续排查。

## References

- `references/modules/order.md`:正式下单、订单生成、下单拦截和反欺诈链路
- `references/modules/sign.md`:申请过程中触发签约、绑卡、重签时继续排查
- `references/modules/benefit.md`:申请过程中触发权益、优惠券、乐活卡时继续排查
- `references/modules/loan.md`:下单成功后的资金路由、放款链路
