#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_feishu_card.py"
SPEC = importlib.util.spec_from_file_location("send_feishu_card", SCRIPT_PATH)
send_feishu_card = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(send_feishu_card)


class ValidateCardDataTest(unittest.TestCase):
    def assert_valid(self, data):
        self.assertIsNone(send_feishu_card.validate_card_data(data))

    def assert_invalid(self, data):
        error = send_feishu_card.validate_card_data(data)
        self.assertIsNotNone(error)
        self.assertEqual(error["status"], "error")
        self.assertEqual(error["error"], "invalid_data_schema")
        self.assertIn("expected_schema", error)
        return error

    def test_valid_schema_passes(self):
        self.assert_valid({
            "summary_fields": [{"label": "服务", "value": "order"}],
            "log_count": 68,
            "table_data": [
                {
                    "headers": ["类型", "次数"],
                    "rows": [["合同查询错误", 68]],
                }
            ],
            "analysis": "近30分钟内共命中68条ERROR。",
            "call_chain": [
                {
                    "level": "ERROR",
                    "time": "16:23:00",
                    "service": "order",
                    "content": "query contract failed",
                }
            ],
        })

    def test_call_chain_cls_style_fields_pass(self):
        self.assert_valid({
            "log_count": 1,
            "call_chain": [
                {
                    "timestamp": "2026-05-31 16:48:14",
                    "serviceName": "order",
                    "level": "WARN",
                    "traceId": "20f1224f851f4050b50d49a1f5d3eb31",
                    "message": "客户调额后可用额度不足",
                }
            ],
        })

    def test_call_chain_unknown_fields_pass(self):
        self.assert_valid({
            "log_count": 1,
            "call_chain": [{"foo": "alpha", "bar": "beta"}],
        })

    def test_unknown_keys_fail(self):
        error = self.assert_invalid({
            "summary": "近30分钟内...",
            "total_logs": "68条",
            "error_breakdown": [],
        })

        self.assertEqual(error["unknown_keys"], ["error_breakdown", "summary", "total_logs"])

    def test_positive_log_count_requires_renderable_content(self):
        error = self.assert_invalid({"log_count": 68})

        self.assertIn("log_count > 0", error["message"])

    def test_zero_log_count_without_content_passes(self):
        self.assert_valid({"log_count": 0})

    def test_summary_fields_missing_label_or_value_fails(self):
        error = self.assert_invalid({
            "summary_fields": [{"label": "服务"}],
            "log_count": 0,
        })

        self.assertIn("summary_fields[0] missing keys: value", error["field_errors"])

    def test_table_rows_must_be_two_dimensional_list(self):
        error = self.assert_invalid({
            "table_data": [
                {
                    "headers": ["类型", "次数"],
                    "rows": ["合同查询错误", 68],
                }
            ],
            "log_count": 0,
        })

        self.assertIn("table_data[0].rows must be a list of lists", error["field_errors"])

    def test_call_chain_item_must_be_object(self):
        error = self.assert_invalid({
            "call_chain": ["not an object"],
            "log_count": 1,
        })

        self.assertIn("call_chain[0] must be an object", error["field_errors"])

    def test_call_chain_item_must_not_be_empty(self):
        error = self.assert_invalid({
            "call_chain": [{}],
            "log_count": 1,
        })

        self.assertIn("call_chain[0] must not be empty", error["field_errors"])

    def test_build_card_renders_cls_style_call_chain_fields(self):
        card = send_feishu_card.build_card(
            title="下单异常",
            color="yellow",
            cls_url="",
            cls_url_expanded="",
            data={
                "log_count": 1,
                "call_chain": [
                    {
                        "timestamp": "2026-05-31 16:48:14",
                        "serviceName": "order",
                        "level": "WARN",
                        "traceId": "20f1224f851f4050b50d49a1f5d3eb31",
                        "message": "客户调额后可用额度不足",
                    }
                ],
            },
        )
        rendered = json.dumps(card, ensure_ascii=False)

        self.assertIn("2026-05-31 16:48:14", rendered)
        self.assertIn("order", rendered)
        self.assertIn("客户调额后可用额度不足", rendered)
        self.assertIn("traceId=20f1224f851f4050b50d49a1f5d3eb31", rendered)
        self.assertNotIn("****", rendered)

    def test_build_card_renders_unknown_call_chain_fields(self):
        card = send_feishu_card.build_card(
            title="日志",
            color="blue",
            cls_url="",
            cls_url_expanded="",
            data={
                "log_count": 1,
                "call_chain": [{"foo": "alpha", "bar": "beta"}],
            },
        )
        rendered = json.dumps(card, ensure_ascii=False)

        self.assertIn("foo=alpha", rendered)
        self.assertIn("bar=beta", rendered)
        self.assertNotIn("****", rendered)


if __name__ == "__main__":
    unittest.main()
