# 反欺诈重试机制

## 代码位置

`CreditService.loanAntiFraud()` — `com.xhqb.order.biz.service.external.credit.CreditService` (line 97-159)

## 重试逻辑

```java
int[] retryDelays = {1000, 2000};   // 第1次重试等1s, 第2次重试等2s
for (int attempt = 0; attempt <= retryDelays.length; attempt++) {
    try {
        loanAntiFraudResult = loanAntiFruadService.loanAntifraud(request);
        if (loanAntiFraudResult != null && loanAntiFraudResult.isSuccess()) {
            break;  // 任一尝试成功即退出
        }
    } catch (Exception e) {
        log.warn("[借款反欺诈]反欺诈服务调用异常, outBizId={}, 第{}次尝试", ...);
    }
    if (attempt < retryDelays.length) {
        Thread.sleep(retryDelays[attempt]);
    }
}
```

| 参数 | 值 |
|------|-----|
| 总尝试次数 | 3 次（attempt=0,1,2） |
| 重试延迟 | 第1次重试延迟 1000ms，第2次延迟 2000ms |
| 触发条件 | ① 反欺诈返回 null 或 `isSuccess=false` ② 调用抛异常 |
| 退出条件 | 任一尝试 `success=true` 即 break |
| 全部失败 | 返回 `Optional.empty()` |

## 调用方

`LoanTemplate.unifiedLoanAfter()` (line 502-508)：

```java
Optional<AntiFraudInfo> optAntiFraudInfo = creditService.loanAntiFraud(loanInfo);
if (!optAntiFraudInfo.isPresent() || !optAntiFraudInfo.get().isSameDevice()) {
    orderLocalService.updateOrderStatus(loanInfo.getOrderId(), OrderStatusEnum.SINGFAIL.getCode());
    throw new BusinessRuntimeException("反欺诈服务调用异常");
}
```

## 日志锚点

| 级别 | 日志关键词 | 说明 |
|------|-----------|------|
| INFO | `[借款反欺诈]借款下单反欺诈请求:{...}` | 每次进入 loanAntiFraud 都打印，仅一次 |
| INFO | `[借款反欺诈]借款下单反欺诈结果, 第N次尝试: LoanAntiFraudResult(...)` | 每次尝试都打印；`第1次`=首次, `第2次`=第1次重试, `第3次`=第2次重试 |
| WARN | `[借款反欺诈]反欺诈服务调用异常, outBizId=..., 第N次尝试` | 调用抛异常时打印（无重试延迟信息） |
| WARN | `[借款反欺诈]反欺诈服务调用异常, outBizId=..., 第N次尝试, Nms后重试` | 准备重试前打印，包含延迟时间 |

## CLS 查询

由于 `[借款反欺诈]` 含中文，需要浏览器注入搜索：

```
serviceName:"order" AND message:"[借款反欺诈]"
```

也可用 ASCII 查询验证是否存在 CreditService 日志：
```
serviceName:"order" AND message:"credit.CreditService"
```
（logger 缩写 `c.x.o.b.s.e.credit.CreditService` 可在 CLS 中通过 `message` 字段搜到）

## 排查路径

1. 搜 `[借款反欺诈]借款下单反欺诈结果, 第2次尝试` — 如果命中，说明重试被触发
2. 搜 `[借款反欺诈]反欺诈服务调用异常` WARN 日志 — 看异常原因和重试延迟
3. 如果所有尝试都失败 → `LoanTemplate` 将订单置为 SINGFAIL
4. 如果 `CreditService` 完全无日志（0 条）→ 反欺诈路径未被触发
