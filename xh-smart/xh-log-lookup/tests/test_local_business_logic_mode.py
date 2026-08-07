from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_FILE = SKILL_ROOT / "SKILL.md"


class LocalBusinessLogicModeTest(unittest.TestCase):
    def read_skill(self):
        return SKILL_FILE.read_text(encoding="utf-8")

    def test_frontmatter_triggers_local_business_logic_analysis(self):
        text = self.read_skill()
        frontmatter = text.split("---", 2)[1]

        for phrase in ("本地源码", "业务流程", "调用链", "条件分支", "字段语义"):
            self.assertIn(phrase, frontmatter)

    def test_skill_defines_three_analysis_modes(self):
        text = self.read_skill()

        for mode in ("local_logic", "log_diagnosis", "combined"):
            self.assertIn(mode, text)
        self.assertIn("分析模式选择", text)

    def test_local_logic_forbids_cls_and_uses_source_inspect(self):
        text = self.read_skill()
        self.assertIn("### `local_logic`", text)
        self.assertIn("### `log_diagnosis`", text)
        local_section = text.split("### `local_logic`", 1)[1].split("### `log_diagnosis`", 1)[0]

        self.assertIn("source_inspect.py", local_section)
        self.assertIn("禁止调用 `log_cls_query.py`", local_section)
        self.assertIn("--content-mode business-logic", local_section)

    def test_log_diagnosis_upgrades_to_combined_when_evidence_is_insufficient(self):
        text = self.read_skill()
        self.assertIn("自动升级为 `combined`", text)
        for reason in ("日志无结果", "证据不足", "查询锚点失效", "字段语义无法确认"):
            self.assertIn(reason, text)

    def test_combined_mode_does_not_switch_or_update_source_branch(self):
        text = self.read_skill()
        combined_section = text.split("### `combined`", 1)[1].split(
            "### 数据统计强制约束",
            1,
        )[0]

        self.assertIn("不执行 `update-target-branch.md`", combined_section)
        self.assertIn("当前分支与目标分支不一致", combined_section)
        self.assertIn("源码验证阻塞", combined_section)

    def test_local_logic_records_source_context_in_card(self):
        text = self.read_skill()
        for field in ("业务模块", "仓库", "分支", "Commit", "工作区状态", "分析范围"):
            self.assertIn(field, text)

    def test_skill_excludes_code_modification_tasks(self):
        text = self.read_skill()
        self.assertIn("不处理代码修改、功能开发、重构或修 Bug", text)

    def test_allowed_tools_include_source_inspect(self):
        text = self.read_skill()
        self.assertIn(
            "Bash(python3 ${HERMES_SKILL_DIR}/scripts/source_inspect.py *)",
            text,
        )


if __name__ == "__main__":
    unittest.main()
