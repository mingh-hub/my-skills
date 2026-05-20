
---

## 九、案例三：近30分钟异常告警总览（2026-05-20 10:09 ~ 10:39）

### 执行背景

用户问题：

> "看下order近半小时异常告警情况"

执行时间：2026-05-20 10:09 ~ 10:39

查询时间范围：`now-30m,now`

### Step 0：ERROR 总览（本次关键改进点）

按照当前版本健康检查 SOP 的 **Step 0**，先查全量 ERROR，不限于 [借款下单] 前缀。

查询语句：

```text
serviceName:"order" AND level:"ERROR"
```

结果：
- **1,631 条 ERROR 日志**（9 次加载更多）
- 涉及 **3 个不同类** 的异常

### Step C：[借款下单] 业务异常

通过浏览器注入中文查询：

```text
serviceName:"order" AND (message:"[借款下单]出现系统错误" OR message:"[借款下单]请求出现业务异常")
```

结果：**23 条 WARN**，2 种业务异常。

### 发现汇总

| 类型 | 数量 | 严重程度 | 说明 |
|------|------|---------|------|
| ReCreditService Dubbo 超时 | ~159 条 (XhCard + Profile) | 🔴 严重 | 持续大量超时，疑似下游故障 |
| [协议共享]CID查询失败 | 20 条 | 🟡 中等 | 5个身份证号均失败 |
| [释放客户冻结额度]异常 | 1 条 | 🟢 偶发 | unfreeze 超时 |
| 身份证照片过期/支付类型不支持 | 23 条 | 🟡 业务拦截 | 业务异常，不影响系统 |

### 对比三种查询策略的召回差异

| 查询策略 | 命中的异常类型 | 遗漏的异常类型 |
|----------|---------------|---------------|
| 📌 老版 Step C 仅 [借款下单] 前缀 | 身份证过期、支付类型不支持(23条) | **ReCreditService 超时(159条)**、CID查询失败(20条)、unfreeze超时(1条) |
| ✅ 新版 Step 0 `level:"ERROR"` | ReCreditService 超时、CID查询失败、unfreeze超时 | **业务异常 WARN** 不会被捕获 |
| ✅ 组合 Step 0 + Step C | **全部异常** | 无 |

### 经验总结

1. **"异常告警"和"健康检查"是不同意图**。健康检查关心下单流程是否畅通；异常告警关注系统是否在报错。两者目标不同，查询策略也不同。
2. **Step 0 不可跳过**。`[借款下单]` 前缀只覆盖 `LoanServiceImpl` 家族，而 `XhCardServiceImpl`、`SharingAgreementServiceImpl`、`AccountOService` 的异常完全在 Radar 之外。
3. **Step 0 的查询是纯 ASCII**（`serviceName:"order" AND level:"ERROR"`），不需要浏览器注入，可以快速执行获取概览。这是它的另一个优势。
4. **每条 ReCreditService 超时产生双条 ERROR**（XhCardServiceImpl 业务层 + ProfileFilter 框架层），统计时要区分"事件数"和"日志条数"。
