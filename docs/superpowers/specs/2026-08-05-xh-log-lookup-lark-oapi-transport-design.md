# xh-log-lookup lark_oapi 双通道设计

## 目标

在当前已经完成安全加固的 `xh-log-lookup` 基线上，引入 Hermes 的 `lark_oapi` 优先通道。发送卡片、用户 ID 转换和消息详情读取优先使用 bot SDK；SDK 不可用、凭据缺失或请求失败时降级到现有 lark-cli。来源搜索继续只使用 lark-cli。

## 合并策略

采用选择性合并，不覆盖 Hermes 目录中的完整文件。以下现有行为必须保持：

- `resolve_hermes_session.py` 只解析当前 `HERMES_SESSION_ID` / `HERMES_SESSION_KEY` 绑定的会话，禁止选择全局最近会话。
- ID/KEY 同时存在时必须匹配同一条记录；不一致时即使存在桥接字段也拒绝解析。
- 所有 lark-cli 动态 ID 使用现有 shell 安全转义。
- `resolve_send_target` 继续通过 `getattr` 兼容旧参数对象。
- 提问者 ID 转换失败时清空 mention 目标，只发群卡片，不生成无效 `@`。

## 组件设计

### SDK 加载与凭据

在 `send_feishu_card.py` 内增加惰性 SDK 加载器和单例 client，不新增运行时硬依赖。环境变量 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 优先；缺失时读取 `~/.hermes/.env`，凭据不得写入日志。

脚本作为 CLI 启动且当前解释器无法导入 `lark_oapi` 时，才尝试使用 Hermes venv Python 重新执行。模块被测试或被其他代码导入时不得执行 `os.execv`，避免 import 副作用。

### 传输路由

- `_to_open_id`：`ou_` 直接返回；否则先调用 OAPI contact v3，失败后调用现有 lark-cli，并保留参数转义。
- `_fetch_message_detail`：先调用 OAPI IM v1 get message，将响应映射为现有消息字典；失败后走现有 `messages-mget`。
- `send_card`：卡片完成现有大小处理后，先调用 OAPI create message。用户目标使用 `receive_id_type=open_id`，会话目标使用 `receive_id_type=chat_id`。失败后走现有 lark-cli 命令。
- `_search_messages`：保持 lark-cli `messages-search`，不接入 OAPI。

OAPI 成功时在普通 stdout 和 route audit 中记录 `transport=lark_oapi`；`--quiet-success` 继续不输出成功 JSON。降级路径沿用现有退出码和输出格式。

## 错误处理

SDK 不存在、Hermes venv 不存在、凭据缺失、client 构建失败、OAPI 返回失败或响应字段缺失都不得阻断 lark-cli 降级。只有 OAPI 和 lark-cli 均失败时，才沿用现有发送失败语义。

## 测试设计

所有 OAPI 测试使用 fake module/client，不读取真实凭据、不访问网络、不发送飞书消息。覆盖：

- CLI 模式解释器提升与 import 模式无副作用。
- 环境凭据优先及 `.env` 兜底。
- ID 转换 OAPI 成功、OAPI 失败降级、降级命令转义。
- 消息详情 OAPI 成功映射及失败降级。
- 私聊和群聊 OAPI 发卡参数、成功 transport 审计、失败降级。
- 当前 118 项测试继续通过，包括会话误投、兼容性和 shell 注入回归。

## 文档与日志

更新 `SKILL.md`，说明双通道边界、解释器提升、transport 字段和降级规则；更新 `xh-smart/xh-notes/skill-build-dev-notes.md` 记录实现范围与验证结果。
