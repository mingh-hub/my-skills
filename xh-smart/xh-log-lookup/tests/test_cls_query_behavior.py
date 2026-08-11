#!/usr/bin/env python3
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cls_log_query.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cls_query_behavior", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClsQueryBehaviorTest(unittest.TestCase):
    def test_input_text_takes_precedence_over_default_api(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "cls.txt"
            input_path.write_text(
                "日志条数 2\n"
                "2026-08-06 10:00:00.001 serviceName=order first\n"
                "2026-08-06 10:00:00.002 serviceName=order second\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch.object(
                module, "query_cls_api", side_effect=AssertionError("API must not run")
            ), mock.patch.object(
                sys,
                "argv",
                [
                    "cls_log_query.py",
                    "--query",
                    'serviceName:"order"',
                    "--input-text",
                    str(input_path),
                ],
            ), redirect_stdout(output):
                exit_code = module.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source"], "input-text")
        self.assertEqual(payload["log_count"], 2)
        self.assertEqual(payload["loaded_count"], 2)
        self.assertTrue(payload["is_complete"])

    def test_input_text_unknown_total_is_not_reported_complete(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "cls.txt"
            input_path.write_text(
                "2026-08-06 10:00:00.001 serviceName=order one\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch.object(
                sys,
                "argv",
                [
                    "cls_log_query.py",
                    "--query",
                    'serviceName:"order"',
                    "--input-text",
                    str(input_path),
                ],
            ), redirect_stdout(output):
                exit_code = module.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIsNone(payload["log_count"])
        self.assertEqual(payload["loaded_count"], 1)
        self.assertIsNone(payload["is_complete"])
        self.assertIsNone(payload["has_more"])

    def test_input_text_known_total_can_be_incomplete(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "cls.txt"
            input_path.write_text(
                "日志条数 3\n"
                "2026-08-06 10:00:00.001 serviceName=order one\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch.object(
                sys,
                "argv",
                [
                    "cls_log_query.py",
                    "--query",
                    'serviceName:"order"',
                    "--input-text",
                    str(input_path),
                ],
            ), redirect_stdout(output):
                exit_code = module.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["log_count"], 3)
        self.assertEqual(payload["loaded_count"], 1)
        self.assertFalse(payload["is_complete"])
        self.assertTrue(payload["has_more"])

    def test_api_without_total_count_has_unknown_completeness(self):
        module = load_module()
        output = io.StringIO()
        logs = [
            {
                "timestamp": "2026-08-06 10:00:00.001",
                "serviceName": "order",
                "message": "one",
            }
        ]
        with mock.patch.object(
            module,
            "query_cls_api",
            return_value=(logs, 1, False, None),
        ), mock.patch.object(
            module, "write_text", return_value="/tmp/cls_output.txt"
        ), mock.patch.object(
            sys,
            "argv",
            ["cls_log_query.py", "--query", '*', "--method", "api"],
        ), redirect_stdout(output):
            exit_code = module.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIsNone(payload["log_count"])
        self.assertEqual(payload["loaded_count"], 1)
        self.assertIsNone(payload["is_complete"])
        self.assertIsNone(payload["has_more"])
        self.assertEqual(payload["fallback_method"], "workbuddy")

    def test_require_complete_rejects_unknown_input_completeness(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "cls.txt"
            input_path.write_text(
                "2026-08-06 10:00:00.001 serviceName=order one\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch.object(
                sys,
                "argv",
                [
                    "cls_log_query.py",
                    "--query",
                    'serviceName:"order"',
                    "--input-text",
                    str(input_path),
                    "--require-complete",
                ],
            ), redirect_stdout(output):
                exit_code = module.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error"], "INCOMPLETE_DATA")
        self.assertIsNone(payload["is_complete"])

    def test_parse_api_response_rejects_cls_error_payload(self):
        module = load_module()
        response = {
            "Response": {
                "Error": {"Code": "InvalidParameter", "Message": "bad query"},
                "RequestId": "request-1",
            }
        }
        with self.assertRaisesRegex(RuntimeError, "InvalidParameter.*bad query"):
            module.parse_api_response(response, api_limit=500)

    def test_parse_api_response_does_not_infer_complete_without_total(self):
        module = load_module()
        response = {
            "Response": {
                "Results": [
                    {
                        "Time": 1780209264000,
                        "LogJson": '{"message":"one"}',
                    }
                ]
            }
        }
        _logs, total, total_available, is_complete = module.parse_api_response(
            response, api_limit=500
        )
        self.assertEqual(total, 1)
        self.assertFalse(total_available)
        self.assertIsNone(is_complete)

    def test_positive_cli_parameters_are_validated(self):
        module = load_module()
        output = io.StringIO()
        with mock.patch.object(
            sys,
            "argv",
            ["cls_log_query.py", "--query", "*", "--method", "workbuddy", "--api-limit", "0"],
        ), redirect_stdout(output):
            exit_code = module.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error"], "invalid_arguments")

    def test_time_wait_and_pagination_parameters_are_validated(self):
        module = load_module()
        invalid_options = (
            ("--api-timeout", "0"),
            ("--max-load-more", "-1"),
            ("--delay", "-0.1"),
            ("--wait", "-1"),
            ("--time", "not-a-time-range"),
            ("--expanded-time", "now,now-1d"),
        )
        for option, value in invalid_options:
            with self.subTest(option=option):
                output = io.StringIO()
                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        "cls_log_query.py",
                        "--query",
                        "*",
                        "--method",
                        "workbuddy",
                        option,
                        value,
                    ],
                ), redirect_stdout(output):
                    exit_code = module.main()
                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, 1)
                self.assertEqual(payload["error"], "invalid_arguments")
                self.assertTrue(any(option in message for message in payload["messages"]))

    def test_chinese_query_keeps_api_text_and_builds_ascii_fallback_url(self):
        module = load_module()
        output = io.StringIO()
        query = 'serviceName:"order" AND message:"中文错误"'
        with mock.patch.object(
            sys,
            "argv",
            ["cls_log_query.py", "--query", query, "--method", "workbuddy"],
        ), redirect_stdout(output):
            exit_code = module.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["query"], query)
        self.assertEqual(payload["url_query"], 'serviceName:"order"')
        self.assertNotIn("中文错误", payload["cls_url"])
        self.assertTrue(payload["warnings"])


if __name__ == "__main__":
    unittest.main()
