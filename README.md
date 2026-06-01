# my-skills

WorkBuddy / Hermes AI agent 技能集合，用于生产/测试环境日志查询、业务异常排查、飞书卡片输出和内部 SSO 会话管理。

## 项目结构

```text
my-skills/
  xh-smart/
    xh-log-lookup/              # 日志查询主控 skill
      SKILL.md                  # 主控规则、服务映射、业务路由和输出约束
      scripts/                  # Python CLI 工具
        cls_query.py            # CLS API / WorkBuddy URL / 本地 Chrome 备用查询
        send_feishu_card.py     # 飞书卡片发送、来源反查、群聊自动 @
        resolve_workspace.py    # 按项目名自动定位本地源码仓库
        validate_query_anchors.py # 校验 reference 中的查询锚点
        skill_config.py         # 内部共享解析工具
      references/
        modules/                # 订单、签约、权益、放款、还款模块 reference
        common/                 # CLS、飞书卡片、Chrome 备用路径等通用 reference
    xh-sso-access/              # SSO 会话管理 skill
      SKILL.md
      agents/openai.yaml
      tools/
        argus_session.py
        test_encrypt.py
      references/
  .claude/skills/run-my-skills/ # Smoke 测试技能
```

## 技能清单

| 技能 | 路径 | 说明 |
| ---- | ---- | ---- |
| xh-log-lookup | `xh-smart/xh-log-lookup/` | 日志查询主控，负责意图分类、业务路由、CLS 查询、统计分档、飞书卡片优先输出和纯文本 fallback |
| xh-sso-access | `xh-smart/xh-sso-access/` | SSO 会话管理，处理 Argus/JANUS/PMP 等内部系统登录态、Cookie 和本地 Chrome 会话 |

`xh-log-lookup` 的业务模块不再拆成独立子技能，而是放在 `references/modules/` 下：

| 模块 reference | 覆盖场景 |
| ---- | ---- |
| `references/modules/order.md` | 下单、借款、预检、试算、拦截、反欺诈 |
| `references/modules/sign.md` | 签约、重签、协议、绑卡、代扣协议 |
| `references/modules/benefit.md` | 权益、会员、VIP、优惠券、乐活卡 |
| `references/modules/loan.md` | 放款、资金路由、loki、提前结清 |
| `references/modules/repay.md` | 还款、扣款、结清、逾期、聚合支付 |

`xh-log-lookup/SKILL.md` 中的 `serviceName` 映射表同时也是客户订单组的服务范围清单。`serviceName` 是 CLS 查询字段，`别名` 是自然语言服务范围入口，`项目名` 仅用于定位源码仓库；`别名`列可以写多个值，用逗号分隔，多个 `serviceName` 也可以共用同一个别名集合，例如 `订单服务,订单`。

## xh-log-lookup 当前行为

- **触发前提**：处理私聊 Tom，或群聊中明确 `@Tom` / 已被 WorkBuddy/Claw 判定为对 Tom 的直接提及。
- **默认环境**：用户未指定环境时查生产环境；只有明确说测试环境时才查测试 topic。
- **服务范围**：按“具体 `serviceName` → 表中别名对应服务组 → 客户订单组全表服务”识别。
- **统计模式**：先用 `cls_query.py --method auto --api-limit 500` 探测；`<=500` 默认精确，`500-1000` 按用户意图选择精确或采样，`>1000` 默认采样；采样统计必须写明“采样统计，非精确统计”。
- **来源反查**：飞书卡片默认用用户原始问题 + 最近 15 分钟窗口反查群聊 @Tom 或私聊 p2p 来源；多条相同 query 命中时按 `create_time` 选择最新消息。
- **WorkBuddy 直问兜底**：如果不是从飞书消息触发、反查不到来源，但配置了 `WORKBUDDY_HOME_CHANNEL_CHAT_ID`，卡片会发送到该 home channel 私聊；未配置时才降级为纯文本。
- **输出规则**：最终结论优先通过 `send_feishu_card.py --quiet-success` 发送飞书卡片；卡片成功后当前会话静默或只做极短确认，失败、来源缺失或候选详情获取失败时才降级为纯文本 fallback。
- **废弃路径**：不再维护 Argus iframe 穿透方案；直接打开完整 CLS URL，WorkBuddy 优先，本地 Chrome 是备用路径。

## 工具

