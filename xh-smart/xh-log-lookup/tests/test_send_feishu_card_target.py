#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_feishu_card.py"
SPEC = importlib.util.spec_from_file_location("send_feishu_card", SCRIPT_PATH)
send_feishu_card = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(send_feishu_card)


class ResolveSendTargetTest(unittest.TestCase):
    def _args(self, chat=None, resolve_chat=False, source_query="raw question"):
        return SimpleNamespace(
            chat=chat,
            resolve_chat=resolve_chat,
            source_query=source_query,
            resolve_window_minutes=15,
        )

    def _select(
        self,
        args,
        resolver,
        env_chat_id="",
        default_private_chat_id="",
        audit=None,
    ):
        return send_feishu_card.resolve_send_target(
            args=args,
            env_chat_id=env_chat_id,
            chat_key="FEISHU_CURRENT_CHAT_ID" if env_chat_id else "",
            chat_type="group",
            chat_type_key="FEISHU_CURRENT_CHAT_TYPE",
            sender_open_id="ou_env_sender",
            sender_key="FEISHU_CURRENT_SENDER_OPEN_ID",
            default_private_key=(
                "WORKBUDDY_HOME_CHANNEL_CHAT_ID"
                if default_private_chat_id else ""
            ),
            default_private_chat_id=default_private_chat_id,
            resolver=resolver,
            audit=audit,
        )

    def test_chat_argument_has_highest_priority(self):
        def resolver(query, window_minutes, audit=None):
            raise AssertionError("resolver should not be called")

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(chat="oc_manual"),
            resolver,
            env_chat_id="oc_env",
            default_private_chat_id="oc_private",
        )

        self.assertEqual(chat_id, "oc_manual")
        self.assertEqual(chat_source, "--chat")
        self.assertEqual(sender_info, {})
        self.assertEqual(send_meta, {})
        self.assertIsNone(error)

    def test_resolved_feishu_source_wins_over_default_private(self):
        seen = {}

        def resolver(query, window_minutes, audit=None):
            seen["query"] = query
            seen["window_minutes"] = window_minutes
            return {
                "chat_id": "oc_group",
                "chat_type": "group",
                "resolved_chat_type": "group",
                "sender_open_id": "ou_sender",
                "sender_name": "ou_sender",
                "matched_msg_id": "om_msg",
                "matched_count": 1,
                "search_strategy": "latest_query_group_at_bot_15m",
                "selected_time_field": "create_time",
                "selected_time_value": 1780200000000,
            }

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True),
            resolver,
            env_chat_id="oc_env",
            default_private_chat_id="oc_private",
        )

        self.assertEqual(seen["query"], "raw question")
        self.assertEqual(seen["window_minutes"], 15)
        self.assertEqual(chat_id, "oc_group")
        self.assertEqual(chat_source, "latest_query_group_at_bot_15m")
        self.assertEqual(sender_info["sender_open_id"], "ou_sender")
        self.assertEqual(sender_info["chat_type"], "group")
        self.assertEqual(send_meta["matched_msg_id"], "om_msg")
        self.assertTrue(send_meta["source_query_provided"])
        self.assertEqual(send_meta["source_query_length"], len("raw question"))
        self.assertIn("env_chat_conflict", send_meta)
        self.assertIsNone(error)

    def test_resolve_chat_requires_source_query(self):
        def resolver(query, window_minutes, audit=None):
            raise AssertionError("resolver should not be called")

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True, source_query=""),
            resolver,
        )

        self.assertIsNone(chat_id)
        self.assertEqual(chat_source, "")
        self.assertEqual(sender_info, {})
        self.assertEqual(send_meta, {})
        self.assertEqual(error["status"], "error")
        self.assertEqual(error["error"], "missing_source_query")
        self.assertIn("--source-query", error["message"])

    def test_unresolved_source_uses_default_private_chat(self):
        def resolver(query, window_minutes, audit=None):
            return {
                "unresolved": True,
                "error": "no_match",
                "matched_count": 0,
                "search_strategy": "latest_query_mixed_15m",
            }

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True),
            resolver,
            default_private_chat_id="oc_private",
        )

        self.assertEqual(chat_id, "oc_private")
        self.assertEqual(chat_source, "WORKBUDDY_HOME_CHANNEL_CHAT_ID")
        self.assertEqual(sender_info, {})
        self.assertEqual(send_meta["source_resolution"]["status"], "source_unresolved")
        self.assertEqual(send_meta["source_resolution"]["fallback"], "default_private_chat")
        self.assertIsNone(error)

    def test_unresolved_source_records_default_private_fallback_audit(self):
        audit = send_feishu_card.RouteAudit()

        def resolver(query, window_minutes, audit=None):
            return {
                "unresolved": True,
                "error": "no_match",
                "matched_count": 0,
                "search_strategy": "latest_query_mixed_15m",
            }

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True),
            resolver,
            default_private_chat_id="oc_private",
            audit=audit,
        )

        self.assertEqual(chat_id, "oc_private")
        self.assertEqual(chat_source, "WORKBUDDY_HOME_CHANNEL_CHAT_ID")
        self.assertEqual(audit.data["fallback"]["fallback_target"], "default_private_chat")
        self.assertEqual(audit.data["fallback"]["fallback_reason"], "no_match")
        self.assertEqual(audit.data["fallback"]["env_key"], "WORKBUDDY_HOME_CHANNEL_CHAT_ID")
        self.assertIsNone(error)

    def test_resolved_source_without_chat_id_uses_default_private_chat(self):
        def resolver(query, window_minutes, audit=None):
            return {
                "chat_type": "p2p",
                "resolved_chat_type": "p2p",
                "matched_count": 1,
                "search_strategy": "latest_query_p2p_15m",
            }

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True),
            resolver,
            default_private_chat_id="oc_private",
        )

        self.assertEqual(chat_id, "oc_private")
        self.assertEqual(chat_source, "WORKBUDDY_HOME_CHANNEL_CHAT_ID")
        self.assertEqual(sender_info, {})
        self.assertEqual(send_meta["source_resolution"]["error"], "missing_resolved_chat_id")
        self.assertIsNone(error)

    def test_unresolved_source_falls_back_to_current_env_chat_without_private(self):
        def resolver(query, window_minutes, audit=None):
            return {
                "unresolved": True,
                "error": "no_match",
                "matched_count": 0,
                "search_strategy": "latest_query_mixed_15m",
            }

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True),
            resolver,
            env_chat_id="oc_env",
        )

        self.assertEqual(chat_id, "oc_env")
        self.assertEqual(chat_source, "FEISHU_CURRENT_CHAT_ID")
        self.assertEqual(send_meta["source_resolution"]["fallback"], "current_env_chat")
        self.assertIsNone(error)

    def test_unresolved_source_without_any_target_returns_missing_private_target(self):
        def resolver(query, window_minutes, audit=None):
            return {
                "unresolved": True,
                "error": "no_match",
                "matched_count": 0,
                "search_strategy": "latest_query_mixed_15m",
            }

        chat_id, chat_source, sender_info, send_meta, error = self._select(
            self._args(resolve_chat=True),
            resolver,
        )

        self.assertIsNone(chat_id)
        self.assertEqual(chat_source, "")
        self.assertEqual(sender_info, {})
        self.assertTrue(send_meta["source_query_provided"])
        self.assertEqual(send_meta["source_query_length"], len("raw question"))
        self.assertEqual(error["status"], "unresolved")
        self.assertEqual(error["error"], "missing_private_target")
        self.assertEqual(error["source_error"], "no_match")


