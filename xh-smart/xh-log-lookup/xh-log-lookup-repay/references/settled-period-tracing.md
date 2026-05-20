# 已结清期次追踪实战参考

> 本文件记录了查询某合同第 N 期是否已结清/何时结清的实操方法。

## 信号源总结

| 日志信号 | 服务 | 字段规律 | 用途 |
|---------|------|---------|------|
| `最近结清期数: N` | account-swift-app-job | `message` 中直接出现 | 确认哪期已结清 |
| `订单id:{orderId}的N期已出账` | order (ArbitrarilyRepayServiceImpl) | `message` 中直接出现 | 确认某期已到还款日 |
| `还款请求,保存还款流水` | order (ArbitrarilyRepayServiceImpl) | `message` 前缀 | 还款请求入口 |
| `交易流水号:{xxx},查询微信订阅结果` | order (ArbitrarilyRepayServiceImpl) | `message` 前缀 | 微信支付回调确认 |
| `syncType:DEDUCT_NOTIVE` | order (JmsQService) | `message` 中 JSON | 扣款状态同步 |

## 合同状态字段速查

- `contractNoState` — 只在特定日志类（DroolsService、CheckShowChangeCardEventListener）中有，不是所有日志都有
- `orderStatus` — 判据：REPAYED/SETTLED/EARLY_REPAYED = 已结清，REPAYING/OVERDUE = 未结清
- `accountStatus` — ACTIVE = 活跃，CLAIMS_Z/CLAIMS_L = 已理赔
- `最近结清期数` — 日切任务给出最新已结清的期次号

## 典型实操示例

**场景**：合同 CK202604090001010，问第一期什么时候结清、从哪个系统发起。

**步骤**：

1. 宽搜 contractNo：
   ```
   message:"CK202604090001010"
   ```

2. 在结果中找 account-swift-app-job 日志，确认 `最近结清期数: 1` → 第一期已结清

3. 在结果中提取 orderId（从 ArbitrarilyRepayServiceImpl 日志中找到）：
   → orderId = 20260402003723692743

4. 搜 orderId 精细定位：
   ```
   serviceName:"order" AND message:"20260402003723692743"
   ```

5. 按时间排序提取关键时间点（⚠️ 注意区分请求时间和成功时间）：
   - **11:16:09.084** — `订单id:xxx的1期已出账`（已到还款日）
   - **11:16:10.084** — `还款请求,还款记录`（发起还款）← ❌ 不是结清时间
   - **11:16:10.396** — `还款请求,保存还款流水`（流水入库）
   - **11:16:31~36** — 查询提前还款、聚合支付检查通过
   - **11:16:13.935** — ✅ **`还款成功，恢复额度:360.4`** ← **实际结清成功时间**
   - **11:16:13.951** — `[返现券]还款成功处理请求 stageNbr=1` ← 佐证
   - **12:40:29** — `查询微信订阅结果`（微信支付回调，已延迟）

6. 查调用链确认来源：
   ```
   SR [172.18.2.202:42286] [ArbitrarilyRepayService.sendRepay]
   → appChannel=APPWECHAT 从 h5-loan 的 /repay/sendRepay 发起
   ```

7. **结论**：第一期实际结清时间为 **2026-05-17 11:16:13.935**（而非请求时间 11:16:10），由 **h5-loan → order.ArbitrarilyRepayServiceImpl**（任性还款）发起，来源渠道 **APPWECHAT**（微信APP）。

## 注意点

- 「最近结清期数」只反映截至日切时的最新已结清期次，不包含全部历史。要知道所有已结清期次需要看历史日切日志或查 DB。
- 任性还款（ArbitrarilyRepayServiceImpl）和系统代扣（RepayOrderServiceImpl）走的是不同的日志前缀，不要混淆。
- **⛔ 不要用 DEDUCT_NOTIVE 的发出时间当结清时间**。DEDUCT_NOTIVE 是扣款状态同步 MQ 消息，可能延迟 1 小时以上（本例延迟约 1 小时到 12:40）。真正的结清时间是 `还款成功，恢复额度:{amount}` 日志的时间。
- `appChannel` 字段（如 APPWECHAT/ANDROID/IOS/H5/WEAPP）标识客户的登录渠道，在 h5-loan 的 `RepayController.sendRepay()` 中通过 `loginChannelNm` 设置，可以从回调链路的 SR 日志中找到。
