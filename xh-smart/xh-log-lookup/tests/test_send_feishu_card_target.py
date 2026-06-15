#!/usr/bin/env python3
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_feishu_card.py"
SPEC = importlib.util.spec_from_file_location("send_feishu_card", SCRIPT_PATH)
send_feishu_card = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(send_feishu_card)


class LarkRunTest(unittest.TestCase):
    def test_lark_run_uses_absolute_cli_when_path_does_not_include_lark_cli(self):
        seen = {}

        def fake_run(cmd, shell, capture_output, text, timeout, env):
            seen["cmd"] = cmd
            seen["env"] = env
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=False):
            with mock.patch.object(send_feishu_card.subprocess, "run", side_effect=fake_run):
                result = send_feishu_card._lark_run("lark-cli --help")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            seen["cmd"],
            f"{send_feishu_card.LARK_CLI_ABSOLUTE} --help",
        )
        self.assertEqual(
            seen["env"]["PATH"],
            (
                f"{send_feishu_card.WORKBUDDY_NODE_BIN_DIR}:"
                f"{send_feishu_card.LARK_CLI_BIN_DIR}:"
                "/usr/bin:/bin"
            ),
        )
        self.assertEqual(seen["env"]["LARK_CLI_NO_PROXY"], "1")


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
    def _capture_search_command(self):
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
                zero_result_retry_delays=(),
            )
        finally:
            send_feishu_card._lark_run = original_lark_run
        return captured["cmd"]

    def test_mixed_search_omits_chat_type_at_bot_and_sender_type(self):
        cmd = self._capture_search_command()

        self.assertNotIn("--chat-type", cmd)
        self.assertNotIn("--at-chatter-ids", cmd)
        self.assertNotIn("--sender-type user", cmd)
        self.assertIn("--query '看下我们组近半小时服务异常情况'", cmd)
        self.assertIn("--start '2026-06-01T10:30:00+08:00'", cmd)
        self.assertIn("--page-limit 1", cmd)
        self.assertIn("--page-size 5", cmd)

    def test_search_supports_custom_page_limits(self):
        captured = {}
        original_lark_run = send_feishu_card._lark_run
        try:
            def fake_lark_run(cmd):
                captured["cmd"] = cmd
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                    returncode=0,
                )

            send_feishu_card._lark_run = fake_lark_run
            send_feishu_card._search_messages(
                query="@Tom",
                start="2026-06-01T10:30:00+08:00",
                zero_result_retry_delays=(),
                page_limit=5,
                page_size=10,
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        self.assertIn("--query '@Tom'", captured["cmd"])
        self.assertIn("--page-limit 5", captured["cmd"])
        self.assertIn("--page-size 10", captured["cmd"])

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
                audit=audit,
                source="mixed",
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        search = audit.data["searches"][0]
        self.assertEqual(search["source"], "mixed")
        self.assertFalse(search["uses_chat_type_filter"])
        self.assertEqual(search["total"], 2)
        self.assertEqual(search["message_ids_count"], 2)
        self.assertEqual(search["message_ids_preview"], ["om_1", "om_2"])
        self.assertEqual(search["attempt_count"], 1)
        self.assertNotIn("query", search)

    def test_search_retries_timeout_with_configured_delays(self):
        original_lark_run = send_feishu_card._lark_run
        calls = []
        sleeps = []
        audit = send_feishu_card.RouteAudit()
        try:
            def fake_lark_run(cmd):
                calls.append(cmd)
                raise subprocess.TimeoutExpired(cmd, timeout=15)

            send_feishu_card._lark_run = fake_lark_run
            result = send_feishu_card._search_messages(
                query="看下我们组近半小时服务异常情况",
                start="2026-06-01T10:30:00+08:00",
                audit=audit,
                sleep_func=sleeps.append,
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        self.assertIsNone(result)
        self.assertEqual(len(calls), 4)
        self.assertEqual(sleeps, [5, 10, 15])
        search = audit.data["searches"][0]
        self.assertEqual(search["attempt_count"], 4)
        self.assertTrue(all(item["timeout"] for item in search["attempts"]))

    def test_search_retry_success_does_not_continue(self):
        original_lark_run = send_feishu_card._lark_run
        calls = []
        sleeps = []
        try:
            def fake_lark_run(cmd):
                calls.append(cmd)
                if len(calls) < 3:
                    return SimpleNamespace(
                        stdout='{"ok": false, "error": {"type": "network"}}',
                        stderr="",
                        returncode=4,
                    )
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                    returncode=0,
                )

            send_feishu_card._lark_run = fake_lark_run
            result = send_feishu_card._search_messages(
                query="看下我们组近半小时服务异常情况",
                start="2026-06-01T10:30:00+08:00",
                sleep_func=sleeps.append,
                zero_result_retry_delays=(),
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [5, 10])

    def test_search_retries_zero_result_until_message_index_ready(self):
        original_lark_run = send_feishu_card._lark_run
        calls = []
        sleeps = []
        audit = send_feishu_card.RouteAudit()
        try:
            def fake_lark_run(cmd):
                calls.append(cmd)
                if len(calls) < 3:
                    return SimpleNamespace(
                        stdout='{"ok": true, "data": {"total": 0, "message_ids": []}}',
                        stderr="",
                        returncode=0,
                    )
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 1, "message_ids": ["om_ready"]}}',
                    stderr="",
                    returncode=0,
                )

            send_feishu_card._lark_run = fake_lark_run
            result = send_feishu_card._search_messages(
                query="刚发的群消息",
                start="2026-06-09T10:30:00+08:00",
                audit=audit,
                sleep_func=sleeps.append,
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["message_ids"], ["om_ready"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [3, 4])
        search = audit.data["searches"][0]
        self.assertEqual(search["attempt_count"], 3)
        self.assertEqual(search["zero_result_retry_count"], 2)
        self.assertTrue(search["zero_result_retry_enabled"])
        self.assertTrue(search["attempts"][0]["zero_result"])
        self.assertFalse(search["attempts"][-1]["zero_result"])
        self.assertEqual(search["message_ids_count"], 1)

    def test_search_stops_after_zero_result_retry_delays_are_exhausted(self):
        original_lark_run = send_feishu_card._lark_run
        calls = []
        sleeps = []
        audit = send_feishu_card.RouteAudit()
        try:
            def fake_lark_run(cmd):
                calls.append(cmd)
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0, "message_ids": []}}',
                    stderr="",
                    returncode=0,
                )

            send_feishu_card._lark_run = fake_lark_run
            result = send_feishu_card._search_messages(
                query="刚发的群消息",
                start="2026-06-09T10:30:00+08:00",
                audit=audit,
                sleep_func=sleeps.append,
            )
        finally:
            send_feishu_card._lark_run = original_lark_run

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["total"], 0)
        self.assertEqual(len(calls), 5)
        self.assertEqual(sleeps, [3, 4, 4, 4])
        search = audit.data["searches"][0]
        self.assertEqual(search["attempt_count"], 5)
        self.assertEqual(search["zero_result_retry_count"], 4)
        self.assertTrue(all(item["zero_result"] for item in search["attempts"]))


