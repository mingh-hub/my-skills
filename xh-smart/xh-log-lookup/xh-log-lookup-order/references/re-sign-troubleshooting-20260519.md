# 重新签约问题排查实录（2026-05-19）

## 何时读取

当用户反馈 APP 一直提示重新签约、银行卡签约页反复弹出、或需要区分全渠道禁闭与签约失效时读取。

## 目录

- 问题描述
- 排查过程
- 根因结论
- 可复用查询方法
- 缓存陷阱

## 问题描述

客户手机号 `13760528673`（林嘉杰）在 APP 反复弹出"重新签约"页面，一直提示客户重新签约。

## 排查过程

### Step 1: 手机号 → cid

搜索 `serviceName:"order" AND message:"13760528673"` 在 CLS 中找到 cid。

**发现**：cid = `20240609023191188998`

### Step 2: 客户画像

从日志中提取到完整客户信息：
- 姓名：林嘉杰（440784199409204235）
- 性别：男，31岁
- 注册：2024-06-09
- 渠道：APPWECHAT / meitubapi01
- 额度：总额 12,210 / 可用 7,470（已用 4,739）
- 状态：mob=22, settle_flag=0（在贷未结清）
- 两张卡：`6212262012004964709`（工行）和 `6225680321001475916`

### Step 3: 找到 RESIGN 签约查询

在 cid 的全量日志中看到两条 `SignService.query`，`scene="RESIGN"`：

```
12:48:21  → 卡 6212262012004964709（traceId: c8be4a21e4cf187c）
12:48:24  → 卡 6225680321001475916（traceId: 37f2ce097bb0c103）
```

两张卡都在发出 RESIGN 查询，说明系统/APP 认为两张卡都需要重新签约。

### Step 4: 发现全渠道禁闭

在同一 trace 中找到 `queryFrozenFundListByCid` 的 SS 日志：

```json
{
  "allRefuse": true,
  "frozenFunds": [
    {"fundSource": "WPXJ_RS", "unfrozenDate": "Wed May 20 16:14:01 CST 2026"},
    {"fundSource": "BHXT",   "unfrozenDate": "Wed May 20 16:14:01 CST 2026"},
    {"fundSource": "MDLC",   "unfrozenDate": "Wed May 20 16:14:01 CST 2026"},
    {"fundSource": "ZHXT",   "unfrozenDate": "Wed May 20 16:14:01 CST 2026"},
    {"fundSource": "ZRB",    "unfrozenDate": "Wed May 20 16:14:01 CST 2026"},
    {"fundSource": "FUQI_TJ","unfrozenDate": "Wed May 20 16:14:01 CST 2026"}
  ]
}
```

日志中还直接输出了：`"20240609023191188998全渠道禁闭结果：1"`

**解禁时间：2026-05-20（次日）16:14:01**

### Step 5: 核心发现 —— 全渠道禁闭 ≠ 重新签约

**全渠道禁闭和重新签约是两套独立机制，不是因果关系，而是并发发生。**

时间线（12:48:21~12:48:24）：
```
12:48:21 — queryFrozenFundListByCid → allRefuse=true（禁闭检查）
12:48:21 — SignService.query scene=RESIGN, card=621226...（签约检查）
12:48:24 — SignService.query scene=RESIGN, card=622568...（签约检查）
12:48:27+ — 会员展示、额度查询、还款列表查询...
```

两组检查并行发出，**互不依赖**。APP 端同时展示"无法借款"(禁闭原因)和"请重新签约"(签约失效)，用户感知为「因为要重签所以不能借」。

### Step 6: 代码链路追溯

#### 全渠道禁闭链路

```
OrderOthersServiceImpl.queryFreezeFundSource()  ← 核心入口
  ├─ 新方法: 查询变量中心 ALL_FUNDS_REFUSE_FLAG_I
  │   OrderOthersServiceImpl:2378~2405
  │   if (allRefuseTag > 0) → freeze ALL fund sources
  └─ 老方法: 查 DB LoanRefuseFreezeRecord
      OrderOthersServiceImpl:2422~2429
      if (fundSource == "ALL_REFUSE") → freeze ALL fund sources

下游消费方（三个独立路径）：
├── FoundSourceInfoFilter.filter()          → ALL_REFUSE_NOT_SUPPORTED 拦截
│   FoundSourceInfoFilter.java:37~47
├── SelfCreditServiceImpl.supplyOtherFilterInfo() → setCanLoan(false), setAllRefuse(true)
│   SelfCreditServiceImpl.java:424~435
└── CustomerCanLoanConfirmHandler.isAllRefuse()
    CustomerCanLoanConfirmHandler.java:102~110
    └── 被 CustomerLoanAvailableServiceImpl.queryLoanAbility() 调用
        CustomerLoanAvailableServiceImpl.java:133 → result.setAllRefuseTag(...)
```

#### 重新签约链路

```
SignService.query(scene="RESIGN")
└── ReSignChannel.querySignChannelInfo()
    ReSignChannel.java:46~88
    ├─ 有缓存 → 直接查 ZTX 签约渠道
    └─ 无缓存 → 查在贷订单 → 查 ZTX
        触发条件：
        ├── AgreementPayServiceImpl:304 划扣失败 → cacheNeedReSignInfo()
        ├── InvalidAgreementHandler:56  支付协议失效 → 发短信通知重签
        └── OrderOthersServiceImpl:4449 SIGNING_ISSUE → 还款失败提示重签
```

**关键：这两条链路没有代码级别的直接调用关系。它们在同一时间窗口被 APP 并行触发。**

