# my-skills

Hermes AI agent 技能集合，用于生产/测试环境日志查询、业务异常排查和内部 SSO 会话管理。

## 项目结构

```text
my-skills/
  xh-smart/
    xh-log-lookup/              # 日志查询主控
      SKILL.md
      agents/openai.yaml
      scripts/                  # Python CLI 工具
        cls_query.py
        validate_query_anchors.py
      references/               # 查询规则、踩坑记录等参考文档
      xh-log-lookup-order/      # 订单模块子技能
      xh-log-lookup-sign/       # 签约模块子技能
      xh-log-lookup-benefit/    # 权益模块子技能
      xh-log-lookup-loan/       # 放款模块子技能
      xh-log-lookup-repay/      # 还款模块子技能
    xh-sso-access/              # SSO 会话管理
      SKILL.md
      agents/openai.yaml
      tools/
        argus_session.py
        test_encrypt.py
      references/
  .claude/skills/run-my-skills/ # Smoke 测试技能
```

## 技能清单

| 技能 | 路径 | 版本 | 说明 |
| ---- | ---- | ---- | ---- |
| xh-log-lookup | `xh-smart/xh-log-lookup/` | 2.0.2 | 日志查询主控，负责意图分类、业务路由、CLS 查询和飞书卡片优先输出，发送失败时降级为飞书兼容文本 |
| xh-log-lookup-order | `xh-smart/xh-log-lookup/xh-log-lookup-order/` | 2.1.0 | 订单模块 — 下单、借款、续签、拦截、反欺诈 |
| xh-log-lookup-sign | `xh-smart/xh-log-lookup/xh-log-lookup-sign/` | 1.0.0 | 签约模块 — 签约、重签、绑卡、代扣协议 |
| xh-log-lookup-benefit | `xh-smart/xh-log-lookup/xh-log-lookup-benefit/` | 1.1.0 | 权益模块 — 会员、优惠券、乐活卡 |
| xh-log-lookup-loan | `xh-smart/xh-log-lookup/xh-log-lookup-loan/` | 1.0.0 | 放款模块 — 资金路由、放款推送、解H |
| xh-log-lookup-repay | `xh-smart/xh-log-lookup/xh-log-lookup-repay/` | 1.1.0 | 还款模块 — 还款、扣款、聚合支付、好友代付 |
| xh-sso-access | `xh-smart/xh-sso-access/` | 2.0.0 | SSO 会话管理 — Argus/JANUS/PMP 登录态维护 |

`xh-log-lookup/SKILL.md` 中的 `serviceName` 映射表同时也是客户订单组的服务范围清单。`serviceName` 是 CLS 查询字段，`别名` 是自然语言服务范围入口，`项目名`仅用于定位源码仓库；`别名`列可以写多个值，用逗号分隔，多个 `serviceName` 也可以共用同一个别名集合，例如 `订单服务,订单`。

## 工具

| 工具 | 路径 | 说明 |
| ---- | ---- | ---- |
| cls_query.py | `xh-smart/xh-log-lookup/scripts/` | 优先通过 CLS HTTP API 查询日志；API 不可用或结果不完整时输出 WorkBuddy fallback URL，显式选择时才用本地 Chrome/AppleScript |
| validate_query_anchors.py | `xh-smart/xh-log-lookup/scripts/` | 校验 SKILL.md 中推荐查询的代码锚点是否与源码匹配 |
| argus_session.py | `xh-smart/xh-sso-access/tools/` | 管理本地 Chrome Argus 会话窗口（创建/复用/校验 cookie/提取 cookie） |
| test_encrypt.py | `xh-smart/xh-sso-access/tools/` | PMP SSO RSA 加密实验脚本（需要 `cryptography` 包） |

## 环境要求

- **macOS** — 仅本地浏览器兜底路径需要 AppleScript 驱动 Google Chrome
- **Python 3.9+** — 主要工具仅依赖标准库，无需 pip install
- **Google Chrome** — 仅 WorkBuddy 不可用、需要本地 Chrome 兜底访问和日志提取时需要
- **WorkBuddy/飞书运行环境** — `xh-log-lookup` 优先通过 `send_feishu_card.py` + `lark-cli` 发送飞书卡片；运行侧可提供当前会话 ID（如 `FEISHU_CURRENT_CHAT_ID` / `AGENT_CURRENT_CHAT_ID`），缺失时用用户原始问题 + 最近时间窗精确反查群聊 @Tom 或私聊 p2p 来源，失败或来源不唯一时降级为当前会话文本回复
- 可选：`cryptography` Python 包（仅 `test_encrypt.py` 需要）

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

自动发现并验证所有 Python 工具和 agent 定义文件：

- 对每个 `*/tools/*.py` 执行 `--help` 检查（缺依赖标记 SKIP）
- 对 `cls_query.py` 执行 `--method workbuddy --no-browser` URL 构建验证
- 对含锚点表的 `SKILL.md` 执行 `validate_query_anchors.py` 校验
- 对每个 `*/agents/*.yaml` 执行格式校验

新增技能后无需修改脚本，工具和定义文件会被自动扫描。
