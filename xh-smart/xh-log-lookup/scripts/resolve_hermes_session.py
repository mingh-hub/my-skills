#!/usr/bin/env python3
"""Resolve the Hermes Feishu session target bound to this tool process.

Exit code 0 means a target was found. Exit code 2 means the caller should
fall back to send_feishu_card.py --resolve-chat.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import feishu_transport


HERMES_STATE_DB = os.path.expanduser("~/.hermes/state.db")
LARK_CLI_CANDIDATES = feishu_transport.LARK_CLI_CANDIDATE_PATHS
WORKBUDDY_NODE_BIN_DIR = feishu_transport.WORKBUDDY_NODE_BIN_DIR
ID_PREFIXES = ("ou_", "om_", "on_")


def _find_lark_cli():
    original = feishu_transport.LARK_CLI_CANDIDATE_PATHS
    feishu_transport.LARK_CLI_CANDIDATE_PATHS = LARK_CLI_CANDIDATES
    try:
        return feishu_transport.resolve_lark_cli()
    except FileNotFoundError:
        return None
    finally:
        feishu_transport.LARK_CLI_CANDIDATE_PATHS = original


def _row_to_result(row):
    session_key, chat_id, chat_type, thread_id, user_id, display_name = row
    result = {
        "chat_id": chat_id,
        "chat_type": chat_type or "dm",
        "session_key": session_key,
        "thread_id": thread_id,
        "user_id": user_id,
        "display_name": display_name,
    }
    if session_key:
        parts = [part for part in session_key.split(":") if part]
        tail = parts[-1] if parts else ""
        if tail.startswith(ID_PREFIXES):
            result["sender_open_id_raw"] = tail
            if chat_type != "group":
                result["chat_type"] = "group" if tail.startswith("om_") else chat_type
    return result


def _resolve_from_current_environment():
    platform = os.environ.get("HERMES_SESSION_PLATFORM", "").strip().lower()
    chat_id = os.environ.get("HERMES_SESSION_CHAT_ID", "").strip()
    if platform != "feishu" or not chat_id:
        return None
    return _row_to_result(
        (
            os.environ.get("HERMES_SESSION_KEY", "").strip(),
            chat_id,
            os.environ.get("HERMES_SESSION_CHAT_TYPE", "").strip() or "dm",
            os.environ.get("HERMES_SESSION_THREAD_ID", "").strip() or None,
            os.environ.get("HERMES_SESSION_USER_ID", "").strip() or None,
            os.environ.get("HERMES_SESSION_USER_NAME", "").strip() or None,
        )
    )


def resolve():
    """Resolve only the Hermes session bound to the current tool process."""
    session_id = os.environ.get("HERMES_SESSION_ID", "").strip()
    session_key = os.environ.get("HERMES_SESSION_KEY", "").strip()
    if os.path.isfile(HERMES_STATE_DB) and (session_id or session_key):
        conditions = []
        params = []
        if session_id:
            conditions.append("id = ?")
            params.append(session_id)
        if session_key:
            conditions.append("session_key = ?")
            params.append(session_key)
        try:
            db = sqlite3.connect(
                f"file:{HERMES_STATE_DB}?mode=ro",
                uri=True,
                timeout=5,
            )
        except sqlite3.Error:
            db = None
        if db is not None:
            try:
                row = db.execute(
                    "SELECT session_key, chat_id, chat_type, thread_id, user_id, display_name "
                    "FROM sessions WHERE source='feishu' "
                    "AND chat_id IS NOT NULL AND chat_id != '' AND ("
                    + " AND ".join(conditions)
                    + ") LIMIT 1",
                    params,
                ).fetchone()
            except sqlite3.Error:
                row = None
            finally:
                db.close()
            if row:
                return _row_to_result(row)
            if session_id and session_key:
                return None
    return _resolve_from_current_environment()


def _lark_run(args):
    lark_cli = _find_lark_cli()
    if not lark_cli:
        raise FileNotFoundError("lark-cli not found")
    command = [lark_cli, *list(args)]
    original_node_dir = feishu_transport.WORKBUDDY_NODE_BIN_DIR
    feishu_transport.WORKBUDDY_NODE_BIN_DIR = WORKBUDDY_NODE_BIN_DIR
    try:
        env = feishu_transport.lark_env(lark_cli)
    finally:
        feishu_transport.WORKBUDDY_NODE_BIN_DIR = original_node_dir
    return subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def to_open_id(uid, uid_type="user_id"):
    """Convert through the shared Feishu transport without loading the SDK."""
    return feishu_transport.to_open_id(
        uid,
        uid_type,
        client_factory=lambda: None,
        runner=_lark_run,
    )


def main():
    parser = argparse.ArgumentParser(description="解析 Hermes 当前 feishu 会话目标")
    parser.add_argument(
        "--resolve-open-id",
        action="store_true",
        help="把 user_id 转成 ou_ open_id 一起输出（私聊直发用）",
    )
    parser.add_argument(
        "--open-id-type",
        default="user_id",
        choices=["user_id", "union_id"],
        help="user_id 的类型，转换 open_id 时使用（默认 user_id）",
    )
    args = parser.parse_args()

    result = resolve()
    if not result:
        print(
            json.dumps(
                {
                    "status": "unresolved",
                    "error": "no_active_feishu_session",
                    "hint": "非 Hermes 环境或 state.db 无 feishu 会话，请走 --resolve-chat 反查",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(2)

    if args.resolve_open_id:
        result["open_id"] = to_open_id(result.get("user_id"), args.open_id_type)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
