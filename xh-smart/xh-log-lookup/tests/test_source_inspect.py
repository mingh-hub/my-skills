#!/usr/bin/env python3
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "source_inspect.py"


class SourceInspectTest(unittest.TestCase):
    def load_module(self):
        self.assertTrue(SCRIPT_PATH.exists(), "scripts/source_inspect.py must exist")
        spec = importlib.util.spec_from_file_location("source_inspect", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "demo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "tests@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Tests"],
            check=True,
        )
        source_dir = self.repo / "src"
        source_dir.mkdir()
        self.source_file = source_dir / "Demo.java"
        self.source_file.write_text(
            "class Demo {\n"
            "    void before() {}\n"
            "    void LoanServiceImpl() {}\n"
            "    void after() {}\n"
            "}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "src/Demo.java"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "initial"],
            check=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_status_reports_branch_commit_and_dirty_files(self):
        source_inspect = self.load_module()
        self.source_file.write_text(
            self.source_file.read_text(encoding="utf-8") + "// changed\n",
            encoding="utf-8",
        )

        result = source_inspect.inspect_status(
            "demo",
            project_paths={"demo": self.repo},
        )

        self.assertEqual(result["project"], "demo")
        self.assertEqual(result["path"], str(self.repo.resolve()))
        self.assertTrue(result["branch"])
        self.assertEqual(len(result["head"]), 40)
        self.assertTrue(result["dirty"])
        self.assertIn("src/Demo.java", result["changed_files"])

    def test_status_lists_untracked_files_individually(self):
        source_inspect = self.load_module()
        untracked_file = self.repo / "untracked" / "nested.txt"
        untracked_file.parent.mkdir()
        untracked_file.write_text("new", encoding="utf-8")

        result = source_inspect.inspect_status(
            "demo",
            project_paths={"demo": self.repo},
        )

        self.assertIn("untracked/nested.txt", result["changed_files"])

    def test_git_commands_disable_optional_index_writes(self):
        source_inspect = self.load_module()
        completed = subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="",
            stderr="",
        )

        with mock.patch.object(source_inspect.subprocess, "run", return_value=completed) as run:
            source_inspect._run_git(self.repo, "status", "--porcelain")

        args = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertIn("core.fsmonitor=false", args)
        self.assertIn("core.hooksPath=/dev/null", args)

    def test_git_timeout_is_reported_as_source_inspect_error(self):
        source_inspect = self.load_module()

        with mock.patch.object(
            source_inspect.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["git"], 10),
        ):
            with self.assertRaisesRegex(source_inspect.SourceInspectError, "timed out"):
                source_inspect._run_git(self.repo, "status", "--porcelain")

    def test_search_returns_line_and_context(self):
        source_inspect = self.load_module()

        result = source_inspect.search_source(
            "demo",
            "LoanServiceImpl",
            context=1,
            max_results=50,
            project_paths={"demo": self.repo},
        )

        self.assertEqual(result["match_count"], 1)
        match = result["matches"][0]
        self.assertEqual(match["file"], "src/Demo.java")
        self.assertEqual(match["line"], 3)
        self.assertIn("before", match["before"][0]["text"])
        self.assertIn("after", match["after"][0]["text"])

    def test_search_does_not_follow_symlink_outside_repository(self):
        source_inspect = self.load_module()
        outside_file = Path(self.temp_dir.name) / "Outside.java"
        outside_file.write_text("class EscapedSecret {}\n", encoding="utf-8")
        (self.repo / "src" / "Outside.java").symlink_to(outside_file)

        result = source_inspect.search_source(
            "demo",
            "EscapedSecret",
            context=0,
            max_results=50,
            project_paths={"demo": self.repo},
        )

        self.assertEqual(result["match_count"], 0)

    def test_search_skips_hidden_directories(self):
        source_inspect = self.load_module()
        hidden_file = self.repo / ".secrets" / "Credentials.java"
        hidden_file.parent.mkdir()
        hidden_file.write_text("class HiddenCredential {}\n", encoding="utf-8")

        result = source_inspect.search_source(
            "demo",
            "HiddenCredential",
            context=0,
            max_results=50,
            project_paths={"demo": self.repo},
        )

        self.assertEqual(result["match_count"], 0)

    def test_search_rejects_symlink_to_hidden_file_inside_repository(self):
        source_inspect = self.load_module()
        hidden_file = self.repo / ".secrets" / "Credentials.java"
        hidden_file.parent.mkdir()
        hidden_file.write_text("class SymlinkedCredential {}\n", encoding="utf-8")
        (self.repo / "src" / "Credentials.java").symlink_to(hidden_file)

        result = source_inspect.search_source(
            "demo",
            "SymlinkedCredential",
            context=0,
            max_results=50,
            project_paths={"demo": self.repo},
        )

        self.assertEqual(result["match_count"], 0)

    def test_read_file_returns_numbered_lines(self):
        source_inspect = self.load_module()

        result = source_inspect.read_source_file(
            "demo",
            "src/Demo.java",
            start_line=2,
            end_line=4,
            project_paths={"demo": self.repo},
        )

        self.assertEqual(result["file"], "src/Demo.java")
        self.assertEqual([line["line"] for line in result["lines"]], [2, 3, 4])
        self.assertIn("LoanServiceImpl", result["lines"][1]["text"])

    def test_read_file_rejects_sensitive_hidden_file(self):
        source_inspect = self.load_module()
        hidden_file = self.repo / ".env"
        hidden_file.write_text("TOKEN=secret\n", encoding="utf-8")

        with self.assertRaisesRegex(source_inspect.SourceInspectError, "allowed source or config"):
            source_inspect.read_source_file(
                "demo",
                ".env",
                start_line=1,
                end_line=1,
                project_paths={"demo": self.repo},
            )

    def test_read_file_rejects_skipped_directory(self):
        source_inspect = self.load_module()
        generated_file = self.repo / "target" / "Generated.java"
        generated_file.parent.mkdir()
        generated_file.write_text("class Generated {}\n", encoding="utf-8")

        with self.assertRaisesRegex(source_inspect.SourceInspectError, "allowed source or config"):
            source_inspect.read_source_file(
                "demo",
                "target/Generated.java",
                start_line=1,
                end_line=1,
                project_paths={"demo": self.repo},
            )

    def test_rejects_unmapped_project(self):
        source_inspect = self.load_module()

        with self.assertRaisesRegex(source_inspect.SourceInspectError, "not mapped"):
            source_inspect.inspect_status("missing", project_paths={"demo": self.repo})

    def test_rejects_path_traversal(self):
        source_inspect = self.load_module()

        with self.assertRaisesRegex(source_inspect.SourceInspectError, "inside project"):
            source_inspect.read_source_file(
                "demo",
                "../secret.txt",
                start_line=1,
                end_line=2,
                project_paths={"demo": self.repo},
            )

    def test_rejects_more_than_400_lines(self):
        source_inspect = self.load_module()

        with self.assertRaisesRegex(source_inspect.SourceInspectError, "400"):
            source_inspect.read_source_file(
                "demo",
                "src/Demo.java",
                start_line=1,
                end_line=401,
                project_paths={"demo": self.repo},
            )

    def test_rejects_search_limit_over_200(self):
        source_inspect = self.load_module()

        with self.assertRaisesRegex(source_inspect.SourceInspectError, "200"):
            source_inspect.search_source(
                "demo",
                "Demo",
                context=1,
                max_results=201,
                project_paths={"demo": self.repo},
            )


if __name__ == "__main__":
    unittest.main()
