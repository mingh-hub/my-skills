# 借款申请（协助创建借款申请模块SKILL说明文档）

`借款申请`流程主要包含`借款首页`、`借款能力`、`借款试算（借款内容）`页面，覆盖`借款首页查询`、`导流`、`预借款`、`借款能力校验`、`借款内容查询`、`权益展示`、`权益勾选及申请`、`试算`、`下单检查`、`申请借款`、`签约绑卡等业务`

## 借款首页

>客户登录成功会进入首页，会调下面的接口判断是走`自营首页`还是`轻资产首页`

```java
com.xhqb.weixinh5api.biz.service.web.BasicInfoController#queryBasicMain
```

- 入口日志：`serviceName:"weixin-h5api" AND message:"BasicInfoController.queryBasicMain cid" AND message:{cid}`
- 结果日志：`serviceName:"weixin-h5api" AND message:"查询卡片信息最终参数为" AND message:{traceId}`，`traceId`需要先根据`入口日志`定位
- 针对这个接口返回有一部分字段需要重点关注，根据返回字段值的不同，前端走不通的流程。

  |字段名|说明|
  |------|------|
  |`applyStatus`|客户审批状态：`PASS`-审批通过，`REFUSE`-审批拒绝`PRE`-未进入审批，`IN`-进入审批，`ING`-审批中，`PAUSE`-暂停审批|
  |`appletApproval`|小程序审批状态：`Y`-小程序审批中，`N`-未进入小程序审批，`0`-小程序审批中并且导流关闭，`1`-未进入小程序审批并且导流开启，`wxf8f5586bf4da64ff`-备份小程序|
  |`cardDetailList.cardEnum`|查`cardDetailList`列表中第一项元素，返回卡类型：`SELF_SUPPORT`-自营首页，`QZC_CODE`-轻资产首页；`自营首页`包含`小程序首页`和`H5首页`|
  |`cardDetailList.creditAmount`|授信总额度|
  |`cardDetailList.availableAmount`|当前可用额度|

## 借款试算页/借款内容页

> 借款试算页初始化会先调借款能力校验接口（`/h5-loan/loan/loanAbility`），校验通过后进入试算页面，页面内容是调借款内容接口（`/h5-loan/loan/loanContent`）获取，客户点击试算页的借款申请则会调用下单检查（`/h5-loan/loan/loanCheck`）及检查通过后的下单接口（`/h5-loan/loan/loan`）

| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 关键指标 | 说明 |
| ------ | ------ | ------ | ------ | ------ | ------ |
|借款能力校验|`/h5-loan/loan/loanAbility`|`[借款能力]客户cid`|<ul><li>入口日志：`serviceName:"h5-loan" AND message:"[借款能力]客户cid" AND message:"借款流程渠道" AND message:"{cid}"`</li><li>出口日志：`serviceName:"h5-loan" AND message:"[借款能力]客户cid" AND message:"借款能力查询结果" AND message:"{cid}"`</li></ul>|**返回结果**：<ul><li>`diversion`：`true`-导流，`false`-不导流</li><li>`canLoan`：`true`-允许借款，`false`-不允许借款</li></ul>|`diversion=true`表示需要导流就会走API渠道导流业务，不能走自营借款业务，走自营借款流程时再看`canLoan`字段，如果为`false`，不能借款，再看`needUpdateIdentityPic`是否为`true`，为`true`说明客户身份证已过期或即将过期，需要先去更新身份证信息；`canLoan`字段为`true`表示可以借款，会调`/loanContent`服务查询借款内容|
|借款内容查询|`/h5-loan/loan/loanContent`|`[借款内容]cid`|<ul><li>入口日志：`serviceName:"h5-loan" AND message:"[借款内容]cid" AND message:"请求" AND message:"{cid}"`</li><li>出口日志：`serviceName:"h5-loan" AND message:"[借款内容]cid" AND message:"结果" AND message:"{cid}"`</li></ul>|**请求入参：**<ul><li>`applyAmount`：借款试算金额</li><li>`applyStage`：借款试算期数</li><li>`couponCode`：优惠券code</li><li>`choiceMember`：是否勾选会员，`true`-勾选</li><li>`equityPackageId`：权益包id</li><li>`chooseLhk`：是否勾选乐活卡，`true`-勾选</li></ul>**返回结果：**<ul><li>`couponInfoMap`：优惠券列表信息，`key=valid`表示当前有效的优惠券列表信息</li><li>`termInfoList`：用户可选期数信息</li><li>`loanTrialInfo`：还款试算信息</li></ul>|借款能力校验通过后，前端会调借款内容查询服务，在借款试算页/借款内容页展示借款信息，包含期数选择，可选优惠券，权益信息，试算还款计划信息展示等|
|卡片信息查询|`/h5-loan/loan/loanMarketCard`|`查询营销卡片请求`|<ul><li>入口日志：`serviceName:"h5-loan" AND message:"查询营销卡片请求" AND message:"{cid}"`</li><li>出口日志：`serviceName:"h5-loan" AND message:"查询营销卡片结果" AND message:"{cid}"`</li></ul>|**请求入参：**<ul><li>`applyAmount`：借款试算金额</li><li>`loanTerm`：借款试算期数</li><li>`chooseMember`：是否勾选会员，`true`-勾选</li><li>`orderStagesChangeMark`：订单期数转换标识，`true`-支持转期，默认不支持</li></ul>**返回结果：**<ul><li>`flowerType`：展示花卡类型（0:不展示、1:尊享卡、2:权益包、3:尊享月卡、4:京东电商权益）</li><li>`equityPackage`：权益包信息，不为空表示展示尊享卡</li><li>`lhkCardBean`：乐活卡信息，不为空表示展示乐活卡</li><li>`newTrialPage`：是否是新试算页，`true`-是新试算页</li></ul>|查询客户的卡片信息，包括乐活卡，权益包，会员信息，尊享卡，拒就赔等信息|
|借款校验|`/h5-loan/loan/loanCheck`|`[借款校验]cid`|<ul><li>入口日志：`serviceName:"h5-loan" AND message:"[借款校验]cid" AND message:"请求" AND message:"{cid}"`</li><li>出口日志：`serviceName:"h5-loan" AND message:"[借款校验]cid" AND message:"结果" AND message:"{cid}"`</li></ul>|**返回结果：**<ul><li>`notAvailBank`：卡是否不可用，`true`-不可用，`false`-可用</li><li>`supportBanks`：支持的银行卡列表</li></ul>|客户下单前的信息校验，包括`签约检查`，`银行卡限额校验`，`身份证状态检查`，`是否需要补充人脸`，`是否需要补充联系人`，`是否需要交易密码`，`查询是否需要学生声明`，`禁闭期查询`等业务，核心处理逻辑在`com.xhqb.h5loan.biz.service.service.check.userinfo.scene.LoanCheckStrategy#check`|
|借款下单||||||