class ResolveChatMixedSearchTest(unittest.TestCase):
    def _with_lark_run(self, fake_lark_run, func):
        original_lark_run = send_feishu_card._lark_run
        try:
            send_feishu_card._lark_run = fake_lark_run
            return func()
        finally:
            send_feishu_card._lark_run = original_lark_run

    def _resolve_chat(self, query):
        return send_feishu_card.resolve_chat(query, zero_result_retry_delays=())

    def test_p2p_message_routes_to_private_chat(self):
        def fake_lark_run(cmd):
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 1,
                        "messages": [{
                            "message_id": "om_p2p",
                            "chat_id": "oc_private",
                            "chat_type": "p2p",
                            "chat_partner": {"open_id": "ou_partner"},
                            "sender": {"id": "ou_sender", "name": "明海"},
                            "content": "看下我们组近一小时异常情况",
                            "create_time": "2026-06-02 14:46",
                        }],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat("看下我们组近一小时异常情况"),
        )

        self.assertEqual(result["chat_id"], "oc_private")
        self.assertEqual(result["resolved_chat_type"], "p2p")
        self.assertEqual(result["sender_open_id"], "ou_sender")
        self.assertEqual(result["search_strategy"], "latest_query_mixed_15m")

    def test_group_message_requires_bot_mention(self):
        def fake_lark_run(cmd):
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 1,
                        "messages": [{
                            "message_id": "om_group",
                            "chat_id": "oc_group",
                            "chat_name": "客户订单",
                            "chat_type": "group",
                            "sender": {"id": "ou_sender", "name": "李超龙"},
                            "mentions": [{"id": send_feishu_card.BOT_OPEN_ID, "name": "Tom"}],
                            "content": "@Tom 看下我们组近一小时异常情况",
                            "create_time": "2026-06-02 14:46",
                        }],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat("看下我们组近一小时异常情况"),
        )

        self.assertEqual(result["chat_id"], "oc_group")
        self.assertEqual(result["resolved_chat_type"], "group")
        self.assertEqual(result["sender_open_id"], "ou_sender")
        self.assertEqual(result["sender_name"], "李超龙")
        self.assertEqual(result["group_at_bot_count"], 1)
        self.assertEqual(result["group_filtered_count"], 0)

    def test_group_message_without_bot_mention_is_filtered(self):
        def fake_lark_run(cmd):
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 1,
                        "messages": [{
                            "message_id": "om_group",
                            "chat_id": "oc_group",
                            "chat_type": "group",
                            "sender": {"id": "ou_sender", "name": "李超龙"},
                            "mentions": [{"id": "ou_other", "name": "别人"}],
                            "content": "看下我们组近一小时异常情况",
                            "create_time": "2026-06-02 14:46",
                        }],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat("看下我们组近一小时异常情况"),
        )

        self.assertTrue(result["unresolved"])
        self.assertEqual(result["error"], "no_valid_chat_type_or_group_mention")
        self.assertEqual(result["group_candidate_count"], 1)
        self.assertEqual(result["group_filtered_count"], 1)

    def test_latest_valid_group_mention_wins(self):
        def fake_lark_run(cmd):
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 3,
                        "messages": [
                            {
                                "message_id": "om_old",
                                "chat_id": "oc_old",
                                "chat_type": "group",
                                "sender": {"id": "ou_old"},
                                "mentions": [{"id": send_feishu_card.BOT_OPEN_ID}],
                                "create_time": "2026-06-02 14:40",
                            },
                            {
                                "message_id": "om_not_bot",
                                "chat_id": "oc_noise",
                                "chat_type": "group",
                                "sender": {"id": "ou_noise"},
                                "mentions": [{"id": "ou_other"}],
                                "create_time": "2026-06-02 14:59",
                            },
                            {
                                "message_id": "om_new",
                                "chat_id": "oc_new",
                                "chat_type": "group",
                                "sender": {"id": "ou_new"},
                                "mentions": [{"id": send_feishu_card.BOT_OPEN_ID}],
                                "create_time": "2026-06-02 14:50",
                            },
                        ],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat("看下我们组近一小时异常情况"),
        )

        self.assertEqual(result["matched_msg_id"], "om_new")
        self.assertEqual(result["chat_id"], "oc_new")
        self.assertEqual(result["group_at_bot_count"], 2)
        self.assertEqual(result["group_filtered_count"], 1)

    def test_message_ids_fall_back_to_mget_detail(self):
        calls = []

        def fake_lark_run(cmd):
            calls.append(cmd)
            if "+messages-search" in cmd:
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 1, "message_ids": ["om_1"]}}',
                    stderr="",
                    returncode=0,
                )
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "messages": [{
                            "message_id": "om_1",
                            "chat_id": "oc_private",
                            "chat_type": "p2p",
                            "sender": {"id": "ou_sender"},
                            "create_time": "2026-06-02 14:46",
                        }],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat("看下我们组近一小时异常情况"),
        )

        self.assertEqual(result["chat_id"], "oc_private")
        self.assertTrue(any("+messages-mget" in cmd for cmd in calls))

    def test_at_tom_fallback_routes_by_similarity_after_full_query_miss(self):
        calls = []
        source_query = "测试环境 traceId:038490bf1f18b2f8 ,order应用 ,分支:release-5.821.0 ,分析异常原因"

        def fake_lark_run(cmd):
            calls.append(cmd)
            if "+messages-search" in cmd and "--query '@Tom'" not in cmd:
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                    returncode=0,
                )
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 1,
                        "messages": [{
                            "message_id": "om_group",
                            "chat_id": "oc_group",
                            "chat_type": "group",
                            "sender": {"id": "ou_sender", "name": "刘波"},
                            "mentions": [{"id": send_feishu_card.BOT_OPEN_ID, "name": "Tom"}],
                            "content": "@Tom " + source_query,
                            "create_time": "2026-06-04 18:22",
                        }],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat(source_query),
        )

        self.assertEqual(result["chat_id"], "oc_group")
        self.assertEqual(result["matched_msg_id"], "om_group")
        self.assertEqual(result["search_strategy"], "latest_query_mixed_at_tom_fallback_15m")
        self.assertGreaterEqual(result["similarity_score"], 0.99)
        self.assertTrue(any("--query '@Tom'" in cmd and "--page-limit 5" in cmd for cmd in calls))

    def test_at_tom_fallback_prefers_similarity_over_latest_message(self):
        source_query = "测试环境 traceId:038490bf1f18b2f8 ,order应用 ,分支:release-5.821.0 ,分析异常原因A"

        def fake_lark_run(cmd):
            if "+messages-search" in cmd and "--query '@Tom'" not in cmd:
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                    returncode=0,
                )
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 2,
                        "messages": [
                            {
                                "message_id": "om_new_but_less_similar",
                                "chat_id": "oc_new",
                                "chat_type": "group",
                                "sender": {"id": "ou_new"},
                                "mentions": [{"id": send_feishu_card.BOT_OPEN_ID}],
                                "content": "@Tom 测试环境 traceId:038490bf1f18b2f8 ,order应用 ,分支:release-5.821.0 ,分析异常原因B",
                                "create_time": "2026-06-04 18:23",
                            },
                            {
                                "message_id": "om_old_exact",
                                "chat_id": "oc_old",
                                "chat_type": "group",
                                "sender": {"id": "ou_old"},
                                "mentions": [{"id": send_feishu_card.BOT_OPEN_ID}],
                                "content": "@Tom " + source_query,
                                "create_time": "2026-06-04 18:22",
                            },
                        ],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat(source_query),
        )

        self.assertEqual(result["matched_msg_id"], "om_old_exact")
        self.assertEqual(result["chat_id"], "oc_old")

    def test_at_tom_fallback_filters_group_without_bot_mention(self):
        def fake_lark_run(cmd):
            if "+messages-search" in cmd and "--query '@Tom'" not in cmd:
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                    returncode=0,
                )
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 1,
                        "messages": [{
                            "message_id": "om_noise",
                            "chat_id": "oc_noise",
                            "chat_type": "group",
                            "sender": {"id": "ou_noise"},
                            "mentions": [{"id": "ou_other", "name": "别人"}],
                            "content": "@Tom 看下这个 traceId",
                            "create_time": "2026-06-04 18:22",
                        }],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat("看下这个 traceId"),
        )

        self.assertTrue(result["unresolved"])
        self.assertEqual(result["error"], "at_tom_fallback_no_valid_group_mention")
        self.assertEqual(result["group_filtered_count"], 1)

    def test_at_tom_fallback_rejects_ambiguous_similarity(self):
        source_query = "测试环境 traceId:038490bf1f18b2f8 分析异常原因"

        def fake_lark_run(cmd):
            if "+messages-search" in cmd and "--query '@Tom'" not in cmd:
                return SimpleNamespace(
                    stdout='{"ok": true, "data": {"total": 0}}',
                    stderr="",
                    returncode=0,
                )
            return SimpleNamespace(
                stdout=json.dumps({
                    "ok": True,
                    "data": {
                        "total": 2,
                        "messages": [
                            {
                                "message_id": "om_1",
                                "chat_id": "oc_1",
                                "chat_type": "group",
                                "sender": {"id": "ou_1"},
                                "mentions": [{"id": send_feishu_card.BOT_OPEN_ID}],
                                "content": "@Tom " + source_query,
                                "create_time": "2026-06-04 18:21",
                            },
                            {
                                "message_id": "om_2",
                                "chat_id": "oc_2",
                                "chat_type": "group",
                                "sender": {"id": "ou_2"},
                                "mentions": [{"id": send_feishu_card.BOT_OPEN_ID}],
                                "content": "@Tom " + source_query,
                                "create_time": "2026-06-04 18:22",
                            },
                        ],
                    },
                }),
                stderr="",
                returncode=0,
            )

        result = self._with_lark_run(
            fake_lark_run,
            lambda: self._resolve_chat(source_query),
        )

        self.assertTrue(result["unresolved"])
        self.assertEqual(result["error"], "at_tom_fallback_ambiguous_similarity")


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
