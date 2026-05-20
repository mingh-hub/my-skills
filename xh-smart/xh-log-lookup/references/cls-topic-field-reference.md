# CLS Topic 字段对照表

## 生产环境 topic

| 属性 | 值 |
|------|---|
| topic_id | `f6748b3a-8ab8-4191-b848-cb90b1598901` |
| CLS UI 显示名称 | `应用日志 / logsvr-prod` |
| 日志集 | `应用日志` |
| 类型 | 应用日志（Java 服务日志） |

### 字段列表（应用日志特征）

**索引字段（精确匹配）:** `timestamp`, `serviceName`, `message`, `traceId`, `level`, `requestId`, `TID`

**可用字段:** `__SOURCE__`, `@timestamp`, `TID`, `beat.@timestamp`, `beat.hostname`, `beat.name`, `beat.version`, `fields.application`, `fields.env`, `fields.level`, `fields.logger`, `fields.message`, `fields.thread`, `fields.timestamp`, `host`, `input.type`, `log.file.path`, `log.offset`, `message`, `offset`, `serviceName`, `source`, `spanId`, `timestamp`, `traceId`

**判定方法:** 看到 `serviceName` 在索引字段中 → 是应用日志 topic，可以正常查询。

---

## ⚠️ 容易误点的 topic

| topic | 显示名称 | 类型 | 字段特征 |
|-------|---------|------|---------|
| `fg-prod` | `应用日志 / fg-prod` | **NGINX 访问日志** | `@timestamp`, `SW_CTX`, `TID`, `auth`, `beat`, `clientgeo`, `clientip`, `cookie.SESSION` |
| `fg-test` | `应用日志 / fg-test` | NGINX 访问日志 | 同上 |

**`fg-prod` 不含 `serviceName`、`message`、`traceId` 等应用日志字段，无法查询业务日志！**

---

## Topic 切换后验证步骤

```
1. 切换 topic 后，检查字段列表中是否出现 serviceName 和 message
2. 如果只看到 SW_CTX/clientgeo/clientip → 切到了 NGINX topic，回退
3. 如果看到 serviceName/message/traceId → 正确，继续注入查询
```

## 搜索过滤器遮挡

当左侧搜索框中存在过滤标签（如 `日志主题名称: f6748b3a`）时：
- topic 树区域显示"暂无数据"
- dismiss 按钮可能不可见

**解决方法:** 点击过滤标签的**文字部分**（如"f6748b3a"），标签会展开显示 dismiss 图标，再点击 dismiss 即可清除。
