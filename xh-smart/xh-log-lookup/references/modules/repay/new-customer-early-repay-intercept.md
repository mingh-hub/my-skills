# 新客提前结清拦截（新客提还拦截弹窗）

## 场景

用户查询还款信息时（`/repay/queryRepayOrderInfo`）弹出弹窗提示：

> 提前结清于资金到账 **N** 天后可发起，如需帮助请联系在线客服

## 代码位置

`H5LoanProject/app/biz/service-impl/src/main/java/com/xhqb/h5loan/biz/service/controller/RepayController.java`

### 触发条件

```java
// 第462-480行
if (queryRepayOrderResult.isSuccess()) {
    // 弱化提前结清开关
    if (configServiceUtils.getWeakenSettleFlagSwitch()) {
        Integer popWindowDays = needWeakenSettle(queryRepayOrderResult, loginChannelNm, customerPhone, customerId);
        if (Objects.nonNull(popWindowDays)) {
            queryRepayOrderResult.setWeakenSettleFlag(2); // 不展示
            // 放款天数 <= popWindowDays → 弹窗拦截
            if ((new Date().getTime() - loanDate.getTime()) / (1000 * 60 * 60 * 24) <= popWindowDays) {
                queryRepayOrderResult.setPopWindow(true);
                queryRepayOrderResult.setRemindMsg(
                    String.format("提前结清于资金到账%s天后可发起，如需帮助请联系在线客服", popWindowDays));
            }
        }
    }
}
```

## needWeakenSettle() 判定逻辑

`RepayController.java:557-606`

### 配置来源

Apollo 配置项：`weaken.settle.rule`（Spring `@Value("#{${weaken.settle.rule}}")` → `Map<String,String>`）

### 规则字段

| 字段 | 类型 | 含义 |
|------|------|------|
| `whiteList` | 逗号分隔手机号 | 白名单手机号不弱化 |
| `fundSources` | 逗号分隔资方代码 | 特定资方（不分新老客都弱化） |
| `wechatLoanSuccessDays` | 整数 | 微信小程序新客放款成功多少天后展示提前结清入口 |
| `phoneTailNumber` | 逗号分隔数字 | 手机尾号（新客尾号不在此列表则弱化） |
| `cidNumberList` | 逗号分隔数字 | cid 匹配列表 |
| `cidCountdown` | 整数 | 从 cid 倒数第几位取一位数字 |
| `effectDate` | `startDate&endDate` | 新限制生效日期范围 |
| `oldPopWindowDays` | 整数 | 旧弹窗天数 |
| `newPopWindowDays` | 整数 | 新弹窗天数 |

### 判定顺序

1. 白名单手机号 → `null`（不拦截）
2. 在 `effectDate` 范围内 **且** cid 尾号匹配 `cidNumberList` → 返回 `newPopWindowDays`
3. 否则：
   - 资方在 `fundSources` 中 → 返回 `oldPopWindowDays`
   - 新客 **且** 微信小程序（APPWECHAT）**且** 放款超过 `wechatLoanSuccessDays` 天 → `null`（不拦截，展示入口）
   - 新客 **且** 手机尾号不在 `phoneTailNumber` 中 → 返回 `oldPopWindowDays`
4. 其余情况 → `null`（不拦截）

## 关联配置项

| Apollo Key | 说明 |
|-----------|------|
| `weaken.settle.flag.switch` | 弱化提前结清总开关 (Boolean) |
| `weaken.settle.rule` | 上述规则字典 |
| `weaken.settle.flag.plan0` | A/B 测试对照组 |
| `weaken.settle.flag.plan1` | A/B 测试实验组A |
| `weaken.settle.flag.plan2` | A/B 测试实验组B |

## QueryRepayOrderResult 关键字段

| 字段 | 类型 | 含义 |
|------|------|------|
| `popWindow` | boolean | 是否弹窗拦截 |
| `remindMsg` | String | 弹窗提示内容 |
| `weakenSettleFlag` | Integer | 1=展示提前结清入口, 2=不展示/弱化 |
| `newCustomer` | boolean | 是否新客（首笔放款距当前 ≤91天） |
| `canEarlyRepayFlag` | boolean | 是否可提前结清 |
| `canotRepayReason` | String | 不能还款原因 |

## 排查示例

合同 `CK202605180002363`（2026-05-18 创建）
- 放款仅 ~1 天，远小于 `popWindowDays`（通常 7 天或更久）
- H5LoanProject 的 RepayController 判定后直接弹窗拦截
- order 服务日志中无任何相关记录（因拦截发生在 H5 层，请求未到达 order）