### Step 7: 其他排查发现

- T4 提现门槛通过了（isOverdue=false），不是 T4 问题
- queryRepayList 返回 orderCount=0，无当前还款订单
- 30 天日志窗口内未发现还款失败/扣款失败记录
- 所有资金方 unfrozenDate 完全一致（都是 2026-05-20 16:14:01），这是全渠道禁闭的特征

### Step 8: 结论

禁闭明天 16:14 解除后：
1. 禁闭解除 → 客户可以正常借款
2. 如果仍然提示重新签约 → 说明有独立的签约失效问题（银行卡支付协议过期/扣款失败历史标记）
3. 需要单独排查签约失效路径（InvalidAgreementHandler / 还款失败记录）

## 关键日志格式参考

```text
# 禁闭检查
[BeforeLoanOrderService.queryFrozenFundListByCid] → {"allRefuse":true,...}
[OrderOthersServiceImpl] → "{cid}全渠道禁闭结果：1"

# RESIGN 查询
[签约查询]查询签约场景:RESIGN,请求内容为:{"scene":"RESIGN","cardNo":"{卡号}",...}

# 全渠道禁闭拦截
[FoundSourceInfoFilter] → errorCode=ALL_REFUSE_NOT_SUPPORTED,  "借款解禁期X天"

# 客户信息
[CustomerInfoService.queryByCustomerId] → {"customerName":"{姓名}","customerPhone":"{手机号}",...}
```

## 排查要点

- 全渠道禁闭时所有资金方的 `unfrozenDate` 通常**完全一致**，这是一个识别特征
- 如果 not 全渠道禁闭，再查还款失败记录（`OrderOthersServiceImpl.getRepayFailMessage` 对应 SIGNING_ISSUE）和签约失效（`InvalidAgreementHandler`）
- RESIGN 查询次数多不等于有异常 —— APP 可能在轮询签约状态
- **不要假设全渠道禁闭导致重新签约** —— 它们是独立机制，需要分别排查

## 🔴 ReSignChannel 缓存机制（核心陷阱）

### 缓存未在签约成功后失效

`ReSignChannel.querySignChannelInfo()` 使用 Redis 缓存来避免重复查询 ZTX：

```java
// ReSignChannel.java:51
String signCacheKey = getSignCacheKey(RESIGN_CACHE_CHANNEL, req.getRePayInfluenceSign());
```

**缓存写入**（无缓存首次查询后，`AbsSignChannel.java:473~475`）：
```java
redisTemplate.opsForValue().set(key, needSignChannel, 10L, TimeUnit.MINUTES);
// TTL = 10 分钟
```

**缓存读取**（`AbsSignChannel.java:482~491`）：
```java
if (!redisTemplate.hasKey(key)) → Optional.empty()      // 无key → 重建
String cache = redisTemplate.opsForValue().get(key);
if (null == cache) → Optional.of(Lists.newArrayList())  // null值 → 全部已签
else → Optional.of(split(",", cache))                   // 有数据 → 用缓存
```

**关键问题**：

1. **签约成功后没有任何代码清除这个缓存**。没有监听器、没有回调、没有清理逻辑。
2. **缓存命中后，返回结果不回写缓存**（`ReSignChannel.java:60~65`）：
   ```java
   if (optCacheSignChannel.isPresent()) {
       List<ZtxPaymentResult.BodyBean.RespData.BindCard> bindCards = 
           querySignChannelToZtx(..., cacheSignChannel);   // 查ZTX
       finalNeedSign = transZtxNeedSignInfo(bindCards, ...); // 转结果
       finalNeedSign.forEach(s -> { ... });                  // 设置重签限制
       // ⚠️ 没有回写缓存！cacheSignChannel 仍然是旧的
   }
   ```
3. **需要签约多个渠道，客户可能只签了部分**。默认渠道集包含 **6~7 个渠道**：
   ```
   BAOFU + YEEPAY + JDPAY + LIANLIAN + ALLINPAY + DXM
   [+ BAOFOO_ZL (工行卡)] [+ YEEPAY_ZL (建行卡)]
   ```
   客户如果只签了 BAOFU，其余 5~6 个 ZTX 仍返回「未签」。

### 复现时序

```
T0 — APP检查 → 无缓存 → 查ZTX → 6个渠道未签 → 缓存(10min) → 返回列表 → 弹出重签
T1 — 客户签署了 BAOFU ✔ (但缓存未清除)
T2 — APP再次检查(10分钟内)
    → 缓存命中 → "BAOFU,YEEPAY,JD,LIANLIAN,AIP,DXM"
    → 查ZTX(仅这6个) → BAOFU=已签, 其余5个=未签
    → 结果未回写缓存, 缓存仍存着旧列表
    → 返回5个未签渠道 → 仍弹重签
T3 — 客户签署了 YEEPAY ✔ (但还是同样的逻辑)
T4 — ...重复直到所有渠道签完或10分钟后缓存过期
```

### 排查建议

1. **查 ZTX 返回的具体渠道状态**：日志中搜 `[签约查询]调用支付签约查询结果`，看 ZTX 返回的 `BindCard.isBind=true/false` 和渠道名
2. **确认客户需要签几个渠道**：ICBC 卡需要 7 个，普通卡 6 个
3. **跳过缓存**：直接查 Redis `RESIGN_CACHE_CHANNEL:*` key，或者等 10 分钟自动过期
4. **如果客户确实签了全部渠道但仍然提示** → ZTX 数据问题，联系支付侧确认签约数据是否同步
