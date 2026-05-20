# 从 CLS 日志提取合同数据（无 DB 替代方案）

## 何时读取

当生产库不可直连、但需要从 CLS 推断 cid 名下合同、合同状态、账务还款计划或 CK/CS 合同号时读取。

## 目录

- 核心限制
- 查询入口
- 字段解析
- 多合同对比
- 结论表达

> 适用场景：用户问"这个cid名下有多少笔未结清合同"、"这笔合同的状态是什么"、"有没有账务还款计划"等业务数据问题，且无法直连生产数据库。

## 核心限制

- **CLS 仅保留 30 天日志**：30 天内无活动的存量合同不会出现
- **日志非实时数据源**：日志记录的是"操作时刻的快照"，不是数据库的当前状态
- **字段不完整**：日志中的 `orderStatus` 等字段是打印时刻的值，后续变化需要新日志确认

## 合适场景

| 场景 | 靠谱度 | 说明 |
|------|--------|------|
| "这笔合同当前是什么状态" | ✅ 高 | 近期有操作的合同都能捕捉到 |
| "有没有账务还款计划" | ✅ 高 | 同步操作通常会打日志 |
| "有多少笔未结清合同" | ⚠️ 中 | 只能查到近30天有活动的，全量需 DB |
| "全部历史订单" | ❌ 低 | 依赖 DB 全量数据 |

## 三类查询模板

### 1. 按合同号查 — 最精确

```
serviceName:"order" AND message:"{contractNo}"
```

适合查：该合同的所有操作日志（下单、签约、放款、还款、逾期、账务同步）

**关键日志类**：
| 类 | 打印内容 | 作用 |
|---|---------|------|
| `RepayOrderServiceImpl` | "合同{contractNo}订单状态:{orderStatus},账户状态:{accountStatus}" | 快速查看当前状态 |
| `RepayOrderServiceImpl` | "同步单个订单还款状态,查询中腾信账务信息" | 确认账务还款计划是否已同步（含完整 periodStatusVos） |
| `RepayOrderServiceImpl` | "[同步还款计划]更新还款计划/结清期次：{JSON}" | **确认具体哪些期次的还款计划被更新**。每出现一次更新一期。可用来确认合同的中腾信账务数据已真实落地到本地 t_order_repayplan 表。日志中的 modifyDate 字段反映了上次更新时间。 |
| `NotifyPartnerAdvisor` | "db查询到最新订单为：{order JSON}" | **最完整的订单快照**，含：fundSourceId（资金方）、overdueDate（逾期日）、norepayAmount（放款金额）、repayCardNo（还款卡号）、loanChannel（渠道）、productType（产品类型）。比 `RepayOrderServiceImpl` 的状态行信息丰富得多。 |

### 2. 按 cid 查 — 宽泛

```
serviceName:"order" AND message:"{cid}"
```

适合查：该客户近期的所有订单活动。
值直接搜，不加 `cid:` 或 `userId:` 前缀。

### 3. 查账务还款计划同步

```
serviceName:"order" AND message:"同步单个订单还款状态,查询中腾信账务信息" AND message:"{contractNo}"
```

返回结果包含 `periodStatusVos` 数组，每一项含：
- `periodNum` — 期数
- `deductDate` — 扣款日期
- `factDeductDate` — 实际扣款日期
- `receiveAmount` — 已收金额
- `receiptAmount` — 应收金额
- `status` — 还款状态（1=已还清, 其他=未还）

以及顶层字段：
- `contractAmt` — 合同金额
- `delinquentDays` — 逾期天数
- `delinquentAmount` — 逾期金额
- `remainCapital` — 剩余本金
- `currPeriod` — 当前期数
- `accountStatus` — 账户状态（NORMAL/CLAIMS_Z/CLAIMS_L）

## 处理流程

```text
Step 1: 判断查询意图 → 存量状态查询（非流程追踪）
Step 2: 选择查询模板（按 contractNo / 按 cid / 按账务同步）
Step 3: 构造 CLS 查询 → 用本地 Chrome（AppleScript）+ 生产 topic
Step 4: 提取页面文本结果
Step 5: 去重汇总 → 统计 unique contractNo、orderStatus、剩余本金等
Step 6: 说明限制 — 仅30天有活动的合同
Step 7: 发飞书卡片
```

## 实操样例

假设查 cid=`20161002000002677537` 的未结清合同：

```
serviceName:"order" AND message:"20161002000002677537"
```

在结果中 grep `"id"` 和 `contractNo` 字段找出合同号，然后查每个合同的 orderStatus。

如果搜到 `合同{xxx}订单状态:OVERDUE` 说明该合同逾期。
如果搜到 `同步单个订单还款状态,查询中腾信账务信息` 说明有账务还款计划同步。

## 多合同对比查询

当用户给出**多个 contractNo** 要求对比（如同步时间、状态等）时：

```text
serviceName:"order" AND (message:"{contractNo1}" OR message:"{contractNo2}" OR ...)
```

然后在结果中按 contractNo 分组、按时间排序，提取每个合同的 sync 时间点和状态。

**示例**（两合同同步时间对比）：

| contractNo | 同步时间 | 触发原因 |
|-----------|---------|---------|
| CK202601020004522 | 05-18 06:52:41.580 | 扣款通知 DEDUCT_NOTIVE |
| CK202604020004502 | 05-18 19:32:16.971 | 扣款通知 DEDUCT_NOTIVE |

触发原因通过查找 `syncType` 字段确认（在 `syncRepaySingleOrder` 请求请求参数中）。

## 已知坑

- CLS 的 topic 可能因 `hide*` 参数丢失数据，0 条结果不一定是真无数据
- 搜 cid 时可能返回大量无关日志（打印了整行 json 含该 cid 的老记录），需要 grep 去重
- 账务数据是"查询时刻的快照"，不是实时推送。如果账务同步定时任务还没跑，可能查不到最新数据
