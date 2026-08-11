#!/usr/bin/env python3
import copy
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_feishu_card.py"


def load_module():
    spec = importlib.util.spec_from_file_location("send_feishu_card_size", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SendFeishuCardSizeTest(unittest.TestCase):
    def _sensitive_card(self, module):
        return module.build_card(
            "客户签约排查",
            "yellow",
            None,
            None,
            {
                "summary_fields": [
                    {"label": "手机号", "value": "13800138000"},
                ],
                "call_chain": [
                    {
                        "level": "INFO",
                        "service": "order",
                        "content": "银行卡号=6222020200001234567",
                    }
                ],
                "table_data": [
                    {
                        "headers": ["身份证号", "姓名", "上游返回"],
                        "rows": [
                            ["11010519491231002X", "张三", "138****8000"],
                        ],
                    }
                ],
                "analysis": "数据源密文=ENC[A1B2C3]，数据源已脱敏/加密，无法确认完整值。",
                "log_count": 1,
            },
        )

    def test_business_sensitive_values_are_preserved_in_all_card_sections(self):
        module = load_module()
        card = self._sensitive_card(module)
        fitted, size_meta = module.fit_card_payload(card)
        payload = module._serialize_card(fitted)

        self.assertFalse(size_meta["truncated"])
        self.assertEqual(fitted, card)
        for value in (
            "13800138000",
            "6222020200001234567",
            "11010519491231002X",
            "张三",
            "138****8000",
            "ENC[A1B2C3]",
        ):
            self.assertIn(value, payload)

    def test_fit_card_uses_utf8_bytes_and_does_not_mutate_input(self):
        module = load_module()
        card = module.build_card(
            "超长中文卡片",
            "blue",
            None,
            None,
            {"analysis": "诊断结论" * 7000, "log_count": 0},
        )
        original = copy.deepcopy(card)
        fitted, size_meta = module.fit_card_payload(card, max_bytes=28000)

        encoded = json.dumps(fitted, ensure_ascii=False).encode("utf-8")
        self.assertLessEqual(len(encoded), 28000)
        self.assertEqual(card, original)
        self.assertTrue(size_meta["truncated"])
        self.assertGreater(size_meta["original_size_bytes"], 28000)
        self.assertIn("内容过长已截断", encoded.decode("utf-8"))

    def test_oapi_and_cli_receive_same_fitted_payload(self):
        module = load_module()
        card = module.build_card(
            "超长中文卡片",
            "blue",
            None,
            None,
            {"analysis": "诊断结论" * 7000, "log_count": 0},
        )
        captured = {}

        def fake_oapi(payload, *_args):
            captured["oapi"] = copy.deepcopy(payload)
            return False, "unavailable"

        def fake_cli(args):
            captured["args"] = list(args)
            return SimpleNamespace(
                stdout='{"ok": true, "data": {"message_id": "om_cli"}}', stderr=""
            )

        with mock.patch.object(module, "_send_card_via_oapi", side_effect=fake_oapi), mock.patch.object(
            module, "_lark_run", side_effect=fake_cli
        ):
            module.send_card("oc_chat", card, "test")

        content = captured["args"][captured["args"].index("--content") + 1]
        self.assertEqual(json.loads(content), captured["oapi"])
        self.assertLessEqual(len(content.encode("utf-8")), 28000)

    def test_oapi_and_cli_preserve_same_sensitive_plaintext_payload(self):
        module = load_module()
        card = self._sensitive_card(module)
        captured = {}

        def fake_oapi(payload, *_args):
            captured["oapi"] = copy.deepcopy(payload)
            return False, "unavailable"

        def fake_cli(args):
            captured["args"] = list(args)
            return SimpleNamespace(
                stdout='{"ok": true, "data": {"message_id": "om_cli"}}', stderr=""
            )

        with mock.patch.object(
            module, "_send_card_via_oapi", side_effect=fake_oapi
        ), mock.patch.object(module, "_lark_run", side_effect=fake_cli):
            module.send_card("oc_chat", card, "test")

        content = captured["args"][captured["args"].index("--content") + 1]
        self.assertEqual(json.loads(content), captured["oapi"])
        for value in (
            "13800138000",
            "6222020200001234567",
            "11010519491231002X",
            "张三",
        ):
            self.assertIn(value, content)


if __name__ == "__main__":
    unittest.main()
