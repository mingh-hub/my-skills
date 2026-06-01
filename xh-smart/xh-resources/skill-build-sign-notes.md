# 签约模块（协助创建签约模块SKILL说明文档）

分为自营签约绑卡和API渠道签约绑卡两种业务模式，走两套不同的业务逻辑，查询时没有指定API渠道默认查自营

## 自营签约绑卡

业务流程：签约查询 -> 签约申请 -> 签约确认 -> 签约绑卡

### 业务场景

- 借款签约绑卡
- 新增签约绑卡
- 换绑卡
- 重签约
- 还款签约绑卡

### 核心业务入口

**签约查询**
这个接口主要是根据手机号和银行卡号来查询这张银行卡是否需要签约以及要签哪些渠道，上述业务场景都会先调这个查询判断是否需要签约**

```java
com.xhqb.h5loan.biz.service.controller.AgreementPayController#querySignSituation 
```

- 入口日志 `serviceName:"h5-loan" AND message:"[签约查询]cid" AND message:"签约查询请求为" AND message:"{value}"`，`value`可为`客户ID`,`手机号`,`银行卡号`
- 入参字段`scene`表示签约场景, 参考代码中的`com.xhqb.order.common.service.model.enums.SignSceneEnum`
- 返回结果中`needSign`判断是否需要签约,true-需要,false-不需要; 如果`needSign`为true, `signInfos`为需要签约的渠道集合
- 查询结果返回：
  - `needSign`返回`true`-需要签约，`false`-不需要签约
  - `handle="NEXTSTEP"`-会跳过签约，`handle="CHANGECARD"`-需要换卡
  - 如果`needSign=true`，`handle`是不会跳过签约也不会去换卡的
  - `signInfos.signStatus`：`UNSIGNED`-未签约，`SIGNED`-已签约，`UNWANTED`-不需要签约，`UNSIGNED`-签约失败

**签约申请**
**根据签约查询返回需要签约`needSign=true`时前端会调这个服务进行签约申请，根据手机号和银行卡号来进行申请**

```java
com.xhqb.h5loan.biz.service.controller.AgreementPayController#applySign
```

- 入口日志：`serviceName:"h5-loan" AND message:"[签约申请]cid" AND message:"签约申请请求" AND message:"{value}"`，`value`可为`客户ID`,`手机号`,`银行卡号`
- 申请成功`success=true`且`resultCode="SUCCESS_RESPONSE"`
- `applyId`签约申请ID，下面`签约绑卡`的入参

**签约确认**
**签约申请成功后，需要客户确认，会调这个接口**

```java
com.xhqb.h5loan.biz.service.controller.AgreementPayController#submitSign
```

- 入口日志：`serviceName:"h5-loan" AND message:"[签约确认]cid" AND message:"{cid}"`
- 入参中的`applyId`为`签约申请`返回的`applyId`

**签约绑卡**
**客户确认后会走签约绑卡的流程**
  
```java
com.xhqb.h5loan.biz.service.controller.AgreementPayController#confirmAndSaveCard
```

- 入口日志：`serviceName:"h5-loan" AND message:"[签约绑卡]cid" AND message:"请求" AND message:"{applyId}"`
- 入参中的`applyId`为`签约申请`返回的`applyId`且不能为空

## API渠道签约绑卡

### 业务场景

- API渠道新增绑卡
- API渠道换绑卡
- 借款前签约绑卡
- 还款/换卡签约绑卡
- 快捷绑卡协议通知

业务流程：卡片校验/签约查询 -> 返回未签约渠道 -> 签约申请 -> 短信确认签约 -> 再次卡片校验 -> 落卡/换卡

- API渠道会先调用`inspect`做卡片校验和签约过滤，判断卡是否可用、是否已绑、是否还有未签约渠道
- 如果存在未签约渠道，`inspect`会返回`needSignCount`和`notSignChannel`，渠道侧拿未签约渠道发起签约申请
- 签约确认成功只代表支付侧签约成功，还需要再次调用`inspect`，确认所有渠道都已签约后才会保存卡包或执行换卡
- `inspect`既是前置校验入口，也是签约完成后的落卡/换卡入口

### 核心业务入口

**卡片校验/签约查询**
**API渠道先通过这个入口校验四要素、卡行、绑卡状态，并查询当前卡是否还有未签约渠道**

```java
com.xhqb.order.biz.service.impl.api.CardInfoInspectServerImpl#inspect
```

- 入口日志：`serviceName:"order" AND message:"[卡片校验]" AND message:"api卡片校验参数" AND message:"{value}"`，`value`可为`客户ID`,`银行卡号`,`手机号`
- 签约查询结果日志：`serviceName:"order" AND message:"[卡片校验]" AND message:"当前签约的渠道信息为" AND message:"{value}"`
- 未签约渠道日志：`serviceName:"order" AND message:"[卡片校验]" AND message:"当前需要签约的渠道信息为" AND message:"{value}"`
- 换卡日志：`serviceName:"order" AND message:"[卡片校验]" AND (message:"换卡请求" OR message:"换卡结果") AND message:"{value}"`
- 异常日志：`serviceName:"order" AND message:"[卡片校验]" AND message:"卡片校验失败" AND message:"{value}"`
- 返回结果中重点关注：
  - `needSignCount`：需要签约的渠道数量
  - `notSignChannel`：未签约渠道集合，渠道侧通常取第一个未签约渠道发起签约申请
  - `isCardBind`：当前卡是否已经在本地卡包绑定
  - `failureCode="NOT_SUPPORT_CARD_LINE"`：卡行不支持

