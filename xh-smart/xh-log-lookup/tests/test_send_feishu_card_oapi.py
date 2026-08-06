#!/usr/bin/env python3
import importlib
import importlib.util
import json
import os
import shlex
import socket
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_feishu_card.py"
SPEC = importlib.util.spec_from_file_location("send_feishu_card_oapi", SCRIPT_PATH)
send_feishu_card = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(send_feishu_card)


def command_argv(command):
    return shlex.split(command) if isinstance(command, str) else list(command)


_NETWORK_PATCHER = mock.patch.object(
    socket.socket,
    "connect",
    side_effect=AssertionError("OAPI tests must not access the network"),
)


def setUpModule():
    _NETWORK_PATCHER.start()


def tearDownModule():
    _NETWORK_PATCHER.stop()


class OapiRuntimeTest(unittest.TestCase):
    def setUp(self):
        send_feishu_card._LARK_OAPI_MODULE = None
        send_feishu_card._LARK_OAPI_IMPORT_FAILED = False
        send_feishu_card._LARK_OAPI_CLIENT = None
        send_feishu_card._LARK_OAPI_CLIENT_FAILED = False

    def test_import_lark_oapi_caches_imported_module(self):
        sdk = object()
        with mock.patch.object(importlib, "import_module", return_value=sdk) as imported:
            self.assertIs(send_feishu_card._import_lark_oapi(), sdk)
            self.assertIs(send_feishu_card._import_lark_oapi(), sdk)

        imported.assert_called_once_with("lark_oapi")

    def test_import_lark_oapi_failure_is_cached_for_cli_fallback(self):
        with mock.patch.object(
            importlib, "import_module", side_effect=RuntimeError("broken sdk")
        ) as imported:
            self.assertIsNone(send_feishu_card._import_lark_oapi())
            self.assertIsNone(send_feishu_card._import_lark_oapi())

        imported.assert_called_once_with("lark_oapi")

    def test_load_env_credentials_prefers_process_environment(self):
        with mock.patch.dict(
            os.environ,
            {"FEISHU_APP_ID": "env-id", "FEISHU_APP_SECRET": "env-secret"},
            clear=True,
        ), mock.patch("builtins.open") as opened:
            credentials = send_feishu_card._load_env_credentials()

        self.assertEqual(credentials, ("env-id", "env-secret"))
        opened.assert_not_called()

    def test_load_env_credentials_falls_back_to_hermes_env_file(self):
        env_text = "FEISHU_APP_ID=file-id\nFEISHU_APP_SECRET=file-secret\n"
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "builtins.open", mock.mock_open(read_data=env_text)
        ):
            credentials = send_feishu_card._load_env_credentials()

        self.assertEqual(credentials, ("file-id", "file-secret"))

    def test_lark_oapi_client_builds_once(self):
        builder = mock.Mock()
        builder.app_id.return_value = builder
        builder.app_secret.return_value = builder
        builder.log_level.return_value = builder
        client = object()
        builder.build.return_value = client
        sdk = SimpleNamespace(
            Client=SimpleNamespace(builder=mock.Mock(return_value=builder)),
            LogLevel=SimpleNamespace(ERROR="error"),
        )

        with mock.patch.object(send_feishu_card, "_import_lark_oapi", return_value=sdk), \
                mock.patch.object(
                    send_feishu_card,
                    "_load_env_credentials",
                    return_value=("app-id", "app-secret"),
                ):
            self.assertIs(send_feishu_card._lark_oapi_client(), client)
            self.assertIs(send_feishu_card._lark_oapi_client(), client)

        sdk.Client.builder.assert_called_once_with()
        builder.app_id.assert_called_once_with("app-id")
        builder.app_secret.assert_called_once_with("app-secret")
        builder.log_level.assert_called_once_with("error")
        builder.build.assert_called_once_with()

    def test_lark_oapi_client_does_not_load_credentials_without_sdk(self):
        with mock.patch.object(
            send_feishu_card, "_import_lark_oapi", return_value=None
        ), mock.patch.object(
            send_feishu_card, "_load_env_credentials"
        ) as load_credentials:
            self.assertIsNone(send_feishu_card._lark_oapi_client())

        load_credentials.assert_not_called()

    def test_relaunch_uses_hermes_python_only_when_sdk_is_missing(self):
        candidate = "/tmp/hermes-python"
        with mock.patch.object(
            send_feishu_card, "HERMES_PYTHON_CANDIDATES", (candidate,)
        ), mock.patch.object(
            send_feishu_card, "_import_lark_oapi", return_value=None
        ), mock.patch.object(
            send_feishu_card.os.path, "isfile", return_value=True
        ), mock.patch.object(
            send_feishu_card.os, "access", return_value=True
        ), mock.patch.object(send_feishu_card.os, "execv") as execv:
            send_feishu_card._maybe_relaunch_with_hermes_python()

        execv.assert_called_once_with(candidate, [candidate] + sys.argv)

    def test_relaunch_does_nothing_when_sdk_is_available(self):
        with mock.patch.object(
            send_feishu_card, "_import_lark_oapi", return_value=object()
        ), mock.patch.object(send_feishu_card.os, "execv") as execv:
            send_feishu_card._maybe_relaunch_with_hermes_python()

        execv.assert_not_called()


