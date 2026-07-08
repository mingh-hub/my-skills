# 报告存放目录

本目录用于存放「质量检测」生成的 QA 报告，以及「调研规划」在用户要求保存时落盘的调研报告。

报告文件名格式：
- QA 报告：`[项目名]-[YYYYMMDD].md`
- 调研报告：`[项目名]-开题调研报告-[YYYYMMDD].md` / `-续写策略报告-` / `-改写策略报告-`

例如：
- `ke-novel-vol2-20260209.md` — 外部项目 ke-novel-continuation 卷二
- `ganxiang-20260209.md` — novel-creator 的 ganxiang 项目
- `standalone-20260209.md` — 用户直接粘贴的独立文本

## 说明

- `ganxiang-20260209.md` 为**迁移自旧技能的示例报告**（0 缺陷的全书 QA 范例），仅作输出格式参考，**不对应本技能内的真实运行项目**，回归测试时请勿当作真实项目复核。
- 注意：该示例早于 `spaces.md` 机制，其"参考设定"未含 `spaces.md`；**新生成的 QA 报告须按 `references/common/output-report-templates.md` 输出 5 模板，将 `spaces.md` 纳入参考设定**（见 `references/modules/qa.md` §4）。
