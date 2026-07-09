# novel 需求迭代关键环节记录

|时间|需求背景|需求描述|
|------|------|------|
|2026-07-07 14:08|统一小说创作全流程能力、消除多技能重复维护成本|`skill` 迁移初始化：参考 `xh-log-lookup` 主控格式，将 `novel/novel` 下 5 个 skill（`novel-outline-researcher`/`novel-studio`/`novel-qa`/`novel-style-reference`，及重命名 `yunhui-style-writer`→`mingh-style-writer`）整合为单一 `novel-creator` 主控技能：`SKILL.md` 只做意图分类/路由/强制规则，领域细则下沉两级 `references/`（`common/` 跨领域 + `modules/` 五模式）；去 AI 化规则四份合一到 `common/anti-ai-style.md`（保留「写作跨章 2 次即禁 / QA 单章 5-6 次判定」双档阈值）；`云辉`→`mingh` 全量改名，`novel-studio` 的「云辉风格」改为内部「mingh 风格」并指向 `modules/mingh-style-writer.md`；重写全部内部交叉引用与运行期目录（技能根 `novels/ styles/ reports/`）；`styles/` 3 个风格数据文件与 `ganxiang` 示例报告逐字迁移；原 `novel/novel` 目录保留原样|