class OapiLookupTest(unittest.TestCase):
    def test_to_open_id_uses_oapi_before_cli(self):
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(user=SimpleNamespace(open_id="ou_oapi")),
        )
        get_user = mock.Mock(return_value=response)
        client = SimpleNamespace(
            contact=SimpleNamespace(
                v3=SimpleNamespace(user=SimpleNamespace(get=get_user))
            )
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_get_user_request", return_value=object()
        ), mock.patch.object(send_feishu_card, "_lark_run") as cli:
            result = send_feishu_card._to_open_id("tenant-user")

        self.assertEqual(result, "ou_oapi")
        get_user.assert_called_once()
        cli.assert_not_called()

    def test_to_open_id_falls_back_to_shell_safe_cli(self):
        uid = "user'; touch /tmp/injected; '"
        cli_response = SimpleNamespace(
            stdout=json.dumps(
                {"ok": True, "data": {"user": {"open_id": "ou_cli"}}}
            ),
            stderr="",
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=None
        ), mock.patch.object(
            send_feishu_card, "_lark_run", return_value=cli_response
        ) as cli:
            result = send_feishu_card._to_open_id(uid)

        self.assertEqual(result, "ou_cli")
        argv = command_argv(cli.call_args.args[0])
        self.assertEqual(argv[argv.index("--user-id") + 1], uid)

    def test_fetch_message_detail_uses_oapi_mapping_and_audit(self):
        item = SimpleNamespace(
            message_id="om_1",
            chat_id="oc_1",
            chat_type="group",
            create_time="100",
            update_time="101",
            sender=SimpleNamespace(id="ou_sender", sender_name="Sender Name"),
            body=SimpleNamespace(content='{"text":"@Tom question"}'),
            mentions=[
                SimpleNamespace(
                    id=send_feishu_card.BOT_OPEN_ID,
                    id_type="open_id",
                    key="@_user_1",
                    name="Tom",
                    tenant_key="tenant",
                )
            ],
        )
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(items=[item]),
        )
        get_message = mock.Mock(return_value=response)
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(message=SimpleNamespace(get=get_message))
            )
        )
        audit = SimpleNamespace(add_mget=mock.Mock())

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_get_message_request", return_value=object()
        ), mock.patch.object(send_feishu_card, "_lark_run") as cli:
            message, error = send_feishu_card._fetch_message_detail(
                "om_1", audit=audit, source="mixed"
            )

        self.assertEqual(error, "")
        self.assertEqual(message["sender"]["id"], "ou_sender")
        self.assertEqual(message["sender"]["name"], "Sender Name")
        self.assertEqual(message["body"]["content"], '{"text":"@Tom question"}')
        self.assertEqual(message["mentions"][0]["name"], "Tom")
        self.assertEqual(message["timestamp"], "100")
        self.assertEqual(audit.add_mget.call_args.args[0]["transport"], "lark_oapi")
        get_message.assert_called_once()
        cli.assert_not_called()

    def test_fetch_message_detail_oapi_exception_falls_back_to_safe_cli(self):
        msg_id = "om_1'; touch /tmp/injected; '"
        get_message = mock.Mock(side_effect=RuntimeError("oapi unavailable"))
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(message=SimpleNamespace(get=get_message))
            )
        )
        cli_response = SimpleNamespace(
            stdout=json.dumps(
                {
                    "ok": True,
                    "data": {
                        "messages": [
                            {
                                "message_id": msg_id,
                                "chat_id": "oc_cli",
                                "chat_type": "group",
                                "sender": {"id": "ou_cli_sender"},
                            }
                        ]
                    },
                }
            ),
            stderr="",
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_get_message_request", return_value=object(),
            create=True,
        ), mock.patch.object(
            send_feishu_card, "_lark_run", return_value=cli_response
        ) as cli:
            message, error = send_feishu_card._fetch_message_detail(msg_id)

        self.assertEqual(error, "")
        self.assertEqual(message["chat_id"], "oc_cli")
        argv = command_argv(cli.call_args.args[0])
        self.assertEqual(argv[argv.index("--message-ids") + 1], msg_id)

    def test_fetch_message_detail_cli_unavailable_returns_failure(self):
        audit = SimpleNamespace(add_mget=mock.Mock())
        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=None
        ), mock.patch.object(
            send_feishu_card,
            "_lark_run",
            side_effect=FileNotFoundError("lark-cli unavailable"),
        ):
            message, error = send_feishu_card._fetch_message_detail(
                "om_1", audit=audit, source="mixed"
            )

        self.assertIsNone(message)
        self.assertIn("FileNotFoundError", error)
        self.assertFalse(audit.add_mget.call_args.args[0]["ok"])

    def test_fetch_message_detail_missing_chat_type_falls_back_to_cli(self):
        item = SimpleNamespace(
            message_id="om_1",
            chat_id="oc_oapi",
            create_time="100",
            update_time="101",
            sender=SimpleNamespace(id="ou_sender", sender_name="Sender Name"),
            body=SimpleNamespace(content='{"text":"question"}'),
            mentions=[],
        )
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(items=[item]),
        )
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(get=mock.Mock(return_value=response))
                )
            )
        )
        cli_response = SimpleNamespace(
            stdout=json.dumps(
                {
                    "ok": True,
                    "data": {
                        "messages": [
                            {
                                "message_id": "om_1",
                                "chat_id": "oc_cli",
                                "chat_type": "group",
                                "sender": {"id": "ou_sender"},
                            }
                        ]
                    },
                }
            ),
            stderr="",
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_get_message_request", return_value=object()
        ), mock.patch.object(
            send_feishu_card, "_lark_run", return_value=cli_response
        ) as cli:
            message, error = send_feishu_card._fetch_message_detail("om_1")

        self.assertEqual(error, "")
        self.assertEqual(message["chat_id"], "oc_cli")
        cli.assert_called_once()

    def test_fetch_message_detail_incomplete_oapi_fields_fall_back_to_cli(self):
        cases = {
            "missing chat_id": {"chat_id": ""},
            "missing sender id": {"sender": SimpleNamespace(id="")},
            "missing body": {"body": None},
            "missing group mentions": {"mentions": None},
        }
        cli_response = SimpleNamespace(
            stdout=json.dumps(
                {
                    "ok": True,
                    "data": {
                        "messages": [
                            {
                                "message_id": "om_1",
                                "chat_id": "oc_cli",
                                "chat_type": "group",
                                "sender": {"id": "ou_cli_sender"},
                                "body": {"content": '{"text":"question"}'},
                                "mentions": [
                                    {"id": send_feishu_card.BOT_OPEN_ID}
                                ],
                            }
                        ]
                    },
                }
            ),
            stderr="",
        )

        for name, overrides in cases.items():
            with self.subTest(name=name):
                fields = {
                    "message_id": "om_1",
                    "chat_id": "oc_oapi",
                    "chat_type": "group",
                    "create_time": "100",
                    "update_time": "101",
                    "sender": SimpleNamespace(
                        id="ou_sender", sender_name="Sender Name"
                    ),
                    "body": SimpleNamespace(content='{"text":"question"}'),
                    "mentions": [
                        SimpleNamespace(
                            id=send_feishu_card.BOT_OPEN_ID,
                            id_type="open_id",
                            key="@_user_1",
                            name="Tom",
                            tenant_key="tenant",
                        )
                    ],
                }
                fields.update(overrides)
                item = SimpleNamespace(**fields)
                response = SimpleNamespace(
                    success=lambda: True,
                    data=SimpleNamespace(items=[item]),
                )
                client = SimpleNamespace(
                    im=SimpleNamespace(
                        v1=SimpleNamespace(
                            message=SimpleNamespace(
                                get=mock.Mock(return_value=response)
                            )
                        )
                    )
                )

                with mock.patch.object(
                    send_feishu_card,
                    "_lark_oapi_client",
                    return_value=client,
                ), mock.patch.object(
                    send_feishu_card,
                    "_oapi_get_message_request",
                    return_value=object(),
                ), mock.patch.object(
                    send_feishu_card,
                    "_lark_run",
                    return_value=cli_response,
                ) as cli:
                    message, error = send_feishu_card._fetch_message_detail(
                        "om_1"
                    )

                self.assertEqual(error, "")
                self.assertEqual(message["chat_id"], "oc_cli")
                cli.assert_called_once()

    def test_resolve_chat_message_id_uses_cli_detail_when_oapi_lacks_chat_type(self):
        item = SimpleNamespace(
            message_id="om_1",
            chat_id="oc_oapi",
            create_time="100",
            update_time="101",
            sender=SimpleNamespace(id="ou_sender", sender_name="Sender Name"),
            body=SimpleNamespace(content='{"text":"question"}'),
            mentions=[],
        )
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(items=[item]),
        )
        get_message = mock.Mock(return_value=response)
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(get=get_message)
                )
            )
        )
        cli_calls = []

        def fake_lark_run(cmd):
            cli_calls.append(cmd)
            if "+messages-search" in cmd:
                payload = {
                    "ok": True,
                    "data": {"total": 1, "message_ids": ["om_1"]},
                }
            else:
                payload = {
                    "ok": True,
                    "data": {
                        "messages": [
                            {
                                "message_id": "om_1",
                                "chat_id": "oc_cli",
                                "chat_type": "p2p",
                                "sender": {"id": "ou_sender"},
                                "create_time": "2026-06-02 14:46",
                            }
                        ]
                    },
                }
            return SimpleNamespace(
                stdout=json.dumps(payload), stderr="", returncode=0
            )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_get_message_request", return_value=object()
        ), mock.patch.object(
            send_feishu_card, "_lark_run", side_effect=fake_lark_run
        ):
            result = send_feishu_card.resolve_chat(
                "question", zero_result_retry_delays=()
            )

        self.assertEqual(result["chat_id"], "oc_cli")
        self.assertEqual(result["resolved_chat_type"], "p2p")
        self.assertTrue(any("+messages-mget" in cmd for cmd in cli_calls))
        get_message.assert_called_once()