class SearchMessagesCommandTest(unittest.TestCase):
    def _capture_search_command(self, chat_type, at_bot):
        captured = {}
        original_lark_run = send_feishu_card._lark_run
        try:
            def fake_lark_run(cmd):
                captured["cmd"] = cmd
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                )

            send_feishu_card._lark_run = fake_lark_run
            send_feishu_card._search_messages(
                query="看下我们组近半小时服务异常情况",
                start="2026-06-01T10:30:00+08:00",
                chat_type=chat_type,
                at_bot=at_bot,
            )
        finally:
            send_feishu_card._lark_run = original_lark_run
        return captured["cmd"]

    def test_group_search_uses_at_bot_without_sender_type(self):
        cmd = self._capture_search_command(chat_type="group", at_bot=True)

        self.assertIn("--chat-type 'group'", cmd)
        self.assertIn(f"--at-chatter-ids '{send_feishu_card.BOT_OPEN_ID}'", cmd)
        self.assertNotIn("--sender-type user", cmd)

    def test_p2p_search_omits_at_bot_and_sender_type(self):
        cmd = self._capture_search_command(chat_type="p2p", at_bot=False)

        self.assertIn("--chat-type 'p2p'", cmd)
        self.assertNotIn("--at-chatter-ids", cmd)
        self.assertNotIn("--sender-type user", cmd)

    def test_search_audit_records_result_summary(self):
        original_lark_run = send_feishu_card._lark_run
        audit = send_feishu_card.RouteAudit()
        try:
            def fake_lark_run(cmd):
                return SimpleNamespace(
                    stdout=(
                        '{"ok": true, "data": {"total": 2, '
                        '"message_ids": ["om_1", "om_2"]}}'
                    ),
                    stderr="",
                )

            send_feishu_card._lark_run = fake_lark_run
            send_feishu_card._search_messages(
                query="看下我们组近半小时服务异常情况",
                start="2026-06-01T10:30:00+08:00",
                chat_type="group",
                at_bot=True,
                audit=audit,
                source="group_at_bot",
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        search = audit.data["searches"][0]
        self.assertEqual(search["source"], "group_at_bot")
        self.assertEqual(search["total"], 2)
        self.assertEqual(search["message_ids_count"], 2)
        self.assertEqual(search["message_ids_preview"], ["om_1", "om_2"])
        self.assertNotIn("query", search)


class RouteAuditTest(unittest.TestCase):
    def test_flush_writes_json_without_source_query_text(self):
        source_query = "手机号：15037636828，合同号：CK202602010010752"
        with tempfile.TemporaryDirectory() as tmp:
            audit = send_feishu_card.RouteAudit(tmp)
            audit.set_context(
                source_query=source_query,
                resolve_window_minutes=15,
                start_time="2026-06-01T16:00:00+08:00",
            )
            audit.set_fallback(
                fallback_target="default_private_chat",
                fallback_reason="no_match",
                chat_source="WORKBUDDY_HOME_CHANNEL_CHAT_ID",
                env_key="WORKBUDDY_HOME_CHANNEL_CHAT_ID",
            )

            path = audit.flush()
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            raw = Path(path).read_text(encoding="utf-8")

        self.assertEqual(payload["source_query_length"], len(source_query))
        self.assertNotIn(source_query, raw)
        self.assertNotIn("15037636828", raw)
        self.assertEqual(payload["fallback"]["fallback_target"], "default_private_chat")


if __name__ == "__main__":
    unittest.main()
