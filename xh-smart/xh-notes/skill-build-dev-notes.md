# xh-log 需求迭代关键环节记录

|时间|需求背景|需求描述|需求验证|
|------|------|------|------|
|2026-07-23|飞书卡片原生表格在列内容较长时需要横向滑动，默认行高也可能裁剪单元格内容，影响日志结果阅读|将 WorkBuddy 版本的表格自适应配置同步到 `xh-log-lookup/scripts/send_feishu_card.py`：`build_table_element` 为所有 `columns[]` 显式设置 `width: "auto"`，表格顶层设置 `row_height: "auto"` 和 `row_max_height: "200px"`，同时覆盖 `table_data` 与 Markdown 表格渲染路径；`row_height: "auto"` 需要飞书客户端 v7.33 及以上，单元格内容超过 200px 时仍按 `row_max_height` 裁剪|![alt text](images/image3.png)|
|2026-07-16 18:45|账务债转成功通知原归属还款模块，缺少独立的 `order-batch → order` 查询链路，期供代偿与合同债转分支容易被混判|新增独立 `debt.md` 债转模块，查询顺序明确为 `orderId → contractNo → 债转短信入口 → traceId 全链路`：只给订单号时先从 `order` 日志提取合同号，再用合同号定位 `com.xhqb.order.batch.service.AccountDebtTransferConsumer#consume` 的 `account-credit-transfer` MQ 入口并提取 traceId；结合一次、二次债转生产 MQ 报文补充 `originalAccountId/currentAccountId` 债转前后合同号、`ZC/ZZC` 一二次债转、前后渠道与资金计划、`billNo`、`claimType` 和 `transferType` 字段语义；补齐 `productClass` 过滤、`PERIOD` 提前返回、`CONTRACT` 回购/债转事件、`syncRepaySingleOrder` 订单与还款计划同步、失败诊断及健康检查；主控将债转、债权转让、期供代偿和债转回购从通用还款路由前置到 `debt.md`，新增 `test_debt_module.py` 保护文件引用、查询顺序、MQ 字段语义、分支语义和源码锚点|
|2026-07-15 17:45|Hold 单排查原由放款模块零散承接，意图边界不清，且旧 `order-batch` 消费链路易被误作当前生产主链|新增独立 `hold.md` 模块，以 `orderId` 为默认主键，补齐进入 H 单、解 H 校验与推送、Loki 失败回 H、取消、超时转单、兜底重路由及 Job 健康检查；主控新增 Hold 关键词与优先路由，明确“拒就赔解H”与普通“拒就赔”的边界；`loan.md` 移除解 H 重复归属，并新增静态单测保护生产锚点和遗留链路边界|
|2026-06-11 20:08|测试环境按需求分支分析代码|主控默认读`master`分支分析代码，生产没问题，但测试环境多跑需求开发分支（新增逻辑不在`master`），易据错分支得出错误结论。重构`update-master-branch.md`为`update-target-branch.md`：按环境选分支（生产`master`、测试需求分支），读代码前分支必须已确认（用户已给直接用、未给先问、答不上按`release-`命名约定+最近活跃度列候选），禁止默认`master`，测试结论须写明实际依据分支；同步SKILL.md主控规则|
|2026-06-11 18:37|主控SKILL.md瘦身|`xh-log-lookup`主控SKILL.md膨胀到405行，按"消重+下沉实现细节"精简到316行：合并飞书发送三处重复、CLS四段示例合并为参数表、统计分档规则改表格、脚本级细节下沉到`references/common`引用文件；所有行为护栏保留，重试节奏改为指向脚本常量`SEARCH_RETRY_DELAYS`/`ZERO_RESULT_RETRY_DELAYS`做唯一事实源|
|2026-06-11 16:08|借款申请模块文档补齐|结合业务说明文档和本地源码（`H5LoanProject`、`weixin_h5api`），将`apply.md`从占位框架补齐为可执行排查文档：拆分自营借款（`LoanController`）与保费分期（`PremiumInstallmentLoanController`，`[保费分期]`前缀）两条申请前链路，补全首查策略、链路追踪、判断规则、失败场景和健康检查，所有日志锚点回源码逐一核实|
|2026-06-04 12:02|借款申请模块初始化|借款申请模块搭建基础架构，后续结合文档补充完善|
|2026-06-02 21:02|签约模块优化与主控路径调整|修正`xh-log-lookup`源码仓库路径，优化签约模块`RESIGN`默认自营、锚点校验表格和健康检查说明|
|2026-06-02 20:34|签约模块查询重构|签约模块查询重构|
|2026-05-31 15:06|飞书卡片查询消息会存在权限过期问题，过期查询降级走`text`通知，权限2小时（可自动续期），7天（需用户授权）|增加过期心跳检测Job|
|2026-05-29 22:09|`Hermes`切换到`WorkBuddy`最大问题是无法指定`WorkBuddy`回复格式，`WorkBuddy`目前默认只能发送`text`格式，不支持`mardown`和`富文本`，`WorkBuddy`网关层也未把消息的`chat_id`传入到业务层，导致`send_feishu_card.py`脚本不知道是谁发的，从哪个群发的，组装的卡片只能走降级路径发送给自己|连接飞书`MCP`，让机器人通过飞书查询消息内容来源（私聊or群聊）和发送人，群内发送卡片时支持@对应发送人|
|2026-05-27 15:19|启用本地浏览器执行`CLS`查询时，本地电脑工作时会强行切换到打开的浏览器|新增`cls-api`调用方式，本地浏览器查询降级，当`cls-api`查询不可用时，启用降级查询方案|
|2026-05-27 02:36|`Hermes`针对业务执行更容易出现结果偏移或描述不准确|`Hermes`切换到`WorkBuddy`|
|2026-05-25 19:06|还款模块|还款模块|
|2026-05-22 20:11|飞书`text`通知支持`mardown`格式有限，如表格，加粗等不支持|新增通过飞书卡片发送查询结果|
|2026-05-21 21:36|下单模块|下单模块|
|2026-05-20 19:40|提高组内处理问题及开发效率|`SKILL`初始化|
