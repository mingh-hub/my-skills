#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name):
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillConfigTest(unittest.TestCase):
    def test_mapping_table_round_trip_preserves_escaped_pipe(self):
        module = load_module("skill_config")
        rows = [
            {
                "serviceName": "order",
                "project": "order",
                "alias": r"订单\|核心,订单",
                "path": "/workspace/order",
            }
        ]
        rendered = module.render_mapping_table(rows)
        self.assertEqual(module.parse_mapping_table(rendered), rows)

    def test_duplicate_service_is_rejected(self):
        module = load_module("skill_config")
        text = """| serviceName | 项目名 | 别名 | 仓库路径 |
|---|---|---|---|
|`order`|`order`|`订单`|`/a`|
|`order`|`order`|`订单`|`/b`|
"""
        with self.assertRaisesRegex(ValueError, "duplicate serviceName"):
            module.parse_mapping_table(text)

    def test_conflicting_project_paths_are_rejected(self):
        module = load_module("skill_config")
        text = """| serviceName | 项目名 | 别名 | 仓库路径 |
|---|---|---|---|
|`order`|`order`|`订单`|`/a`|
|`order-batch`|`order`|`订单`|`/b`|
"""
        with self.assertRaisesRegex(ValueError, "conflicting paths"):
            module.parse_mapping_table(text)

    def test_invalid_mapping_header_is_rejected(self):
        module = load_module("skill_config")
        text = """| serviceName | 项目 | 仓库路径 |
|---|---|---|
|`order`|`order`|`/a`|
"""
        with self.assertRaisesRegex(ValueError, "mapping table header"):
            module.parse_mapping_table(text)

    def test_unescaped_markdown_pipe_is_rejected(self):
        module = load_module("skill_config")
        rows = [
            {
                "serviceName": "order",
                "project": "order",
                "alias": "订单|核心",
                "path": "/workspace/order",
            }
        ]
        with self.assertRaisesRegex(ValueError, "unescaped pipe"):
            module.render_mapping_table(rows)

    def test_parsed_unescaped_markdown_pipe_is_rejected(self):
        module = load_module("skill_config")
        text = """| serviceName | 项目名 | 别名 | 仓库路径 |
|---|---|---|---|
|`order`|`order`|`订单|核心`|`/a`|
"""
        with self.assertRaisesRegex(ValueError, "unescaped pipe"):
            module.parse_mapping_table(text)

    def test_invalid_cached_path_resolves_from_workspace_roots_without_writing(self):
        module = load_module("skill_config")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "order"
            repo.mkdir()
            (repo / ".git").mkdir()
            skill = root / "SKILL.md"
            original = """| serviceName | 项目名 | 别名 | 仓库路径 |
|---|---|---|---|
|`order`|`order`|`订单`|`/missing/order`|
"""
            skill.write_text(original, encoding="utf-8")
            with mock.patch.dict(os.environ, {"XH_WORKSPACE_ROOTS": str(root)}, clear=False):
                paths = module.read_project_paths(skill)
            self.assertEqual(paths["order"], repo)
            self.assertEqual(skill.read_text(encoding="utf-8"), original)


class ResolveWorkspaceTest(unittest.TestCase):
    def test_check_mode_does_not_mutate_rows_or_write(self):
        module = load_module("resolve_workspace")
        rows = [{"serviceName": "order", "project": "order", "alias": "", "path": ""}]
        original = [dict(row) for row in rows]
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "order"
            repo.mkdir()
            (repo / ".git").mkdir()
            with mock.patch.dict(
                os.environ, {"XH_WORKSPACE_ROOTS": tmpdir}, clear=False
            ), mock.patch.object(module, "update_skill_md") as update:
                exit_code = module.cmd_resolve(rows, dry_run=True)
        self.assertEqual(exit_code, 0)
        self.assertEqual(rows, original)
        update.assert_not_called()

    def test_multiple_workspace_candidates_remain_unresolved(self):
        module = load_module("resolve_workspace")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            roots = [root / "one", root / "two"]
            candidates = []
            for workspace_root in roots:
                repo = workspace_root / "order"
                repo.mkdir(parents=True)
                (repo / ".git").mkdir()
                candidates.append(repo)
            found, actual_candidates = module.find_project("order", roots)
        self.assertIsNone(found)
        self.assertEqual(actual_candidates, candidates)

    def test_set_project_rejects_plain_directory(self):
        module = load_module("resolve_workspace")
        rows = [{"serviceName": "order", "project": "order", "alias": "", "path": ""}]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(module, "update_skill_md") as update:
                exit_code = module.cmd_set_project(rows, "order", tmpdir)
        self.assertEqual(exit_code, 1)
        update.assert_not_called()

    def test_update_skill_md_is_atomic_and_only_replaces_mapping_table(self):
        module = load_module("resolve_workspace")
        rows = [
            {
                "serviceName": "order",
                "project": "order",
                "alias": "订单",
                "path": "/workspace/order",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = Path(tmpdir) / "SKILL.md"
            skill.write_text(
                "before\n\n| serviceName | 项目名 | 别名 | 仓库路径 |\n"
                "|---|---|---|---|\n|`old`|`old`|||\n\nafter\n",
                encoding="utf-8",
            )
            with mock.patch.object(module, "SKILL_MD", skill):
                module.update_skill_md(rows)
            text = skill.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("before\n\n"))
        self.assertTrue(text.endswith("\nafter\n"))
        self.assertIn("|`order`|`order`|`订单`|`/workspace/order`|", text)


if __name__ == "__main__":
    unittest.main()
