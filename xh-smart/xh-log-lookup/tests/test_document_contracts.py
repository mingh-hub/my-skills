#!/usr/bin/env python3
import importlib.util
import re
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
SKILL_FILE = SKILL_ROOT / "SKILL.md"
README_FILE = REPO_ROOT / "README.md"
PUBLIC_CLIS = {
    "cls_query.py",
    "resolve_hermes_session.py",
    "resolve_workspace.py",
    "send_feishu_card.py",
    "source_inspect.py",
    "validate_query_anchors.py",
}


def load_skill_config():
    scripts = SKILL_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "skill_config.py"
    spec = importlib.util.spec_from_file_location("document_contract_skill_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocumentContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_text = SKILL_FILE.read_text(encoding="utf-8")
        cls.readme_text = README_FILE.read_text(encoding="utf-8")

    def test_allowed_python_tools_are_the_public_cli_entrypoints(self):
        frontmatter = self.skill_text.split("---", 2)[1]
        allowed = set(
            re.findall(
                r"Bash\(python3 \$\{WORKBUDDY_SKILL_DIR\}/scripts/([^ )]+\.py)",
                frontmatter,
            )
        )
        self.assertEqual(allowed, PUBLIC_CLIS)
        for name in allowed:
            self.assertTrue((SKILL_ROOT / "scripts" / name).is_file(), name)

    def test_references_named_by_skill_exist(self):
        references = set(
            re.findall(
                r"`(references/(?:modules|common)/[^`*]+\.md)`",
                self.skill_text,
            )
        )
        self.assertGreaterEqual(len(references), 16)
        missing = [path for path in references if not (SKILL_ROOT / path).is_file()]
        self.assertEqual(missing, [])

    def test_readme_commands_point_to_real_test_entrypoints(self):
        smoke_path = REPO_ROOT / ".agents/skills/run-my-skills/smoke.sh"
        tests_path = SKILL_ROOT / "tests"
        self.assertTrue(smoke_path.is_file())
        self.assertTrue(tests_path.is_dir())
        self.assertIn("bash .agents/skills/run-my-skills/smoke.sh", self.readme_text)
        self.assertIn("-s xh-smart/xh-log-lookup/tests", self.readme_text)
        self.assertNotIn(".claude/skills/run-my-skills", self.readme_text)

    def test_service_mapping_is_valid_and_has_supported_projects(self):
        rows = load_skill_config().parse_mapping_table(self.skill_text)
        self.assertTrue(rows)
        self.assertEqual(len({row["serviceName"] for row in rows}), len(rows))
        self.assertTrue(all(row["project"] for row in rows))
        self.assertTrue(
            all(not row["path"] or Path(row["path"]).is_absolute() for row in rows)
        )

    def test_all_public_cli_entrypoints_exist(self):
        scripts = SKILL_ROOT / "scripts"
        self.assertEqual(
            {path.name for path in scripts.glob("*.py")} & PUBLIC_CLIS,
            PUBLIC_CLIS,
        )


if __name__ == "__main__":
    unittest.main()
