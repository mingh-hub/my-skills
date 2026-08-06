#!/usr/bin/env python3
"""CLI facade for Feishu card rendering, routing, and transport."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import feishu_card as _card
import feishu_routing as _routing
import feishu_transport as _transport


# Public and informal compatibility exports.
BOT_OPEN_ID = _routing.BOT_OPEN_ID
RouteAudit = _routing.RouteAudit
SendTarget = _routing.SendTarget
TransportResult = _transport.TransportResult
TransportError = _transport.TransportError

HERMES_ENV_PATH = _transport.HERMES_ENV_PATH
HERMES_PYTHON_CANDIDATES = _transport.HERMES_PYTHON_CANDIDATES
LARK_CLI_CANDIDATE_PATHS = _transport.LARK_CLI_CANDIDATE_PATHS
WORKBUDDY_NODE_BIN_DIR = _transport.WORKBUDDY_NODE_BIN_DIR
SEARCH_RETRY_DELAYS = _transport.SEARCH_RETRY_DELAYS
ZERO_RESULT_RETRY_DELAYS = _transport.ZERO_RESULT_RETRY_DELAYS
AT_TOM_FALLBACK_PAGE_LIMIT = _routing.AT_TOM_FALLBACK_PAGE_LIMIT
AT_TOM_FALLBACK_PAGE_SIZE = _routing.AT_TOM_FALLBACK_PAGE_SIZE
AT_TOM_FALLBACK_SIMILARITY_THRESHOLD = (
    _routing.AT_TOM_FALLBACK_SIMILARITY_THRESHOLD
)
AT_TOM_FALLBACK_SIMILARITY_EPSILON = _routing.AT_TOM_FALLBACK_SIMILARITY_EPSILON

CURRENT_CHAT_ENV_KEYS = ("FEISHU_CURRENT_CHAT_ID", "AGENT_CURRENT_CHAT_ID")
CURRENT_CHAT_TYPE_ENV_KEYS = (
    "FEISHU_CURRENT_CHAT_TYPE",
    "AGENT_CURRENT_CHAT_TYPE",
)
CURRENT_SENDER_ENV_KEYS = (
    "FEISHU_CURRENT_SENDER_OPEN_ID",
    "AGENT_CURRENT_SENDER_OPEN_ID",
    "FEISHU_SENDER_OPEN_ID",
)
EXTRA_CHAT_ENV_KEYS = (
    "WORKBUDDY_CURRENT_CHAT_ID",
    "CHAT_ID",
    "CURRENT_CHAT_ID",
    "FEISHU_CHAT_ID",
)
DEFAULT_PRIVATE_CHAT_ENV_KEYS = (
    "WORKBUDDY_HOME_CHANNEL_CHAT_ID",
    "FEISHU_DEFAULT_PRIVATE_CHAT_ID",
    "AGENT_DEFAULT_PRIVATE_CHAT_ID",
)

CARD_DATA_SCHEMA = _card.CARD_DATA_SCHEMA
CARD_DATA_ALLOWED_KEYS = _card.CARD_DATA_ALLOWED_KEYS
CALL_CHAIN_ALIASES = _card.CALL_CHAIN_ALIASES
LEVEL_ICON = _card.LEVEL_ICON
COLOR_MAP = _card.COLOR_MAP
MAX_CARD_SIZE_BYTES = _card.MAX_CARD_SIZE_BYTES
CARD_TRUNCATION_NOTICE = _card.CARD_TRUNCATION_NOTICE

validate_card_data = _card.validate_card_data
parse_markdown_tables = _card.parse_markdown_tables
build_table_element = _card.build_table_element
build_rich_elements = _card.build_rich_elements
parse_cls_raw_text = _card.parse_cls_raw_text
build_card = _card.build_card
fit_card_payload = _card.fit_card_payload
_format_call_chain_item = _card._format_call_chain_item
_serialize_card = _card.serialize_card
_card_size_bytes = _card.card_size_bytes
_truncate_utf8 = _card._truncate_utf8

_LARK_OAPI_MODULE = _transport._LARK_OAPI_MODULE
_LARK_OAPI_IMPORT_FAILED = _transport._LARK_OAPI_IMPORT_FAILED
_LARK_OAPI_CLIENT = _transport._LARK_OAPI_CLIENT
_LARK_OAPI_CLIENT_FAILED = _transport._LARK_OAPI_CLIENT_FAILED


def _push_transport_state():
    for name in (
        "_LARK_OAPI_MODULE",
        "_LARK_OAPI_IMPORT_FAILED",
        "_LARK_OAPI_CLIENT",
        "_LARK_OAPI_CLIENT_FAILED",
    ):
        setattr(_transport, name, globals()[name])


def _pull_transport_state():
    global _LARK_OAPI_MODULE, _LARK_OAPI_IMPORT_FAILED
    global _LARK_OAPI_CLIENT, _LARK_OAPI_CLIENT_FAILED
    _LARK_OAPI_MODULE = _transport._LARK_OAPI_MODULE
    _LARK_OAPI_IMPORT_FAILED = _transport._LARK_OAPI_IMPORT_FAILED
    _LARK_OAPI_CLIENT = _transport._LARK_OAPI_CLIENT
    _LARK_OAPI_CLIENT_FAILED = _transport._LARK_OAPI_CLIENT_FAILED


def _import_lark_oapi():
    _push_transport_state()
    result = _transport.import_lark_oapi()
    _pull_transport_state()
    return result


def _load_env_credentials():
    _transport.HERMES_ENV_PATH = HERMES_ENV_PATH
    return _transport.load_env_credentials()


def _lark_oapi_client():
    _push_transport_state()
    result = _transport.lark_oapi_client(
        importer=_import_lark_oapi,
        credential_loader=_load_env_credentials,
    )
    _pull_transport_state()
    return result


def _maybe_relaunch_with_hermes_python():
    original = _transport.HERMES_PYTHON_CANDIDATES
    _transport.HERMES_PYTHON_CANDIDATES = HERMES_PYTHON_CANDIDATES
    try:
        return _transport.maybe_relaunch_with_hermes_python(
            importer=_import_lark_oapi
        )
    finally:
        _transport.HERMES_PYTHON_CANDIDATES = original


def _resolve_lark_cli():
    _transport.LARK_CLI_CANDIDATE_PATHS = LARK_CLI_CANDIDATE_PATHS
    return _transport.resolve_lark_cli()


def _lark_env(lark_cli=None):
    env = os.environ.copy()
    env["LARK_CLI_NO_PROXY"] = "1"
    env["PATH"] = os.pathsep.join(
        part
        for part in (
            WORKBUDDY_NODE_BIN_DIR,
            os.path.dirname(lark_cli) if lark_cli else "",
            env.get("PATH", ""),
        )
        if part
    )
    return env


def _lark_run(args):
    lark_cli = _resolve_lark_cli()
    command = shlex.split(args) if isinstance(args, str) else list(args)
    if command and command[0] == "lark-cli":
        command[0] = lark_cli
    elif not command or os.path.basename(command[0]) != "lark-cli":
        command.insert(0, lark_cli)
    return subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=_lark_env(lark_cli),
    )


def _oapi_get_user_request(uid, uid_type):
    return _transport.oapi_get_user_request(uid, uid_type)


def _oapi_get_message_request(message_id):
    return _transport.oapi_get_message_request(message_id)


def _to_open_id(uid, uid_type="user_id"):
    return _transport.to_open_id(
        uid,
        uid_type,
        client_factory=_lark_oapi_client,
        runner=_lark_run,
        request_builder=_oapi_get_user_request,
    )


def _search_messages(*args, **kwargs):
    kwargs.setdefault("runner", _lark_run)
    return _transport.search_messages(*args, **kwargs)


def _fetch_message_detail(message_id, audit=None, source=""):
    return _transport.fetch_message_detail(
        message_id,
        audit=audit,
        source=source,
        client_factory=_lark_oapi_client,
        runner=_lark_run,
        request_builder=_oapi_get_message_request,
    )


def _oapi_create_message_request(card, receive_id, receive_id_type):
    return _transport.oapi_create_message_request(card, receive_id, receive_id_type)


def _send_card_via_oapi(card, target_type, chat_id, user_id):
    return _transport.send_card_via_oapi(
        card,
        target_type,
        chat_id,
        user_id,
        client_factory=_lark_oapi_client,
        request_builder=_oapi_create_message_request,
    )


def send_card(
    chat_id,
    card,
    chat_source,
    meta=None,
    quiet_success=False,
    audit=None,
    target_type="chat",
    user_id=None,
):
    return _transport.send_card(
        chat_id,
        card,
        chat_source,
        meta=meta,
        quiet_success=quiet_success,
        audit=audit,
        target_type=target_type,
        user_id=user_id,
        oapi_sender=_send_card_via_oapi,
        runner=_lark_run,
    )


def resolve_chat(*args, **kwargs):
    kwargs.setdefault("searcher", _search_messages)
    kwargs.setdefault("detail_fetcher", _fetch_message_detail)
    return _routing.resolve_chat(*args, **kwargs)


def resolve_send_target(*args, **kwargs):
    kwargs.setdefault("resolver", resolve_chat)
    return _routing.resolve_send_target(*args, **kwargs)


def resolve_send_target_model(*args, **kwargs):
    kwargs.setdefault("resolver", resolve_chat)
    return _routing.resolve_send_target_model(*args, **kwargs)


def load_env():
    return _transport.load_env_files()


def _first_env(keys):
    for key in keys:
        value = os.environ.get(key)
        if value:
            return key, value
    return "", ""


def build_parser():
    parser = argparse.ArgumentParser(description="发送飞书互动卡片")
    parser.add_argument(
        "--chat-id",
        default=None,
        help="显式群/会话 chat_id (oc_xxx)，Hermes 直传，优先级高于 --resolve-chat",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="显式私聊 open_id (ou_xxx)，Hermes 直传私聊直发，优先级最高",
    )
    parser.add_argument(
        "--sender-open-id",
        default=None,
        help="群聊提问者 open_id (ou_xxx)，卡片 @ 用；非 ou_ 开头自动转换",
    )
    parser.add_argument(
        "--sender-id-type",
        default="user_id",
        choices=["user_id", "union_id", "open_id"],
        help="--sender-open-id 的类型，非 ou_ 开头时用于转换（默认 user_id）",
    )
    parser.add_argument(
        "--chat-type",
        default=None,
        choices=["p2p", "group"],
        help="显式会话类型（Hermes 直传时用，默认 user 模式=p2p，chat 模式=group）",
    )
    parser.add_argument("--chat", default=None, help="飞书会话 chat_id（手动模式，兼容旧调用）")
    parser.add_argument(
        "--resolve-chat",
        action="store_true",
        help="兜底：自动用 --source-query 搜索群聊 @Bot 或私聊 p2p 消息获取 chat_id",
    )
    parser.add_argument(
        "--source-query",
        default="",
        help="用户原始问题，仅用于 --resolve-chat 来源反查；禁止传摘要或分析标题",
    )
    parser.add_argument(
        "--resolve-window-minutes",
        type=int,
        default=15,
        help="--resolve-chat 精确搜索最近 N 分钟内的群聊 @Bot 或私聊 p2p 消息",
    )
    parser.add_argument("--at-sender", action="store_true", help="群聊卡片中 @提问者")
    parser.add_argument("--title", required=True, help="卡片标题")
    parser.add_argument(
        "--color",
        default="blue",
        choices=["red", "yellow", "green", "blue"],
        help="red=ERROR/阻断, yellow=WARN/拦截, green=全部正常, blue=常规",
    )
    parser.add_argument(
        "--content-mode",
        default="log",
        choices=["log", "business-logic", "combined"],
        help="卡片内容模式：日志、本地业务逻辑或源码+日志联合分析",
    )
    parser.add_argument("--cls-url", default=None, help="CLS 查询 URL (跳转链接按钮)")
    parser.add_argument(
        "--cls-url-expanded", default=None, help="CLS 扩大时间范围 URL (扩大查询范围按钮)"
    )
    parser.add_argument(
        "--raw-text",
        default=None,
        help="CLS 原始文本，自动解析为 call_chain（替代 --data 中的 call_chain）",
    )
    parser.add_argument(
        "--data",
        required=True,
        help="JSON: {summary_fields, call_chain, log_count, table_data, analysis}",
    )
    parser.add_argument(
        "--debug-log-dir",
        default="",
        help="可选：写入来源反查审计 JSON，不记录原始问题或凭据",
    )
    parser.add_argument(
        "--quiet-success",
        action="store_true",
        help="发送成功时不向 stdout 输出 status JSON，用于避免宿主应用重复回复",
    )
    parser.add_argument(
        "--allow-home-channel-fallback",
        action="store_true",
        help=(
            "来源反查失败时允许兜底发送到 WORKBUDDY_HOME_CHANNEL_CHAT_ID；"
            "默认关闭，仅供无来源上下文的批量/定时调用显式开启"
        ),
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    load_env()
    audit = RouteAudit(args.debug_log_dir)

    chat_type_key, chat_type = _first_env(CURRENT_CHAT_TYPE_ENV_KEYS)
    sender_key, sender_open_id = _first_env(CURRENT_SENDER_ENV_KEYS)
    chat_key, env_chat_id = _first_env(CURRENT_CHAT_ENV_KEYS)
    if not env_chat_id:
        chat_key, env_chat_id = _first_env(EXTRA_CHAT_ENV_KEYS)
    default_private_key, default_private_chat_id = _first_env(
        DEFAULT_PRIVATE_CHAT_ENV_KEYS
    )
    target = resolve_send_target_model(
        args,
        env_chat_id,
        chat_key,
        chat_type,
        chat_type_key,
        sender_open_id,
        sender_key,
        default_private_key,
        default_private_chat_id,
        allow_home_channel_fallback=args.allow_home_channel_fallback,
        audit=audit,
    )
    if target.error:
        audit.set_send(
            status="not_sent", error=target.error.get("error", "target_error")
        )
        path = audit.flush()
        if path:
            target.error["route_audit_path"] = path
        stream = sys.stderr if target.error.get("status") == "error" else sys.stdout
        print(json.dumps(target.error, ensure_ascii=False), file=stream)
        return 1 if target.error.get("status") == "error" else 2

    sender_info = target.sender_info
    if args.sender_open_id and sender_info.get("target_type") in ("user", "chat"):
        raw_sender = args.sender_open_id
        if not raw_sender.startswith("ou_"):
            raw_sender = _to_open_id(raw_sender, uid_type=args.sender_id_type) or ""
        sender_info["sender_open_id"] = raw_sender
        sender_info["sender_name"] = raw_sender

    try:
        data = json.loads(args.data)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "invalid_data_json",
                    "message": str(exc),
                    "fallback": "plain_text",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    if args.raw_text and "call_chain" not in data:
        parsed = parse_cls_raw_text(args.raw_text)
        data.setdefault("call_chain", parsed["call_chain"])
        data.setdefault("log_count", parsed["log_count"])
    schema_error = validate_card_data(data)
    if schema_error:
        print(json.dumps(schema_error, ensure_ascii=False), file=sys.stderr)
        return 1

    should_at = args.at_sender or (
        sender_info
        and sender_info.get("chat_type") == "group"
        and sender_info.get("sender_open_id")
    )
    card = build_card(
        args.title,
        args.color,
        args.cls_url,
        args.cls_url_expanded,
        data,
        sender_open_id=(sender_info.get("sender_open_id", "") if should_at else ""),
        sender_name=(sender_info.get("sender_name", "") if should_at else ""),
        chat_type=(sender_info.get("chat_type", "group") if should_at else "group"),
        content_mode=args.content_mode,
    )
    try:
        send_card(
            target.chat_id,
            card,
            target.chat_source,
            meta=target.meta,
            quiet_success=args.quiet_success,
            audit=audit,
            target_type=target.target_type,
            user_id=target.user_id,
        )
    except TransportError as exc:
        print(json.dumps(exc.output, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
