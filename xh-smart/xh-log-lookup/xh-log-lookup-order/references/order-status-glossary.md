# 订单状态术语表 — t_order.order_status

## 何时读取

当需要解释 `orderStatus`、合同状态、申请状态、未结清/已结清/退单/拒绝等状态语义时读取。

## 目录

- 合同 vs 申请
- 未结清状态
- 已结清状态
- 失败和拒绝状态

> 来源：`OrderMapper.xml` (com.xhqb.order.common.dal.dao.OrderMapper)
> 表名：`orderdb.t_order`（或 `t_order`）
> 用户字段：`user_id`（即 cid）

## 合同 vs 申请

| 类别 | 判断依据 | 说明 |
|------|---------|------|
| **已生成合同** | `contract_no IS NOT NULL` | 签约成功，资金方已出合同 |
| **仅申请未签约** | `contract_no IS NULL` | 只创建了申请、无合同 |
| **未结清合同** | `contract_no IS NOT NULL` AND `order_status NOT IN (已结清状态集)` | 正在还款中 |

## 状态分类

### 🔴 未结清 — 有合同且未还清（含逾期）

| orderStatus | 中文含义 | 用户可见状态 | 说明 |
|------------|---------|-------------|------|
| `REPAYING` | 正常还款中 | 正常 | 合同已生成，按计划还款中 |
| `OVERDUE` | 逾期 | 逾期 | 已逾期，超期未还款 |
| `EARLYREPAYING` | 提前还款处理中 | 提前还款处理中 | 用户发起了提前还款 |
| `LOAN_SUCESS_PRE_WP` | 服务费扣取中 | 服务费扣取中 | 放款成功，但代扣服务费未完成 |
| `NOTICE_SETTLE` | 提现中 | 提现中 | 存管提现进行中 |
| `WITHDRAW_FAIL_CARD` | 提现失败待换卡 | 提现失败待换卡 | 代付提现失败，需换卡 |
| `WITHDRAWING` | 提现中 | 提现中 | 代付提现进行中 |
| `WITHDRAW_SUCESS` | 提现中 | 提现中 | 提现成功但资金未到账 |
| `HOLD_ON` | 转账中 | 转账中 | 放款转账进行中 |
| `ON_ROUTE` | 转账中 | 转账中 | 资金路由中 |
| `RISK_CONFIRM` | 转账中 | 风控确认中 | 放款前风控二次确认 |
| `PRESIGN` | 签约中 | 转账中 | 待签约 |
| `PRELOAN` | 待放款 | 待放款 | 签约完毕，排队等待放款 |
| `FINANCING` | 待放款 | 待放款 | 资方放款处理中 |
| `INITLOAN` | 待放款 | 待放款 | 初始放款状态 |
| `PREVERIF` | 待认证 | 待认证 | 签约前认证 |

### 🟢 已结清 — 合同已还清

| orderStatus | 中文含义 |
|------------|---------|
| `REPAYED` | 已还清 |
| `SETTLED` | 已结清 |
| `REFUNDSETTLED` | 退款结清（结清后退款） |

### ⚪ 申请失败 / 未形成合同

| orderStatus | 中文含义 | 说明 |
|------------|---------|------|
| `REFUSE` | 拒绝 | 风控拒绝 |
| `SINGFAIL` | 签约失败 | 用户未签约或签约失败 |
| `CANCEL` | 已取消 | 用户取消 |
| `FAIL` | 失败 | 下单失败 |
| `WAITING_PAYMENT` | 待支付 | 前置收费未完成 |
| `WAITING_WITHDRAW` | 待提现 | 等待用户主动提现 |
| `LOAN_REFUSE` | 放款拒绝 | 资方拒绝放款 |

### ⚠️ 理赔

| accountStatus | 中文含义 | 说明 |
|--------------|---------|------|
| `CLAIMS_Z` | 理赔中（Z） | 担保理赔处理中 |
| `CLAIMS_L` | 理赔中（L） | 保险理赔处理中 |

## 查询模式

### 查某 cid 未结清合同数

SQL：
```sql
SELECT COUNT(*)
FROM t_order
WHERE user_id = '{cid}'
  AND contract_no IS NOT NULL
  AND order_status IN ('REPAYING','OVERDUE','EARLYREPAYING','LOAN_SUCESS_PRE_WP',
       'NOTICE_SETTLE','WITHDRAW_FAIL_CARD','WITHDRAWING','WITHDRAW_SUCESS',
       'HOLD_ON','ON_ROUTE','RISK_CONFIRM','PRESIGN','PRELOAN','FINANCING',
       'INITLOAN','PREVERIF');
-- 或语义等同的不在已结清状态集：
SELECT COUNT(*)
FROM t_order
WHERE user_id = '{cid}'
  AND contract_no IS NOT NULL
  AND order_status NOT IN ('REPAYED','SETTLED','REFUNDSETTLED');
```

### 查某 cid 全部订单

```sql
SELECT id, order_status, contract_no, loan_amount, apply_amount, loan_channel,
       create_date, loan_date, settled_status, settle_date
FROM t_order
WHERE user_id = '{cid}'
ORDER BY create_date DESC;
```

### 注意

- **无数据库直连**：当前 agent 没有生产数据库访问权限。如需查询上述数据，需通过：
  1. 用户提供的 SQL 工具 / 数据库客户端
  2. 内部管理后台 API
  3. CLS 日志中提取 orderStatus 状态推断（不实时，仅供参考）
- `user_id` = `cid`，两者在 order 系统中指同一个人
- `contract_no` 为 null 表示未生成合同，不计入"未结清合同"统计
