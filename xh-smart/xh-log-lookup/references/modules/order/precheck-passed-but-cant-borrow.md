# 预检通过但客户仍无法借款 — 排查指南

当所有预检接口返回成功（`canLoan:true`, `queryCanLoan success:true`, `h5-audit accessable:1`, T4提现门槛通过）但客户在页面上仍提示"无法借款"时使用。

## 典型的排查路径

### Step 1: 确认是否有实际下单提交

先用值搜查 order 服务日志是否包含下单入口：

```text
serviceName:"order" AND message:"[借款下单]下单请求为" AND message:"{cid}"
```

若无命中则客户只查看了页面，未实际提交借款。需要前端截图或前端报错信息才能进一步定位。

### Step 2: 检查 guideCheckAbility 的还款计划级别逾期检查

**这是最容易被忽略的盲区。**

代码入口：`CustomerLoanAvailableServiceImpl#guideCheckAbility`

```java
// 1. 查询当前所有在还订单(REPAYING/OVERDUE/EARLYREPAYING)
List<Order> orderList = orderMapper.queryCurrentOrderList(cid);
List<String> orderIdList = orderList.stream()
    .filter(o -> orderStatus in (REPAYING, OVERDUE, EARLYREPAYING))
    .map(Order::getId).collect(Collectors.toList());

if (CollectionUtils.isNotEmpty(orderIdList)) {
    // 2. 查询这些订单的所有还款计划的最大逾期天数
    int maxOverdueDays = orderRepayplanMapper.queryMaxOverdueDays(orderIdList);
    // 3. 如果 maxOverdueDays < 7 → 拦截（即使当前逾期=0）
    if (maxOverdueDays < 7) {
        result.setResultMessage("您有借款已逾期噢，请还款后再来借款~");
    }
}
```

**关键事实**：
- 合同状态是 REPAYING 且当前逾期=0 时，某个还款计划可能在过去7天内有过逾期记录
- `queryMaxOverdueDays` 查的是**所有还款计划的历史最大逾期天数**（不是当前逾期）
- 该方法是 DEBUG 级别日志（`logger.debug`），CLS **不采集** DEBUG 日志
- 无法直接通过 CLS 确认是否触发了此拦截

**替代验证方式**：
- 查合同是否存在：`contractNoState:"REPAYING" AND message:"{contractNo}"`
- 如能找到 `contractNoState:REPAYING` 且 `overdue:0` 的日志 → 合同当前无逾期
- 但仍无法证明每个还款计划都没在近7天内逾期过

### Step 3: 检查 h5-loan 前端的资方封禁信息

查询 h5-loan 的 miniCardInfo 接口结果：

```text
serviceName:"h5-loan" AND message:"{cid}" AND message:"allRefuse"
```

关注以下字段：
- `allRefuse:true/false` — 是否被全局禁借
- `frozenFunds` — 被封禁的资方列表
- `applyStatusEnum:"PASS"/"FAIL"` — 申请状态
- `queryApiOrderRelocationList` — 端外迁徙（是否有待处理的订单）

### Step 4: 检查外部系统实验配置加载

`weixin-h5api` 调用 `UserInfoService.getExperimentItem` 可能超时，导致借款入口实验配置未正确加载：

```text
level:"ERROR" AND message:"getExperimentItem" AND message:"{cid}"
```

如果 itemCode=`user_navigation_loan_enter` 超时，前端可能无法展示借款入口。

### Step 5: 对比 queryOverdueMark vs guideCheckAbility 的差异

| 维度 | queryOverdueMark (LoanServiceImpl用) | guideCheckAbility (前端/预检用) |
|------|--------------------------------------|-------------------------------|
| 日志级别 | INFO（CLS可查） | DEBUG（CLS不可查） |
| 逾期检查 | ①当前逾期 getUserOverDueMark ②T4门槛 queryUserOverDueHis | ①还款计划逾期天数<7 ②额度不足 ③T4门槛 |
| 额外检查 | - | 额度比较(applyAmount vs loanCurrentCredit) |
| 结果 | isOverdue: true/false | isSuccess: true/false |

**结论**：guideCheckAbility 比 queryOverdueMark 多两个检查（还款计划逾期<7天 + 额度比较），且为不可见的 DEBUG 级别。若 queryOverdueMark 通过但客户仍无法借款，优先怀疑 guideCheckAbility 中的还款计划逾期检查。

### Step 6: 查看资金路由

如果所有预检通过且有实际下单，资金路由可能阻塞：

- `underFrozenCheck 某个可用资金方未在冻结表里` — 不影响流程但提示可能路由异常
- `[资金路由]被xx借款渠道拒绝` — 资方拒绝
- order 服务 FundPlanService.queryFundList — 查看可用资方列表
