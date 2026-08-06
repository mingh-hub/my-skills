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


if __name__ == "__main__":
    unittest.main()
