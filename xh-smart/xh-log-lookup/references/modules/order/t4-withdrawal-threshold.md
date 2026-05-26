# T4 提现门槛规则（UserOverDueHisHandler）

## 何时读取

当用户看到“不良借款记录”“提现门槛”“历史最大逾期天数”等借款能力预检拦截时读取。

## 目录

- 规则概述
- 客群分类
- 日志关键词
- 诊断结论模板

> 代码位置: `order/app/biz/service-impl/src/main/java/com/xhqb/order/biz/service/handle/UserOverDueHisHandler.java`
> 需求来源: Tapd #1167422022001057398

## 规则概述

T4 提现门槛根据用户的 **MOB（在贷月数）** 和 **结清状态** 将客户分 4 类，每类有不同的准入条件。用户必须满足**至少一条**该类下的条件才能借款。

## 配置阈值（可从 Redis/DB 动态调整）

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `minHisMaxOverdueDay` | 10 | 历史最高逾期天数最小阈值 |
| `maxHisMaxOverdueDay` | 60 | 历史最高逾期天数最大阈值 |
| `settleMaxOverdueThreeMon` | 12 | 结清前 3 个月最大逾期天数 |
| `maxOverdueInThreeMon` | 0 | 近 3 个月最大逾期天数 |
| `maxOverdueInTwelveMon` | 15 | 结清前近 1 年最大逾期天数 |
| `maxOverdueInThreeYears` | 12 | 近 3 年最大逾期天数 |
| `maxOverdueInSixYears` | 30 | 近 6 年最大逾期天数 |

## 分类规则

### 第 1 类：短 MOB 用户（mob ≤ 6）

```
条件 1.1: hisMaxOverdueDay < 10 → 通过
否则: 驳回
```

### 第 2 类：中 MOB 未结清用户（6 < mob ≤ 12, settle_flag = 0）

```
条件 2.1: hisMaxOverdueDay < 10 → 通过
否则: 驳回
```

### 第 3 类：中 MOB 结清用户（mob > 6, settle_flag = 1）

```
条件 3.1: hisMaxOverdueDay < 10 → 通过
条件 3.2: hisMaxOverdueDay ≤ 60
       AND max_overdue_day_6year ≤ 30
       AND max_overdue_day_3year ≤ 12
       AND settleDateMaxOverdueDays12mi ≤ 15
       AND settle_date_max_overdue_days_3m_i ≤ 12
       → 通过
否则: 驳回
```

### 第 4 类：长 MOB 未结清用户（mob > 12, settle_flag = 0）← **最常见拦截场景**

```
条件 4.1: hisMaxOverdueDay < 10 → 通过
条件 4.2: hisMaxOverdueDay ≤ 60
       AND max_overdue_day_6year ≤ 30
       AND max_overdue_day_3year ≤ 12      ← 近3年阈值较严格
       AND max_overdue_days_in3m_i ≤ 0     ← 近3月必须0逾期
       → 通过
否则: 驳回
```

## 关键聚合字段说明（来自 aggrAntifraudAnlyzService.queryTxInfo）

| 字段 | 含义 |
|------|------|
| `mob_i` | 在贷月数（Month on Book） |
| `settle_flag_i` | 结清标志（0=未结清/在贷, 1=已结清） |
| `his_max_overdue_days_i` | 历史最高逾期天数 |
| `max_overdue_day_6year` | 近 6 年最高逾期天数 |
| `max_overdue_day_3year` | 近 3 年最高逾期天数 |
| `max_overdue_days_in3m_i` | 近 3 个月最高逾期天数 |
| `max_overdue_days_in1m_i` | 近 1 个月最高逾期天数 |
| `settleDateMaxOverdueDays12mi` | 结清前近 1 年最高逾期天数（结清用户） |
| `settle_date_max_overdue_days_3m_i` | 结清前 3 个月最高逾期天数（结清用户） |
| `total_credit_used_rate_f` | 总额度使用率 |

## 日志定位指引

搜索 `UserOverDueHisHandler` 的日志行：

```
cid:{cid},hisMaxOverdueDay:{N},aggrAntifraudAnlyzService queryTxInfo result is:{full JSON}
  → 第一步：打印聚合反欺诈的返回结果

cid:{cid},T4提现门槛, hisMaxOverdueDay:{N}, mob:{N}, settleFlag:{N}, max_overdue_day_6year:{N},...
  → 第二步：打印传入的参数

cid:{cid},通过提现门槛[3.1/3.2/4.1/4.2],历史最大逾期天数:{N},...
  → 通过提现门槛

cid:{cid},T4提现门槛通过[3.2/4.2], 贷中结清客群(长MOB在贷), 历史最大逾期天数:{N}
  → 通过但历史逾期>15天（高风险客户的特殊日志）

cid:{cid},未通过提现门槛,历史最大逾期天数:{N},...
  → 未通过 → isOverdue=true → 返回"您存在不良借款记录，无法借款。"

cid:{cid},贷中提现门槛查询结果，是否逾期:{true/false}
  → 最终判定结果
```

## 常见拦截场景

| 客群特征 | 命中规则 | 超标维度 |
|----------|---------|---------|
| mob=111, settle=0, hisOverdue=15 | 4.2 | max_overdue_day_3year=15 > 12 |
| mob=111, settle=0, hisOverdue=8 | — | **不会拦截**（条件4.1: < 10 → 通过） |
| mob=111, settle=0, hisOverdue=15, 3m=0 | 4.2 | his=15 ≤ 60 ✓, 6yr=15 ≤ 30 ✓, **3yr=15 > 12 ✗**, 3m=0 ≤ 0 ✓ → 驳回 |
| mob=111, settle=0, hisOverdue=50, 3m=15 | 4.2 | **his=50 ≤ 60 ✓**, 6yr=50 ≤ 30 ✗ → 驳回（6年超标） |
| mob=8, settle=0, hisOverdue=15 | 2 | his=15 ≥ 10 → 驳回（只能走条件2.1，无条件2.2兜底） |

## 排查步骤（如果用户说"不良借款记录"）

1. 搜 cid 定位 traceId
2. traceId 钻取，找 `UserOverDueHisHandler` 日志
3. 从日志中提取 `mob_i`, `settle_flag_i`, `max_overdue_day_3year`, `his_max_overdue_days_i`
4. 对照上述分类表判断命中哪条规则
5. 定位是哪个维度超标
