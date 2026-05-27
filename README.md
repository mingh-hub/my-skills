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
        send_feishu_card.py
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
| xh-log-lookup | `xh-smart/xh-log-lookup/` | 2.0.2 | 日志查询主控，负责意图分类、业务路由、CLS 查询和飞书卡片输出 |
| xh-log-lookup-order | `xh-smart/xh-log-lookup/xh-log-lookup-order/` | 2.1.0 | 订单模块 — 下单、借款、续签、拦截、反欺诈 |
| xh-log-lookup-sign | `xh-smart/xh-log-lookup/xh-log-lookup-sign/` | 1.0.0 | 签约模块 — 签约、重签、绑卡、代扣协议 |
| xh-log-lookup-benefit | `xh-smart/xh-log-lookup/xh-log-lookup-benefit/` | 1.1.0 | 权益模块 — 会员、优惠券、乐活卡 |
| xh-log-lookup-loan | `xh-smart/xh-log-lookup/xh-log-lookup-loan/` | 1.0.0 | 放款模块 — 资金路由、放款推送、解H |
| xh-log-lookup-repay | `xh-smart/xh-log-lookup/xh-log-lookup-repay/` | 1.1.0 | 还款模块 — 还款、扣款、聚合支付、好友代付 |
| xh-sso-access | `xh-smart/xh-sso-access/` | 2.0.0 | SSO 会话管理 — Argus/JANUS/PMP 登录态维护 |

## 工具

| 工具 | 路径 | 说明 |
| ---- | ---- | ---- |
| cls_query.py | `xh-smart/xh-log-lookup/scripts/` | 优先通过 CLS HTTP API 查询日志；API 不可用或结果不完整时输出 WorkBuddy fallback URL，显式选择时才用本地 Chrome/AppleScript |
| send_feishu_card.py | `xh-smart/xh-log-lookup/scripts/` | 发送飞书交互式卡片（诊断结论、调用链、健康检查），支持 red/yellow/green/blue 四色 |
| validate_query_anchors.py | `xh-smart/xh-log-lookup/scripts/` | 校验 SKILL.md 中推荐查询的代码锚点是否与源码匹配 |
| argus_session.py | `xh-smart/xh-sso-access/tools/` | 管理本地 Chrome Argus 会话窗口（创建/复用/校验 cookie/提取 cookie） |
| test_encrypt.py | `xh-smart/xh-sso-access/tools/` | PMP SSO RSA 加密实验脚本（需要 `cryptography` 包） |

## 环境要求

- **macOS** — 仅本地浏览器兜底路径需要 AppleScript 驱动 Google Chrome
- **Python 3.9+** — 主要工具仅依赖标准库，无需 pip install
- **Google Chrome** — 仅 WorkBuddy 不可用、需要本地 Chrome 兜底访问和日志提取时需要
- 可选：`~/.hermes/.env` 中配置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_HOME_CHANNEL`（飞书卡片发送）
- 可选：`cryptography` Python 包（仅 `test_encrypt.py` 需要）

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
