#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cls_query.py"
SPEC = importlib.util.spec_from_file_location("cls_query", SCRIPT_PATH)
cls_query = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cls_query)


class ExtractLevelTest(unittest.TestCase):
    def test_extracts_top_level_error(self):
        self.assertEqual(cls_query._extract_level({"level": "ERROR"}, ""), "ERROR")

    def test_extracts_top_level_warn(self):
        self.assertEqual(cls_query._extract_level({"level": "WARN"}, ""), "WARN")

    def test_extracts_fields_level(self):
        log_json = {"fields": {"level": "debug"}}
        self.assertEqual(cls_query._extract_level(log_json, ""), "DEBUG")

    def test_extracts_nested_log_level(self):
        log_json = {"log": {"LEVEL": "trace"}}
        self.assertEqual(cls_query._extract_level(log_json, ""), "TRACE")

    def test_extracts_message_level_fallback(self):
        message = "2026-05-31 14:34:24 WARN c.x.Service - retry later"
        self.assertEqual(cls_query._extract_level({}, message), "WARN")

    def test_defaults_to_info_when_level_missing(self):
        self.assertEqual(cls_query._extract_level({"message": "plain message"}, "plain message"), "INFO")

    def test_parse_api_response_keeps_real_level(self):
        response = {
            "Response": {
                "TotalCount": 1,
                "Results": [
                    {
                        "Time": 1780209264000,
                        "LogJson": json.dumps(
                            {
                                "level": "ERROR",
                                "serviceName": "order",
                                "message": "metrics error",
                            }
                        ),
                    }
                ],
            }
        }

        logs, total_count, total_count_available, is_complete = cls_query.parse_api_response(
            response,
            api_limit=500,
        )

        self.assertEqual(logs[0]["level"], "ERROR")
        self.assertEqual(total_count, 1)
        self.assertTrue(total_count_available)
        self.assertTrue(is_complete)


if __name__ == "__main__":
    unittest.main()
