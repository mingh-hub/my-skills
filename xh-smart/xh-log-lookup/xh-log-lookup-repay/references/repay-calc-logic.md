# 还款订单列表 & 逾期金额计算

## 场景

给定一个 `contractNo`（如 `CK202604080005360`），查询还款订单列表时看到的 `overdueAmount`（逾期金额/当前应还金额）是怎么算出来的。

## 入口方法

`ArbitrarilyRepayServiceImpl.java:204` — `queryRepayOrderList()`

## 逾期金额计算公式

代码位置：`ArbitrarilyRepayServiceImpl.java:322-335`

```java
BigDecimal overdueAmount = BigDecimal.ZERO;
for (OrderRepayplan plan : planList) {
    if (OVERDUE.equals(plan.getCurrentRepayStatus())) {
        overdueAmount = overdueAmount
            .add(plan.getCurrentRepayAmount())    // 本期应还本金
            .add(plan.getCurrentRepayFee())       // 本期应还费用(利息+服务费)
            .add(plan.getOverdueFee())            // 逾期费(滞纳金)
            .subtract(plan.getRepayedAmount());   // 已还金额
    }
}
```

然后第 409~413 行赋值给前端返回的 `nowRepayAmount`（当前应还金额）：

```java
if (overdueAmount.compareTo(BigDecimal.ZERO) > 0) {
    orderBean.setNowRepayAmount(overdueAmount);   // 有逾期 → 返回逾期总额
} else {
    orderBean.setNowRepayAmount(curStageAmount);  // 无逾期 → 返回当期应还
}
```

## 关键模型字段

### OrderRepayplan（`t_order_repayplan` 表）

| 字段 | 类型 | 含义 |
|------|------|------|
| `currentRepayStatus` | enum | `OVERDUE`=逾期, `REPAYED`=已还，`CURRENT`=当期 |
| `currentRepayAmount` | BigDecimal | 本期应还本金 |
| `currentRepayFee` | BigDecimal | 本期应还费用(利息+服务费) |
| `overdueFee` | BigDecimal | 逾期费(滞纳金) = 应还金额 × 日罚息率 × 逾期天数 |
| `repayedAmount` | BigDecimal | 已还金额 |
| `useDiscountFee` | BigDecimal | 使用优惠券金额 |
| `currentStageNum` | Integer | 当前期数 |
| `currentRepayDate` | Date | 还款日 |

### QueryRepayOrderListResult.OrderBean（返回给前端）

| 字段 | 计算逻辑 |
|------|---------|
| `nowRepayAmount` | 有逾期=overdueAmount, 无逾期=curStageAmount |
| `overdueFee` | SUM(所有未还分期的overdueFee) |
| `unSettleAmount` | SUM(所有未结清分期的currentRepayAmount + currentRepayFee + overdueFee - repayedAmount) |
| `unRepayAmountSum` | SUM(符合条件的可分期的currentRepayAmount + currentRepayFee + overdueFee) |
| `currentRepayAmount` | 本月应还金额(from OrderLocalService.getThisMonthRepayInfo) |
| `repayedPrincipal` | SUM(已还分期的currentRepayAmount) |
| `noRepayPrincipal` | contractAmount - repayedPrincipal |

## 生命周期状态流转

```text
NORMAL(正常) → OVERDUE(逾期) → OVERDUE(持续逾期，增长逾期费)
CURRENT(当期) → REPAYED(已还)
```

逾期状态判定：`plan.getCurrentRepayStatus() == OVERDUE`

## 用于 CLS 日志查询

```sql
-- 查该合同的所有日志（跨服务）
message:"CK202604080005360"

-- 查还款相关日志
serviceName:"order" AND message:"CK202604080005360" AND (queryRepayOrderList OR 还款订单列表)

-- 查扣款记录（可能从 hades-web/account-gateway 查到）
message:"CK202604080005360" AND deductAmount
```
