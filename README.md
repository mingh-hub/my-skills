# my-skills

WorkBuddy / Hermes AI agent 技能集合，用于生产/测试环境日志查询、本地业务逻辑分析、业务异常排查、飞书卡片输出和内部 SSO 会话管理。

## 项目结构

```text
my-skills/
  xh-smart/
    xh-log-lookup/              # 日志与业务逻辑分析主控 skill
      SKILL.md                  # 模式选择、服务映射、业务路由和输出约束
      scripts/                  # Python CLI 工具
        cls_log_query.py            # CLS API / WorkBuddy URL / 本地 Chrome 备用查询
        resolve_workspace.py    # 按项目名自动定位本地源码仓库
        source_inspect.py       # 受限的只读源码状态、搜索和片段读取
        send_feishu_card.py     # 飞书卡片薄 CLI 入口和兼容导出
        feishu_card.py          # 卡片 schema、日志解析、渲染和大小适配
        feishu_routing.py       # 来源解析、目标优先级和路由审计
        feishu_transport.py     # OAPI/CLI 传输、凭据与 ID 转换
        validate_query_anchors.py # 校验 reference 中的查询锚点
        skill_config.py         # 内部共享解析工具
      tests/                    # 单元测试，覆盖模式路由、源码工具、CLS、卡片 schema/渲染和发送目标
      references/
        modules/                # 借款、订单、签约、权益、Hold、放款、还款、债转 reference
        common/                 # CLS、飞书卡片、Chrome 备用路径等通用 reference
    xh-notes/                   # skill 构建、需求迭代和问题复盘记录
    xh-sso-access/              # SSO 会话管理 skill
      SKILL.md
      agents/openai.yaml
      tools/
        argus_session.py
        test_encrypt.py
      references/
  .agents/skills/run-my-skills/ # 离线 smoke 测试技能
```

## 技能清单

| 技能 | 路径 | 说明 |
| ---- | ---- | ---- |
| xh-log-lookup | `xh-smart/xh-log-lookup/` | 日志与业务逻辑分析主控，支持纯源码、日志诊断、源码与日志联合分析，统一通过飞书卡片优先输出 |
| xh-sso-access | `xh-smart/xh-sso-access/` | SSO 会话管理，处理 Argus/JANUS/PMP 等内部系统登录态、Cookie 和本地 Chrome 会话 |

`xh-smart/xh-notes/` 不是可触发 skill，而是维护资料：

| 记录 | 说明 |
| ---- | ---- |
| `skill-build-dev-notes.md` | 需求迭代、关键变更及 Bug 修复记录 |
| `skill-build-apply-notes.md` | 借款申请模块业务梳理和建模草稿 |
| `skill-build-sign-notes.md` | 签约模块业务梳理和建模草稿 |

`xh-log-lookup` 的业务模块不再拆成独立子技能，而是放在 `references/modules/` 下：

| 模块 reference | 覆盖场景 |
| ---- | ---- |
| `references/modules/apply.md` | 借款首页、借款能力校验、借款内容页、试算、申请前行为轨迹 |
| `references/modules/order.md` | 正式下单、订单生成、下单拦截、反欺诈 |
| `references/modules/sign.md` | 签约、重签、协议、绑卡、代扣协议 |
| `references/modules/benefit.md` | 权益、会员、VIP、优惠券、乐活卡 |
| `references/modules/hold.md` | Hold 单、进入 H、解 H、取消、超时转单、失败回 H |
| `references/modules/loan.md` | 放款、资金路由、loki、提前结清 |
| `references/modules/repay.md` | 还款、扣款、结清、逾期、聚合支付 |
| `references/modules/debt.md` | 债转、债权转让、期供代偿、债转回购 |

`xh-log-lookup/SKILL.md` 中的 `serviceName` 映射表同时也是客户订单组的服务范围清单。`serviceName` 是 CLS 查询字段，`别名` 是自然语言服务范围入口，`项目名` 仅用于定位源码仓库；`别名`列可以写多个值，用逗号分隔，多个 `serviceName` 也可以共用同一个别名集合，例如 `订单服务,订单`。

## xh-log-lookup 当前行为

