# Order 测试数据库访问指南

## 何时读取

当用户明确查询测试环境订单数据，或需要用 SQL 解释订单状态/未结清定义时读取。生产数据默认不直连，优先使用 CLS 或用户提供的连接信息。

## 目录

- 凭据来源
- 连接方式
- 未结清 SQL
- 状态解释

## 凭据来源

**不要**尝试解密 `jdbc.properties` 中的 Druid RSA 加密密码。在 `dalgen` 工具配置中有明文凭据：

| 文件 | 路径 |
|------|------|
| `dal.properties` | `order/dalgen/src/main/resources/dal.properties` |

### 连接参数

| 参数 | 值 |
|------|----|
| Host | `10.32.5.227` (dev test) / `10.32.4.188` (service app test) |
| Port | 3306 |
| Database | `orderdb` |
| User | `xhtest` |
| Password | `xh_test` |

两个服务器数据一致（都是测试数据），任选一个即可。

## MySQL Client

Mac 本地有 MySQL Client：

```
/usr/local/mysql/bin/mysql -h 10.32.5.227 -u xhtest -pxh_test orderdb
```

## 测试库 vs 生产库

**测试库只有约 1.5~1.7 万条 t_order 记录**，全为测试数据。生产客户（如 `2016...` 开头的 cid）在测试库中不存在。

### 测试库 user_id 分布（~16K 条）

| 前缀 | 数量 |
|------|------|
| 2019 | ~4,000 |
| 2025 | ~2,500 |
| 2018 | ~2,000 |
| 2023 | ~1,400 |
| 2024 | ~1,400 |
| 2022 | ~1,200 |
| 2020 | ~900 |
| 2021 | ~600 |
| 2017 | ~500 |
| a202 | ~400 |

`2016` 开头的 cid 不存在于测试库。

## 关键 SQL

### 未结清合同数

```sql
SELECT COUNT(o.id) AS unsettled_count
FROM t_order o
WHERE o.user_id = '${cid}'
  AND o.order_status NOT IN (
    'REPAYED','REFUNDSETTLED','SETTLED',
    'EARLY_REPAYED','CANCEL','FAIL',
    'SINGFAIL','LOAN_REFUSE'
  );
```

### 该 cid 全部订单（含状态）

```sql
SELECT o.id AS order_id, o.contract_no, o.order_status,
       o.apply_amount, o.loan_amount, o.create_date, o.loan_date
FROM t_order o
WHERE o.user_id = '${userId}'
ORDER BY o.create_date DESC;
```

### t_order 表结构特点

- `user_id` — 客户 ID（cid 格式），`varchar(30)`
- `order_status` — 订单状态
- 表中字段名均用 `user_id` 而非 `cid`

## cid 与 userId 关系

- **cid** = `20161002000002677537`（纯数字，用户标识）
- **userId** = `mem484e1914f6cf411ebff413f812ba40a9`（mem 开头格式）
- t_order 表 `user_id` 字段实际存的是 cid（纯数字格式），不是 mem 格式的 userId
- 项目中部分代码混合使用 cid/userId 术语，但 t_order.user_id 是 cid

## 未结清订单定义

来源 `OrderMapper.xml` 的 SQL：

| 方法 | SQL 条件 | 用途 |
|------|---------|------|
| `isNotSettle(cid)` | `order_status NOT IN ('REPAYED','REFUNDSETTLED','SETTLED','EARLY_REPAYED','CANCEL','FAIL','SINGFAIL','LOAN_REFUSE')` | 计数 |
| `queryNoSettleOrders(userId)` | `order_status IN ('REPAYING','OVERDUE')` | 列表 |
| `queryUserRepayOrderList(queryMaps)` | `order_status IN ('LOAN_SUCESS_PRE_WP','OVERDUE','REPAYING')` | 用户可还列表 |

`isNotSettle` 范围最广（非结清/取消/失败即算未结清），`queryNoSettleOrders` 仅含 REPAYING + OVERDUE。

## 其他可访问的数据库

`orderdb` 所在 MySQL 实例上有大量其他数据库，包括 `accountdb`、`cifdb`、`funddb`、`repaydb`、`loki` 等。需要时连接后直接 `SHOW DATABASES` 查看完整列表。
