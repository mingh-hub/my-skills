#!/usr/bin/env python3
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_query_anchors.py"


def load_module():
    scripts = str(SCRIPT_PATH.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("validate_query_anchors_behavior", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ValidateQueryAnchorsBehaviorTest(unittest.TestCase):
    def make_row(self, method_entry="`Demo#run`", message="stable prefix"):
        module = load_module()
        return module.AnchorRow(
            skill=Path("demo.md"),
            scene="demo",
            method_entry=method_entry,
            keywords="",
            query=f'serviceName:"order" AND message:"{message}"',
            note="",
        )

    def make_source_index(self, text):
        module = load_module()
        temp_dir = tempfile.TemporaryDirectory()
        source = Path(temp_dir.name) / "src" / "Demo.java"
        source.parent.mkdir()
        source.write_text(text, encoding="utf-8")
        return module, temp_dir, module.build_class_index([Path(temp_dir.name)])

    def test_method_entry_uses_first_inline_code_span(self):
        module = load_module()
        parsed = module.parse_method_entry(
            "`PremiumInstallmentLoanController#loanAbility`（`/premiumLoan/loanAbility`）"
        )
        self.assertEqual(
            parsed,
            (
                "PremiumInstallmentLoanController",
                "PremiumInstallmentLoanController",
                "loanAbility",
            ),
        )

    def test_no_source_roots_marks_rows_unverified(self):
        module = load_module()
        row = module.AnchorRow(
            skill=Path("apply.md"),
            scene="借款能力",
            method_entry="`LoanController#loanAbility`",
            keywords="",
            query='serviceName:"h5-loan" AND message:"[借款能力]"',
            note="",
        )
        result = module.validate_row(row, {}, source_available=False)
        self.assertEqual(result["verification_status"], "unverified")
        self.assertFalse(result["source_available"])

    def test_strict_returns_nonzero_for_unverified_rows(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            reference = Path(tmpdir) / "apply.md"
            reference.write_text(
                "| 场景 | 方法入口 | 日志锚点/关键词 | 推荐查询 | 说明 |\n"
                "|---|---|---|---|---|\n"
                "| 借款能力 | `LoanController#loanAbility` | x | "
                "`serviceName:\"h5-loan\" AND message:\"[借款能力]\"` | x |\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch.object(module, "_default_source_roots", return_value=[]), mock.patch.object(
                sys,
                "argv",
                ["validate_query_anchors.py", "--skill", str(reference), "--summary", "--strict"],
            ), redirect_stdout(output):
                exit_code = module.main()
        self.assertEqual(exit_code, 1)
        self.assertIn("未验证", output.getvalue())

    def test_valid_anchor_is_verified(self):
        module, temp_dir, index = self.make_source_index(
            'class Demo { void run() { log.info("stable prefix"); } }\n'
        )
        self.addCleanup(temp_dir.cleanup)
        result = module.validate_row(self.make_row(), index, source_available=True)
        self.assertEqual(result["verification_status"], "verified")
        self.assertEqual(result["method_status"], "ok")
        self.assertEqual(result["message_status"], "ok")

    def test_partial_source_index_distinguishes_missing_class(self):
        module, temp_dir, index = self.make_source_index(
            'class Demo { void run() { log.info("stable prefix"); } }\n'
        )
        self.addCleanup(temp_dir.cleanup)
        valid = module.validate_row(self.make_row(), index, source_available=True)
        missing = module.validate_row(
            self.make_row(method_entry="`MissingController#run`"),
            index,
            source_available=True,
        )
        self.assertEqual(valid["verification_status"], "verified")
        self.assertEqual(missing["verification_status"], "warning")
        self.assertIn("未找到类", missing["method_detail"])

    def test_missing_method_is_warning(self):
        module, temp_dir, index = self.make_source_index(
            'class Demo { void other() { log.info("stable prefix"); } }\n'
        )
        self.addCleanup(temp_dir.cleanup)
        result = module.validate_row(self.make_row(), index, source_available=True)
        self.assertEqual(result["verification_status"], "warning")
        self.assertIn("未找到方法", result["method_detail"])

    def test_missing_log_anchor_is_warning(self):
        module, temp_dir, index = self.make_source_index(
            "class Demo { void run() {} }\n"
        )
        self.addCleanup(temp_dir.cleanup)
        result = module.validate_row(self.make_row(), index, source_available=True)
        self.assertEqual(result["verification_status"], "warning")
        self.assertEqual(result["missing_message_anchors"], ["stable prefix"])


if __name__ == "__main__":
    unittest.main()