**签约渠道查询**
**`inspect`内部会把卡片信息转换为`QuerySignInfoReq`，调用这个服务查询支付侧签约状态**

```java
com.xhqb.order.biz.service.impl.SignServiceImpl#query
```

- 入口日志：`serviceName:"order" AND message:"[签约查询]" AND message:"查询签约场景" AND message:"{value}"`，`value`可为`客户ID`,`银行卡号`,`手机号`,`signScene`
- 查询结果日志：`serviceName:"order" AND message:"[签约查询]" AND message:"查询签约渠道结果" AND message:"{value}"`
- 支付侧查询日志：`serviceName:"order" AND message:"[签约查询]" AND (message:"调用支付签约查询请求" OR message:"调用支付签约查询结果") AND message:"{value}"`
- API渠道查询来源为`SignQueryFromEnum.API`
- 返回的`SignInfo`会通过`SignInfo.tranApiSign()`转换为外部渠道看到的`SignResult`
- 返回结果中重点关注：
  - `signChannel`：支付签约渠道
  - `signStatus`：是否已签约，`false`表示未签约
  - `fundPayChannel`：资方所需支付渠道/子渠道
  - `agreementType`：`API`或`H5`
  - `agreementNo`：签约协议号
  - `canSign`：当前渠道是否允许签约

**签约申请**
**渠道侧拿到`notSignChannel`后，通常取第一个未签约渠道组装`ApplySignReq`发起签约申请**

```java
com.xhqb.order.biz.service.impl.SignServiceImpl#apply
```

- 入口日志：`serviceName:"order" AND message:"[签约申请]" AND message:"签约申请请求内容" AND message:"{value}"`，`value`可为`客户ID`,`银行卡号`,`手机号`
- 并发控制日志：`serviceName:"order" AND message:"[签约申请]" AND message:"并发请求" AND message:"{银行卡号}"`
- 支付侧申请日志：`serviceName:"order" AND message:"[签约申请]" AND (message:"支付签约申请信息请求" OR message:"支付签约申请信息结果") AND message:"{value}"`
- 异常日志：`serviceName:"order" AND message:"[签约申请]" AND (message:"签约申请请求业务出错" OR message:"签约申请请求系统出错") AND message:"{value}"`
- 申请成功后重点关注：
  - `applyId`：签约申请ID，短信确认时使用
  - `agreementType`：默认`API`，支付返回H5表单时为`H5`
  - `formUrl/formParams`：H5签约时使用
- 控制点：
  - 用Redis对`银行卡 + 签约渠道`做50秒防并发
  - 锡商银行等特殊渠道可能限制60秒一次
  - 签约渠道配置不存在或不可用时会直接失败
  - 需要外部注册的渠道会先完成资方注册再调支付申请

**短信确认签约**
**渠道收到短信验证码后，调用确认接口完成支付侧签约**

```java
com.xhqb.order.biz.service.impl.SignServiceImpl#confirm
```

- 申请缓存日志：`serviceName:"order" AND message:"[签约确认]" AND message:"取得签约申请缓存为" AND message:"{applyId}"`
- 支付侧确认日志：`serviceName:"order" AND message:"[签约确认]" AND (message:"支付签约确认信息请求" OR message:"支付签约确认信息结果") AND message:"{applyId}"`
- 异常日志：`serviceName:"order" AND message:"[签约确认]" AND (message:"签约确认业务出错" OR message:"签约确认系统出错") AND message:"{value}"`
- 入参中的`applyId`必须是`签约申请`返回的`applyId`
- `confirm`会从缓存读取`applyId`对应的`ApplySignReq`，如果缓存不存在会返回“请先发起短信验证”
- 确认时`signChannel`必须和申请时一致，否则会要求重新发起短信验证
- 确认成功后会按签约渠道发布对应事件，并发布通用`SignData`签约成功事件
- 确认成功只代表支付侧签约完成，API渠道通常还要再次调用`inspect(BIND)`完成最终落卡/换卡

**协议通知**
**外部已经有协议号，或者快捷绑卡场景，可以直接通知生成协议**

```java
com.xhqb.order.biz.service.impl.SignServiceImpl#notifyProtocol
```

- 频控日志：`serviceName:"order" AND message:"notifyProtocol.redisKey" AND message:"{cid}"`
- 协议生成可结合签约确认后的协议MQ日志继续查：`serviceName:"order" AND message:"协议" AND message:"{cid或agreementNo}"`
- 该链路不再调支付确认，只负责按协议号生成协议MQ
- `payChannel=baofu`会被转换为`baofu#payChannel`
- 同一客户同一协议号一分钟内只能通知一次
