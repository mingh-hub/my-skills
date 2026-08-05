#!/usr/bin/env python3
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "resolve_hermes_session.py"
)


def load_module():
    if not SCRIPT_PATH.is_file():
        raise AssertionError("resolve_hermes_session.py has not been added")
    spec = importlib.util.spec_from_file_location("resolve_hermes_session", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResolveHermesSessionTest(unittest.TestCase):
    def _create_state_db(self, path):
        db = sqlite3.connect(path)
        db.execute(
            "CREATE TABLE sessions ("
            "id TEXT, session_key TEXT, chat_id TEXT, chat_type TEXT, "
            "thread_id TEXT, user_id TEXT, display_name TEXT, source TEXT, "
            "last_activity_at INTEGER)"
        )
        db.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "session-current",
                    "agent:main:feishu:dm:oc_current",
                    "oc_current",
                    "dm",
                    None,
                    "current-user",
                    "current",
                    "feishu",
                    100,
                ),
                (
                    "session-newer",
                    "agent:main:feishu:group:oc_newer:ou_other",
                    "oc_newer",
                    "group",
                    None,
                    "other-user",
                    "other",
                    "feishu",
                    200,
                ),
            ],
        )
        db.commit()
        db.close()

    def test_resolve_uses_current_session_id_instead_of_latest_session(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_db = Path(tmpdir) / "state.db"
            self._create_state_db(state_db)

            original_state_db = module.HERMES_STATE_DB
            try:
                module.HERMES_STATE_DB = str(state_db)
                with mock.patch.dict(
                    os.environ,
                    {
                        "HERMES_SESSION_ID": "session-current",
                        "HERMES_SESSION_PLATFORM": "feishu",
                    },
                    clear=True,
                ):
                    result = module.resolve()
            finally:
                module.HERMES_STATE_DB = original_state_db

        self.assertEqual(result["chat_id"], "oc_current")
        self.assertEqual(result["chat_type"], "dm")

    def test_resolve_refuses_to_guess_without_current_session_binding(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_db = Path(tmpdir) / "state.db"
            self._create_state_db(state_db)

            original_state_db = module.HERMES_STATE_DB
            try:
                module.HERMES_STATE_DB = str(state_db)
                with mock.patch.dict(os.environ, {}, clear=True):
                    result = module.resolve()
            finally:
                module.HERMES_STATE_DB = original_state_db

        self.assertIsNone(result)

    def test_resolve_rejects_mismatched_current_session_id_and_key(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_db = Path(tmpdir) / "state.db"
            self._create_state_db(state_db)

            original_state_db = module.HERMES_STATE_DB
            try:
                module.HERMES_STATE_DB = str(state_db)
                with mock.patch.dict(
                    os.environ,
                    {
                        "HERMES_SESSION_ID": "session-current",
                        "HERMES_SESSION_KEY": "agent:main:feishu:group:oc_newer:ou_other",
                        "HERMES_SESSION_PLATFORM": "feishu",
                        "HERMES_SESSION_CHAT_ID": "oc_bridge",
                        "HERMES_SESSION_CHAT_TYPE": "group",
                        "HERMES_SESSION_USER_ID": "ou_bridge",
                    },
                    clear=True,
                ):
                    result = module.resolve()
            finally:
                module.HERMES_STATE_DB = original_state_db

        self.assertIsNone(result)

    def test_resolve_uses_bridged_current_session_environment_without_db_row(self):
        module = load_module()
        original_state_db = module.HERMES_STATE_DB
        try:
            module.HERMES_STATE_DB = "/path/that/does/not/exist/state.db"
            with mock.patch.dict(
                os.environ,
                {
                    "HERMES_SESSION_PLATFORM": "feishu",
                    "HERMES_SESSION_KEY": "agent:main:feishu:group:oc_group:ou_sender",
                    "HERMES_SESSION_CHAT_ID": "oc_group",
                    "HERMES_SESSION_CHAT_TYPE": "group",
                    "HERMES_SESSION_USER_ID": "ou_sender",
                    "HERMES_SESSION_USER_NAME": "Sender",
                },
                clear=True,
            ):
                result = module.resolve()
        finally:
            module.HERMES_STATE_DB = original_state_db

        self.assertIsNotNone(result, "bridged Hermes session environment was ignored")
        self.assertEqual(result["chat_id"], "oc_group")
        self.assertEqual(result["sender_open_id_raw"], "ou_sender")

    def test_resolve_returns_none_without_state_database(self):
        module = load_module()
        original_state_db = module.HERMES_STATE_DB
        try:
            module.HERMES_STATE_DB = "/path/that/does/not/exist/state.db"
            result = module.resolve()
        finally:
            module.HERMES_STATE_DB = original_state_db

        self.assertIsNone(result)

    def test_to_open_id_supplies_workbuddy_node_path(self):
        module = load_module()
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                stdout='{"ok": true, "data": {"user": {"open_id": "ou_ok"}}}'
            )

        with mock.patch.object(
            module,
            "_find_lark_cli",
            return_value="/tmp/lark-bin/lark-cli",
        ), mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            result = module.to_open_id("minghai")

        self.assertEqual(result, "ou_ok")
        path_parts = captured["kwargs"]["env"]["PATH"].split(os.pathsep)
        self.assertEqual(path_parts[0], module.WORKBUDDY_NODE_BIN_DIR)
        self.assertEqual(path_parts[1], "/tmp/lark-bin")

    def test_to_open_id_passes_uid_as_single_subprocess_argument(self):
        module = load_module()
        captured = {}
        malicious_uid = "user'; touch /tmp/xh-log-lookup-injected; '"

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return SimpleNamespace(stdout='{"ok": false}')

        with mock.patch.object(
            module,
            "_find_lark_cli",
            return_value="/tmp/lark-bin/lark-cli",
        ), mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            module.to_open_id(malicious_uid)

        self.assertIsInstance(captured["cmd"], list)
        uid_index = captured["cmd"].index("--user-id") + 1
        self.assertEqual(captured["cmd"][uid_index], malicious_uid)
        self.assertFalse(captured["kwargs"].get("shell", False))


if __name__ == "__main__":
    unittest.main()