| 工具 | 路径 | 说明 |
| ---- | ---- | ---- |
| `cls_query.py` | `xh-smart/xh-log-lookup/scripts/` | 优先通过 CLS HTTP API 查询日志；默认 `--api-limit 500`，用于统计探测和小数据精确统计；必要时输出 WorkBuddy fallback URL，显式选择时才用本地 Chrome/AppleScript |
| `send_feishu_card.py` | `xh-smart/xh-log-lookup/scripts/` | 发送飞书交互式卡片；支持 `--resolve-chat --query` 来源反查、最近 15 分钟窗口、多命中取最新、WorkBuddy 直问默认私聊兜底、群聊 sender 自动 @、`--quiet-success` 成功静默和纯文本 fallback 状态返回 |
| `resolve_workspace.py` | `xh-smart/xh-log-lookup/scripts/` | 按 `XH_WORKSPACE_ROOTS` 和项目名自动定位本地源码仓库，并可更新 `SKILL.md` 服务映射表中的本地路径 |
| `validate_query_anchors.py` | `xh-smart/xh-log-lookup/scripts/` | 校验业务 reference 中推荐查询的代码锚点是否仍与源码匹配 |
| `skill_config.py` | `xh-smart/xh-log-lookup/scripts/` | 内部共享解析工具，供其它脚本读取/渲染 `SKILL.md` 服务映射表 |
| `argus_session.py` | `xh-smart/xh-sso-access/tools/` | 管理本地 Chrome Argus 会话窗口（创建/复用/校验 cookie/提取 cookie） |
| `test_encrypt.py` | `xh-smart/xh-sso-access/tools/` | PMP SSO RSA 加密实验脚本（需要 `cryptography` 包） |

## 环境要求

- **Python 3.9+** — `xh-log-lookup` 主要工具仅依赖标准库。
- **WorkBuddy/飞书运行环境** — `xh-log-lookup` 通过 `send_feishu_card.py` + `lark-cli` 发送飞书卡片；成功后当前会话静默或极短确认。WorkBuddy 客户端直问建议在 `~/.workbuddy/.env` 配置 `WORKBUDDY_HOME_CHANNEL_CHAT_ID`，用于来源反查失败时发到 home channel 私聊；未配置且无来源时降级为当前会话文本回复。
- **macOS + Google Chrome** — 仅 WorkBuddy 不可用、页面操作失败或需要本地 Chrome 备用提取时需要。
- 可选：`cryptography` Python 包，仅 `xh-sso-access/tools/test_encrypt.py` 需要。

## 仓库路径自动定位

`xh-log-lookup/SKILL.md` 中的仓库路径是本地缓存，不应作为跨同事共享的固定路径。首次使用或路径失效时，配置 `XH_WORKSPACE_ROOTS`，再让 `resolve_workspace.py` 按项目名自动定位真实仓库。

`XH_WORKSPACE_ROOTS` 支持用 `:` 分隔多个根目录。每个根目录会按 `{root}/{projectName}` 和 `{root}/workspace/{projectName}` 查找仓库，所以既可以配置 `/Users/hisense/Documents`，也可以配置 `/Users/hisense/Documents/workspace`。

```bash
export XH_WORKSPACE_ROOTS="/Users/hisense/Documents:/Users/hisense/Documents/workspace:/Users/xxj/sp/xx"
python3 xh-smart/xh-log-lookup/scripts/resolve_workspace.py --check
```

脚本要求候选目录具备源码仓库特征（如 `.git`、`pom.xml`、`build.gradle`、`settings.gradle`、`package.json`）。如果多个根目录下都有可信同名项目，脚本不会自动写入，会提示使用 `--set-project <project> <path>` 人工指定。

## Smoke 测试

```bash
bash .claude/skills/run-my-skills/smoke.sh
```

Smoke 测试会验证现有 Python 工具和 agent 定义：

- 对 `*/tools/*.py` 执行 `--help` 检查（缺依赖标记 SKIP）
- 对 `cls_query.py` 执行 `--method workbuddy --no-browser` URL 构建验证
- 对含锚点表的 `SKILL.md` 执行 `validate_query_anchors.py` 校验
- 对现有 `*/agents/*.yaml` 执行格式校验（当前主要是 `xh-sso-access/agents/openai.yaml`）

新增工具或 reference 后无需修改脚本，测试会按现有目录自动扫描。
