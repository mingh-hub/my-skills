# 借款申请（协助创建借款申请模块SKILL说明文档）

`借款申请`流程主要包含`借款首页`、`借款能力`、`借款试算（借款内容）`页面，覆盖`借款首页查询`、`导流`、`预借款`、`借款能力校验`、`借款内容查询`、`权益展示`、`权益勾选及申请`、`试算`、`下单检查`、`申请借款`、`签约绑卡等业务`

## 借款首页

客户登录成功会进入首页，会调下面的接口判断是走`自营首页`还是`轻资产首页`

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

## 借款试算页（借款内容页）