- **触发前提**：处理私聊 Tom，或群聊中明确 `@Tom` / 已被 WorkBuddy/Claw 判定为对 Tom 的直接提及。
- **三种分析模式**：明确“不查日志、只看代码”或仅问流程/调用链/字段/分支时走 `local_logic`；明确查日志、环境、时间或实例故障时走 `log_diagnosis`；同时要求梳理逻辑和验证实际路径时走 `combined`。代码修改、功能开发、重构和修 Bug 不由本 skill 接管。
- **源码读取规则**：纯源码模式通过 module reference 导航，再用 `source_inspect.py` 验证实际源码；默认读取当前本地分支和未提交工作区内容，不自动 fetch、stash、pull、checkout 或更新仓库，卡片标注仓库、分支、HEAD commit 和 dirty 状态。联合分析发现当前分支与日志目标分支不一致时，标记源码验证阻塞并只交付可用日志证据。
- **自动联合分析**：日志诊断遇到无结果、证据不足、入口不明确、查询锚点失效、字段语义无法确认或无法仅凭日志确定根因时，自动升级为 `combined`；用户明确不查日志时禁止反向升级。
- **默认环境**：用户未指定环境时查生产环境；只有明确说测试环境时才查测试 topic。
- **服务范围**：先判断业务意图，再识别服务范围；业务链路查询优先于服务别名扩范围，只有明确问服务异常、服务健康或服务组情况时才按“具体 `serviceName` → 表中别名对应服务组 → 客户订单组全表服务”扩展。
- **业务路由**：借款首页、首页无额度、借款内容页、预检、借款能力校验、试算、借款失败和申请前轨迹默认走 `references/modules/apply.md`；明确下单、订单生成、下单拦截、反欺诈或下单成功/失败统计时走 `references/modules/order.md`。
- **SQL 条件下沉**：查询前必须把环境、时间、标识符、业务锚点、服务和日志级别等可确定条件拼进 CLS SQL；除非用户明确要求原始日志、全部日志或随机采样，禁止先宽查裸服务范围再从返回样本里筛 `ERROR`、`WARN` 或业务结果。
- **统计模式**：先用 `cls_log_query.py --method auto --api-limit 500` 探测；`<=500` 默认精确，`500-1000` 按用户意图选择精确或采样，`>1000` 默认采样；采样统计必须写明“采样统计，非精确统计”。异常/健康检查默认先单查 `level:"ERROR"`，再单查 `level:"WARN"`，必要时继续按服务、业务锚点或时间窗口拆分。
- **来源反查**：飞书卡片默认用用户原始问题 + 最近 15 分钟窗口反查群聊 `@Tom` 或私聊 p2p 来源；`--source-query` 必须传触发技能的原始问题，不能传摘要、卡片标题或改写后的问题。
- **`@Tom` 候选池兜底**：完整原始问题搜索 0 命中时，`send_feishu_card.py` 会搜索最近窗口内最多 50 条 `@Tom` 群聊候选，仍校验 `mentions` 包含 Tom/BOT_OPEN_ID，再按原始问题相似度选择来源；低相似度、并列或无有效候选时才进入现有 fallback。
- **WorkBuddy 直问兜底**：反查不到来源时默认降级为当前会话纯文本；只有显式传 `--allow-home-channel-fallback` 且配置 `WORKBUDDY_HOME_CHANNEL_CHAT_ID` 时，才允许发送到 home channel 私聊。
- **输出规则**：最终结论优先通过 `send_feishu_card.py --quiet-success` 发送飞书卡片；`log` 保持原日志卡片，`business-logic` 不显示“无匹配日志”或“0 条日志”，`combined` 同时呈现源码表格和日志链路。卡片成功后当前会话静默或只做极短确认，失败、来源缺失或候选详情获取失败时才降级为纯文本 fallback。
- **卡片 schema**：`send_feishu_card.py --data` 顶层只允许 `summary_fields`、`call_chain`、`log_count`、`table_data`、`analysis`；`log_count > 0` 时必须至少提供一种可渲染内容。
- **废弃路径**：不再维护 Argus iframe 穿透方案；直接打开完整 CLS URL，WorkBuddy 优先，本地 Chrome 是备用路径。

## 工具