class OapiSendTest(unittest.TestCase):
    def test_create_message_request_contains_interactive_card(self):
        class RequestBody:
            pass

        class RequestBuilder:
            def receive_id_type(self, value):
                self.receive_id_type_value = value
                return self

            def request_body(self, value):
                self.request_body_value = value
                return self

            def build(self):
                return SimpleNamespace(
                    receive_id_type=self.receive_id_type_value,
                    body=self.request_body_value,
                )

        builder = RequestBuilder()
        request_type = SimpleNamespace(builder=lambda: builder)
        modules = {
            "lark_oapi": ModuleType("lark_oapi"),
            "lark_oapi.api": ModuleType("lark_oapi.api"),
            "lark_oapi.api.im": ModuleType("lark_oapi.api.im"),
            "lark_oapi.api.im.v1": ModuleType("lark_oapi.api.im.v1"),
        }
        modules["lark_oapi.api.im.v1"].CreateMessageRequest = request_type
        modules["lark_oapi.api.im.v1"].CreateMessageRequestBody = RequestBody

        with mock.patch.dict(sys.modules, modules):
            request = send_feishu_card._oapi_create_message_request(
                {"schema": "2.0"}, "ou_target", "open_id"
            )

        self.assertEqual(request.receive_id_type, "open_id")
        self.assertEqual(request.body.receive_id, "ou_target")
        self.assertEqual(request.body.msg_type, "interactive")
        self.assertEqual(json.loads(request.body.content), {"schema": "2.0"})

    def test_send_card_via_oapi_uses_open_id_for_user(self):
        captured = {}
        request = object()
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="om_sent"),
        )
        create_message = mock.Mock(return_value=response)
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(message=SimpleNamespace(create=create_message))
            )
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card,
            "_oapi_create_message_request",
            side_effect=lambda card, receive_id, receive_id_type: captured.update(
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            ) or request,
        ):
            result = send_feishu_card._send_card_via_oapi(
                {}, "user", None, "ou_target"
            )

        self.assertEqual(result, (True, "om_sent"))
        self.assertEqual(
            captured,
            {"receive_id": "ou_target", "receive_id_type": "open_id"},
        )
        create_message.assert_called_once_with(request)

    def test_send_card_via_oapi_uses_chat_id_for_chat(self):
        captured = {}
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(
                        create=mock.Mock(
                            return_value=SimpleNamespace(
                                success=lambda: True,
                                data=SimpleNamespace(message_id="om_group"),
                            )
                        )
                    )
                )
            )
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card,
            "_oapi_create_message_request",
            side_effect=lambda card, receive_id, receive_id_type: captured.update(
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            ) or object(),
        ):
            result = send_feishu_card._send_card_via_oapi(
                {}, "chat", "oc_target", None
            )

        self.assertEqual(result, (True, "om_group"))
        self.assertEqual(
            captured,
            {"receive_id": "oc_target", "receive_id_type": "chat_id"},
        )

    def test_send_card_via_oapi_rejects_success_without_message_id(self):
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(
                        create=mock.Mock(
                            return_value=SimpleNamespace(
                                success=lambda: True,
                                data=SimpleNamespace(message_id=""),
                            )
                        )
                    )
                )
            )
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_create_message_request", return_value=object()
        ):
            result = send_feishu_card._send_card_via_oapi(
                {}, "chat", "oc_target", None
            )

        self.assertEqual(result, (False, "missing message_id"))

    def test_send_card_missing_oapi_message_id_falls_back_to_cli(self):
        client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(
                        create=mock.Mock(
                            return_value=SimpleNamespace(
                                success=lambda: True,
                                data=SimpleNamespace(message_id=None),
                            )
                        )
                    )
                )
            )
        )
        cli_response = SimpleNamespace(
            stdout=json.dumps(
                {"ok": True, "data": {"message_id": "om_cli"}}
            ),
            stderr="",
        )

        with mock.patch.object(
            send_feishu_card, "_lark_oapi_client", return_value=client
        ), mock.patch.object(
            send_feishu_card, "_oapi_create_message_request", return_value=object()
        ), mock.patch.object(
            send_feishu_card, "_lark_run", return_value=cli_response
        ) as cli, mock.patch.object(send_feishu_card.sys, "stderr"):
            send_feishu_card.send_card(
                "oc_target",
                {"schema": "2.0", "body": {"elements": []}},
                "--chat-id",
                quiet_success=True,
            )

        cli.assert_called_once()

    def test_send_card_oapi_success_records_transport_without_cli(self):
        audit = SimpleNamespace(
            set_send=mock.Mock(), flush=mock.Mock(return_value="/tmp/audit.json")
        )
        printed = []

        with mock.patch.object(
            send_feishu_card,
            "_send_card_via_oapi",
            return_value=(True, "om_oapi"),
        ), mock.patch.object(send_feishu_card, "_lark_run") as cli, mock.patch(
            "builtins.print", side_effect=lambda *args, **kwargs: printed.append(args[0])
        ):
            send_feishu_card.send_card(
                "oc_target",
                {"schema": "2.0", "body": {"elements": []}},
                "--chat-id",
                audit=audit,
            )

        cli.assert_not_called()
        audit.set_send.assert_called_once()
        self.assertEqual(
            audit.set_send.call_args.kwargs["transport"], "lark_oapi"
        )
        self.assertEqual(json.loads(printed[0])["transport"], "lark_oapi")

    def test_send_card_oapi_failure_falls_back_to_safe_cli(self):
        user_id = "ou_bad'; touch /tmp/injected; '"
        cli_response = SimpleNamespace(
            stdout=json.dumps(
                {"ok": True, "data": {"message_id": "om_cli"}}
            ),
            stderr="",
        )

        with mock.patch.object(
            send_feishu_card,
            "_send_card_via_oapi",
            return_value=(False, "unavailable"),
        ), mock.patch.object(
            send_feishu_card, "_lark_run", return_value=cli_response
        ) as cli, mock.patch.object(send_feishu_card.sys, "stderr"):
            send_feishu_card.send_card(
                None,
                {"schema": "2.0", "body": {"elements": []}},
                "--user-id",
                quiet_success=True,
                target_type="user",
                user_id=user_id,
            )

        argv = command_argv(cli.call_args.args[0])
        self.assertEqual(argv[argv.index("--user-id") + 1], user_id)

    def test_send_card_cli_transport_failure_is_mapped_and_audited(self):
        audit = SimpleNamespace(
            set_send=mock.Mock(), flush=mock.Mock(return_value="/tmp/audit.json")
        )
        with mock.patch.object(
            send_feishu_card,
            "_send_card_via_oapi",
            return_value=(False, "sdk unavailable"),
        ), mock.patch.object(
            send_feishu_card,
            "_lark_run",
            side_effect=FileNotFoundError("do not expose command payload"),
        ):
            with self.assertRaises(send_feishu_card.TransportError) as raised:
                send_feishu_card.send_card(
                    "oc_target",
                    {"schema": "2.0", "body": {"elements": []}},
                    "--chat-id",
                    audit=audit,
                )

        self.assertEqual(raised.exception.output["status"], "error")
        self.assertEqual(raised.exception.output["detail"], "lark-cli is unavailable")
        self.assertEqual(
            audit.set_send.call_args.kwargs["transport_failure_reason"],
            "lark_cli_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
