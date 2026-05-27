# Dubbo ProfileFilter 全链路追踪

## 背景

日志中的 `ProfileFilter` 记录了 Dubbo RPC 调用链路的四阶段标记，用于追踪跨服务调用。

## 标记含义

| 标记 | 含义 | 方向 | 示例 |
|------|------|------|------|
| **CS** | Client Send | 调用方 → 发送请求 | `CS [172.18.31.95:20880] [com.xhqb.order.common.service.SharingAgreementService.sharingAgreementNew] : {...}` |
| **SR** | Server Receive | 提供方 → 收到请求 | 通常不在日志中单独输出，被 CS 代替 |
| **SS** | Server Send | 提供方 → 返回响应 | `SS [172.18.45.27:20880] [8ms] [com.xhqb.cif...queryByIdCard] : {...}` |
| **CR** | Client Receive | 调用方 → 收到响应 | `CR [172.18.31.95:20880] [9ms] [com.xhqb.order...sharingAgreementNew] : {"success":false,"resultCode":"SYS_FAILURES"}` |

完整链路（时间正序）：

```
caller-app CS → callee-app SR → callee-app SS → caller-app CR
```

## 溯源方法论

### 1. 定位入口服务

查到 ERROR 后，用 traceId 无 serviceName 限制查询，看谁最先发起调用：

```text
traceId:"22ba2bf2f47462e1"
```

CLS 返回的 log_count 会列出所有涉及的服务（如 `order`, `order-batch`, `cif`）。

### 2. 按 Chronological 排序重建调用链

从 CLS 提取的全文按时间升序排列后，找到第一个 CS 标记：

```
# 最早: order-batch 发起调用 → order
order-batch CS [172.18.31.95:20880] [com.xhqb.order...SharingAgreementService.sharingAgreementNew]
```

### 3. 追踪完整链路

```
order-batch (Pulsar)
  └─ CS → order:SharingAgreementService.sharingAgreementNew
       └─ CS → cif:CustomerInfoService.queryByIdCard
            └─ SS ← cif: queryByIdCard (返回结果)
       └─ CR ← cif: queryByIdCard
  └─ CR ← order: sharingAgreementNew (返回最终结果)
```

### 4. 关键识别线索

- **线程名**：`pulsar-external-listener-*` → 消息队列消费者触发
- **线程名**：`http-nio-8080-exec-*` → HTTP 请求触发
- **线程名**：`DubboServerHandler-*` → Dubbo 服务端调用
- **线程名**：`DubboClientHandler-*` → Dubbo 客户端超时响应回调
- **IP 端口对**：`CS [目标IP:目标端口]` 和 `SS [源IP:源端口]` 配对可识别调用关系

## 常见链路模式

| 入口 | 中间服务 | 下游 | 线程特征 |
|------|---------|------|---------|
| order-batch (Pulsar) | order | cif | `pulsar-external-listener-*` → `DubboServerHandler-*` |
| h5-loan (HTTP) | — | guide / cif / etc. | `http-nio-8080-exec-*` → `DubboClientHandler-*` |
| order (Dubbo) | — | cif / loki / etc. | `DubboServerHandler-*` → CS → 下游 |

## 注意事项

- 同一个 traceId 可能跨 topic（当前 topic 只收了部分服务），若返回服务数少于预期，可检查是否所有服务都上报到同一个 topic
- ProfileFilter 日志中的 `[Nms]` 是耗时（毫秒），可判断哪一步最慢
- SS/CR 中能看到返回的 JSON 结果，可直接判断是否成功