| 工具 | 路径 | 说明 |
| ---- | ---- | ---- |
| `cls_log_query.py` | `xh-smart/xh-log-lookup/scripts/` | 优先通过 CLS HTTP API 查询日志；默认 `--api-limit 500`，用于统计探测和小数据精确统计；必要时输出 WorkBuddy fallback URL，显式选择时才用本地 Chrome/AppleScript |
| `resolve_workspace.py` | `xh-smart/xh-log-lookup/scripts/` | 按 `XH_WORKSPACE_ROOTS` 和项目名自动定位本地源码仓库，并可更新 `SKILL.md` 服务映射表中的本地路径 |
| `source_inspect.py` | `xh-smart/xh-log-lookup/scripts/` | 只允许访问 `SKILL.md` 映射项目；支持 `--status` 查看分支/commit/dirty、`--search` 搜索源码与配置、`--file` 读取仓库内相对路径片段；拒绝越界、隐藏/构建目录及指向不允许位置的符号链接，搜索最多 200 条，单次读取最多 400 行，不执行任何仓库更新或文件写入 |
| `send_feishu_card.py` | `xh-smart/xh-log-lookup/scripts/` | 飞书卡片薄 CLI 入口；`feishu_card.py` 负责 schema/渲染/28KB 适配，`feishu_routing.py` 负责来源选择和审计，`feishu_transport.py` 负责 OAPI/CLI 发送与 ID 转换；入口保留原参数、JSON 和常用 Python 导出 |
| `validate_query_anchors.py` | `xh-smart/xh-log-lookup/scripts/` | 校验业务 reference 中推荐查询的代码锚点是否仍与源码匹配；常用 `--all --summary` 扫描 `references/modules/*.md` |
| `skill_config.py` | `xh-smart/xh-log-lookup/scripts/` | 内部共享解析工具，供其它脚本读取/渲染 `SKILL.md` 服务映射表 |
| `argus_session.py` | `xh-smart/xh-sso-access/tools/` | 管理本地 Chrome Argus 会话窗口（创建/复用/校验 cookie/提取 cookie） |
| `test_encrypt.py` | `xh-smart/xh-sso-access/tools/` | PMP SSO RSA 加密实验脚本（需要 `cryptography` 包） |

## 环境要求

- **Python 3.10+** — `xh-log-lookup` 核心工具仅依赖标准库，`lark_oapi` 为可选依赖。
- **WorkBuddy/飞书运行环境** — `xh-log-lookup` 通过 `send_feishu_card.py` 和可用的 OAPI/`lark-cli` 通道发送飞书卡片；成功后当前会话静默或极短确认。来源无法确认时默认降级为当前会话文本；`WORKBUDDY_HOME_CHANNEL_CHAT_ID` 只在显式传 `--allow-home-channel-fallback` 的批量或定时任务中启用。
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
bash .agents/skills/run-my-skills/smoke.sh
```

Smoke 全程离线，不访问 CLS、飞书或 Chrome。它会验证：

- `xh-log-lookup/scripts/` 下 6 个公开 CLI 的 `--help`
- `skill_config.py` 离线导入、CLS WorkBuddy URL-only 输出和无源码锚点 advisory JSON
- `xh-log-lookup` 完整单元测试
- 自动发现的 `*/agents/*.yaml` 基本格式

## 单元测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s xh-smart/xh-log-lookup/tests -p 'test_*.py'
```

当前单元测试覆盖：

- `cls_log_query.py` 的输入优先级、完整性状态、参数校验、API 错误体和日志级别解析
- `SKILL.md` 的本地业务逻辑触发、三模式选择、自动升级、纯源码禁用 CLS 和修改类任务排除
- 服务映射 round-trip、工作区只读解析、原子更新、锚点 verified/unverified/strict 行为
- `source_inspect.py` 的项目映射限制、`rg --fixed-strings` 快速路径、纯 Python fallback 和路径/数量边界
- 飞书卡片 schema、UTF-8 字节截断、三种内容模式、来源反查、目标优先级、OAPI/CLI 降级和审计脱敏
- README、allowed-tools、references、服务映射和 CLI 入口的文档契约

## 维护建议

- 修改 `xh-log-lookup/SKILL.md` 的模式选择、服务映射、业务路由、来源反查、SQL 条件下沉、统计完整性或卡片 schema 后，同步更新本 README 的“当前行为”和“工具”说明。
- 新增业务模块 reference 时，补充 `references/modules/` 清单；新增复盘资料时，补充 `xh-notes/` 清单。
- 调整 `apply.md` / `order.md` 边界时，同步检查 README 的业务路由说明，避免“借款失败”和“下单失败”入口混淆。
- 涉及模式路由、源码工具、飞书卡片内容模式/发送、来源选择、SQL 条件下沉、统计完整性或 CLS level 解析的改动，优先补充 `xh-smart/xh-log-lookup/tests/`。
- 修改查询锚点后，先跑 `validate_query_anchors.py`，确认 reference 与源码仍匹配。
