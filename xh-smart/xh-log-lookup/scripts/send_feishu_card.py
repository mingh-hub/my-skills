#!/usr/bin/env python3
"""
飞书互动卡片发送工具 - xh-log-lookup 专用

用法:
  # 手动指定 chat_id（旧模式，向后兼容）
  python3 send_feishu_card.py \
    --chat "oc_xxx" \
    --title "日志查询结果" \
    --color blue \
    --data '{"analysis": "...", "log_count": 20}'

  # 来源反查兜底：用问题文本搜索群聊 @Bot 或私聊 p2p 消息，自动获取 chat_id
  python3 send_feishu_card.py \
    --resolve-chat --source-query "客户手机号13173889286为什么还款失败" \
    --at-sender \
    --title "日志查询结果" \
    --color blue \
    --data '{"analysis": "...", "log_count": 20}'

  # WorkBuddy 直问：反查不到飞书来源时，发到 home channel 私聊目标
  WORKBUDDY_HOME_CHANNEL_CHAT_ID=oc_xxx

标题格式: [emoji] 场景简述 · 时间范围
颜色: red(ERROR/阻断) / yellow(WARN/拦截) / green(全部正常) / blue(常规)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# Bot identity 常量（全局唯一，跨所有群不变）
BOT_OPEN_ID = "ou_ae0341a3578d833a22b5f2927b103988"
CURRENT_CHAT_ENV_KEYS = ("FEISHU_CURRENT_CHAT_ID", "AGENT_CURRENT_CHAT_ID")
CURRENT_CHAT_TYPE_ENV_KEYS = ("FEISHU_CURRENT_CHAT_TYPE", "AGENT_CURRENT_CHAT_TYPE")
CURRENT_SENDER_ENV_KEYS = (
    "FEISHU_CURRENT_SENDER_OPEN_ID",
    "AGENT_CURRENT_SENDER_OPEN_ID",
    "FEISHU_SENDER_OPEN_ID",
)
EXTRA_CHAT_ENV_KEYS = ("WORKBUDDY_CURRENT_CHAT_ID", "CHAT_ID", "CURRENT_CHAT_ID", "FEISHU_CHAT_ID")
DEFAULT_PRIVATE_CHAT_ENV_KEYS = (
    "WORKBUDDY_HOME_CHANNEL_CHAT_ID",
    "FEISHU_DEFAULT_PRIVATE_CHAT_ID",
    "AGENT_DEFAULT_PRIVATE_CHAT_ID",
)

LEVEL_ICON = {"INFO": "\U0001f7e2", "WARN": "\U0001f7e1", "WARNING": "\U0001f7e1", "ERROR": "\U0001f534"}
COLOR_MAP = {"red": "red", "yellow": "yellow", "green": "green", "blue": "blue"}
CARD_DATA_SCHEMA = {
    "summary_fields": "list[{label, value}]",
    "call_chain": "list[object], recommended keys: level/time/service/content; aliases are rendered automatically",
    "log_count": "int >= 0",
    "table_data": "list[{headers: list, rows: list[list]}]",
    "analysis": "string",
}
CARD_DATA_ALLOWED_KEYS = set(CARD_DATA_SCHEMA)
CALL_CHAIN_ALIASES = {
    "level": ("level", "Level", "LEVEL"),
    "time": ("time", "timestamp", "datetime", "log_time"),
    "service": ("service", "serviceName", "service_name", "app"),
    "content": ("content", "message", "msg", "log"),
}

MD_TABLE_RE = re.compile(
    r'(?:^|\n)'
    r'(\|[^\n]+\|)\n'
    r'(\|[-:\| ]+\|)\n'
    r'((?:\|[^\n]+\|\n?)+)',
    re.MULTILINE
)


def _lark_env():
    """返回 lark-cli 所需的干净环境"""
    env = os.environ.copy()
    env["LARK_CLI_NO_PROXY"] = "1"
    return env


def _lark_run(cmd_str):
    """通过 shell 执行 lark-cli 命令（绕过 Python subprocess sandbox 限制）"""
    return subprocess.run(cmd_str, shell=True, capture_output=True, text=True,
                          timeout=15, env=_lark_env())


def _first_env(keys):
    for key in keys:
        value = os.environ.get(key)
        if value:
            return key, value
    return "", ""


def _schema_error(message, unknown_keys=None, field_errors=None):
    return {
        "status": "error",
        "error": "invalid_data_schema",
        "unknown_keys": unknown_keys or [],
        "field_errors": field_errors or [],
        "message": message,
        "expected_schema": CARD_DATA_SCHEMA,
        "fallback": "plain_text",
    }


def _has_renderable_card_content(data):
    return bool(
        data.get("summary_fields")
        or data.get("call_chain")
        or data.get("table_data")
        or data.get("analysis")
    )


def validate_card_data(data):
    if not isinstance(data, dict):
        return _schema_error("--data must be a JSON object")

    unknown_keys = sorted(set(data) - CARD_DATA_ALLOWED_KEYS)
    if unknown_keys:
        return _schema_error(
            "unsupported --data keys; use only the documented card schema",
            unknown_keys=unknown_keys,
        )

    field_errors = []

    summary_fields = data.get("summary_fields", [])
    if not isinstance(summary_fields, list):
        field_errors.append("summary_fields must be a list")
    else:
        for index, item in enumerate(summary_fields):
            if not isinstance(item, dict):
                field_errors.append(f"summary_fields[{index}] must be an object")
                continue
            missing = [key for key in ("label", "value") if key not in item]
            if missing:
                field_errors.append(
                    f"summary_fields[{index}] missing keys: {', '.join(missing)}"
                )

    call_chain = data.get("call_chain", [])
    if not isinstance(call_chain, list):
        field_errors.append("call_chain must be a list")
    else:
        for index, item in enumerate(call_chain):
            if not isinstance(item, dict):
                field_errors.append(f"call_chain[{index}] must be an object")
            elif not item:
                field_errors.append(f"call_chain[{index}] must not be empty")

    log_count = data.get("log_count", len(call_chain) if isinstance(call_chain, list) else 0)
    if not isinstance(log_count, int) or isinstance(log_count, bool):
        field_errors.append("log_count must be an integer")
    elif log_count < 0:
        field_errors.append("log_count must be >= 0")

    table_data = data.get("table_data", [])
    if not isinstance(table_data, list):
        field_errors.append("table_data must be a list")
    else:
        for index, table in enumerate(table_data):
            if not isinstance(table, dict):
                field_errors.append(f"table_data[{index}] must be an object")
                continue
            headers = table.get("headers")
            rows = table.get("rows")
            if not isinstance(headers, list):
                field_errors.append(f"table_data[{index}].headers must be a list")
            if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
                field_errors.append(f"table_data[{index}].rows must be a list of lists")

    analysis = data.get("analysis", "")
    if not isinstance(analysis, str):
        field_errors.append("analysis must be a string")

    if field_errors:
        return _schema_error("invalid --data schema", field_errors=field_errors)

    if log_count > 0 and not _has_renderable_card_content(data):
        return _schema_error(
            "log_count > 0 requires at least one renderable field: "
            "summary_fields, call_chain, table_data, or analysis"
        )

    return None


def _stringify_card_value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _first_present_value(item, keys):
    for key in keys:
        if key in item:
            value = _stringify_card_value(item.get(key)).strip()
            if value:
                return key, value
    return "", ""


def _format_extra_fields(item, consumed_keys):
    parts = []
    for key, value in item.items():
        if key in consumed_keys:
            continue
        text = _stringify_card_value(value).strip()
        if not text:
            continue
        parts.append(f"{key}={text}")
    return " ".join(parts)


def _format_call_chain_item(item):
    consumed_keys = set()
    level_key, level = _first_present_value(item, CALL_CHAIN_ALIASES["level"])
    time_key, timestamp = _first_present_value(item, CALL_CHAIN_ALIASES["time"])
    service_key, service = _first_present_value(item, CALL_CHAIN_ALIASES["service"])
    content_key, content = _first_present_value(item, CALL_CHAIN_ALIASES["content"])
    for key in (level_key, time_key, service_key, content_key):
        if key:
            consumed_keys.add(key)

    icon = LEVEL_ICON.get(level.upper(), "\U0001f7e2") if level else "\U0001f7e2"
    extra = _format_extra_fields(item, consumed_keys)
    detail = " ".join(part for part in (content, extra) if part).strip()
    if not detail:
        detail = _format_extra_fields(item, set())

    line_parts = [icon]
    if timestamp:
        line_parts.append(f"`{timestamp}`")
    if service:
        line_parts.append(f"**{service}**")
    if detail:
        line_parts.append(detail)
    return " ".join(line_parts)


def _load_json_output(stdout, stderr, context):
    """尽量从 noisy stdout 中提取 JSON。"""
    raw = (stdout or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass
    sys.stderr.write(f"[{context}] parse failed: {(stderr or raw)[:500]}\n")
    return None


def _split_row(row):
    cells = row.strip().strip('|').split('|')
    return [c.strip() for c in cells]


def parse_markdown_tables(text):
    segments = []
    last_end = 0
    for m in MD_TABLE_RE.finditer(text):
        before = text[last_end:m.start()].strip()
        if before:
            segments.append(("text", before))
        headers = _split_row(m.group(1))
        rows = [_split_row(line) for line in m.group(3).strip().splitlines()]
        segments.append(("table", {"columns": headers, "rows": rows}))
        last_end = m.end()
    after = text[last_end:].strip()
    if after:
        segments.append(("text", after))
    return segments


def build_table_element(columns, rows):
    col_defs = [
        {"name": f"col_{i}", "display_name": h, "data_type": "markdown"}
        for i, h in enumerate(columns)
    ]
    row_datas = []
    for row in rows:
        entry = {}
        for i in range(len(columns)):
            entry[f"col_{i}"] = str(row[i]) if i < len(row) else ""
        row_datas.append(entry)
    return {
        "tag": "table",
        "columns": col_defs,
        "rows": row_datas
    }


def build_rich_elements(text):
    segments = parse_markdown_tables(text)
    if len(segments) == 1 and segments[0][0] == "text":
        return [{"tag": "div", "text": {"tag": "lark_md", "content": segments[0][1]}}]
    elements = []
    for seg_type, seg_data in segments:
        if seg_type == "text":
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": seg_data}})
        else:
            elements.append(build_table_element(seg_data["columns"], seg_data["rows"]))
    return elements


def load_env():
    for env_path in ("~/Desktop/feishu/.env", "~/.workbuddy/.env", "~/.hermes/.env",
                     "~/.lark/.env"):
        resolved = os.path.expanduser(env_path)
        if not os.path.exists(resolved):
            continue
        with open(resolved) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def parse_cls_raw_text(raw_text):
    """从 CLS 页面原始文本提取结构化数据，自动构建 call_chain"""
    count_match = re.search(r'日志条数\s+([\d,]+)', raw_text)
    total_count = int(count_match.group(1).replace(',', '')) if count_match else 0

    rows = []
    pattern = r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+).*?message:(.*?)(?=\n\t|\Z)'
    for m in re.finditer(pattern, raw_text, re.DOTALL):
        timestamp = m.group(1).strip()
        msg = m.group(2).strip()[:300]
        level = "ERROR" if "ERROR" in msg or "\u5f02\u5e38" in msg or "\u9519\u8bef" in msg else \
                "WARN" if "WARN" in msg or "\u62e6\u622a" in msg else "INFO"
        svc_match = re.search(r'serviceName[=:]\s*"?(\w+)"?', raw_text)
        service = svc_match.group(1) if svc_match else "unknown"
        rows.append({
            "time": timestamp.split()[-1] if ' ' in timestamp else timestamp,
            "service": service,
            "level": level,
            "content": msg
        })

    return {"call_chain": rows[:20], "log_count": total_count or len(rows)}


def _search_messages(query, start, chat_type, at_bot=False):
    parts = [
        "lark-cli im +messages-search",
        "--as user",
    ]
    escaped_query = query.replace("'", "'\\''")
    parts.append(f"--query '{escaped_query}'")
    parts.extend([
        f"--chat-type '{chat_type}'",
        "--sender-type user",
        f"--start '{start}'",
        "--page-limit 1",
        "--page-size 5",
    ])
    if at_bot:
        parts.append(f"--at-chatter-ids '{BOT_OPEN_ID}'")
    cmd = " ".join(parts)
    result = _lark_run(cmd)
    return _load_json_output(result.stdout, result.stderr, "resolve_chat.search")


def _extract_message_ids(search_payload):
    message_ids = search_payload.get("message_ids", [])
    if not message_ids and search_payload.get("messages"):
        message_ids = [
            item.get("message_id")
            for item in search_payload.get("messages", [])
            if item.get("message_id")
        ]
    return message_ids


def _fetch_message_detail(msg_id):
    cmd = f"lark-cli im +messages-mget --message-ids '{msg_id}' --as bot"
    detail_result = _lark_run(cmd)

    detail_data = _load_json_output(detail_result.stdout, detail_result.stderr, "resolve_chat.mget")
    if detail_data is None:
        return None, "mget parse failed"

    if not detail_data.get("ok"):
        return None, detail_data.get("error", "mget failed")

    msgs = detail_data.get("data", {}).get("messages", [])
    if not msgs:
        return None, "mget returned no messages"

    return msgs[0], ""


def _message_time_value(msg):
    """Return a comparable millisecond timestamp and the source field name."""
    for key in ("create_time", "update_time", "timestamp"):
        raw_value = msg.get(key)
        if raw_value is None or raw_value == "":
            continue
        try:
            value = int(str(raw_value))
        except (TypeError, ValueError):
            continue
        if value < 10_000_000_000:
            value *= 1000
        return value, key
    return None, ""


def _recent_start(minutes):
    tz = timezone(timedelta(hours=8))
    return (datetime.now(tz) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def resolve_chat(query, window_minutes=15):
    """在时间窗内用问题文本精确搜索群聊 @Bot 或私聊 p2p 消息。

    Returns:
        dict with chat_id, chat_type, sender_open_id, sender_name,
             matched_count, matched_msg_id
        或 {} 表示未找到
    """
    query = (query or "").strip()
    if not query:
        print(json.dumps({"status": "error", "detail": "missing query"},
                         ensure_ascii=False), file=sys.stderr)
        return {}

    start = _recent_start(window_minutes)
    searches = [
        ("group_at_bot", _search_messages(query=query, start=start, chat_type="group", at_bot=True)),
        ("p2p", _search_messages(query=query, start=start, chat_type="p2p", at_bot=False)),
    ]
    candidates = []
    seen_ids = set()

    for source, search_data in searches:
        if search_data is None:
            print(json.dumps({"status": "error", "detail": f"{source} search parse failed"},
                             ensure_ascii=False), file=sys.stderr)
            return {}

        if not search_data.get("ok"):
            error_detail = search_data.get("error", f"{source} search failed")
            sys.stderr.write(f"[resolve_chat] {source} search error: {json.dumps(error_detail, ensure_ascii=False)[:500]}\n")
            print(json.dumps({"status": "error", "detail": error_detail},
                             ensure_ascii=False), file=sys.stderr)
            return {}

        search_payload = search_data.get("data", {})
        message_ids = _extract_message_ids(search_payload)
        source_count = max(len(message_ids), int(search_payload.get("total") or 0))
        if source_count <= 0:
            continue
        if not message_ids:
            print(json.dumps({"status": "error", "detail": f"{source} search returned count without message_ids"},
                             ensure_ascii=False), file=sys.stderr)
            return {}
        for msg_id in message_ids:
            if msg_id not in seen_ids:
                seen_ids.add(msg_id)
                candidates.append({
                    "msg_id": msg_id,
                    "source": source,
                    "search_order": len(candidates),
                })

    if not candidates:
        return {
            "unresolved": True,
            "matched_count": 0,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
        }
    matched_count = len(candidates)

    detailed_candidates = []
    detail_errors = []
    for candidate in candidates:
        msg, error_detail = _fetch_message_detail(candidate["msg_id"])
        if msg is None:
            detail_errors.append({
                "msg_id": candidate["msg_id"],
                "source": candidate["source"],
                "error": error_detail,
            })
            continue

        time_value, time_field = _message_time_value(msg)
        candidate.update({
            "msg": msg,
            "time_value": time_value,
            "time_field": time_field,
        })
        detailed_candidates.append(candidate)

    if not detailed_candidates:
        sys.stderr.write(f"[resolve_chat] mget error: {json.dumps(detail_errors[:3], ensure_ascii=False)[:500]}\n")
        return {
            "unresolved": True,
            "error": "detail_fetch_failed",
            "matched_count": matched_count,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
            "detail_errors": detail_errors[:3],
        }

    timed_candidates = [c for c in detailed_candidates if c["time_value"] is not None]
    if timed_candidates:
        selected = max(timed_candidates, key=lambda c: (c["time_value"], c["search_order"]))
    else:
        selected = detailed_candidates[0]

    msg = selected["msg"]
    source = selected["source"]
    expected_chat_type = "group" if source == "group_at_bot" else "p2p"
    search_strategy = f"latest_query_{source}_{window_minutes}m"

    sender = msg.get("sender", {})
    chat_type = msg.get("chat_type") or msg.get("chat_type_v2") or ""
    if not chat_type:
        chat_type = expected_chat_type
    elif chat_type not in ("group", "p2p"):
        chat_type = expected_chat_type

    return {
        "chat_id": msg.get("chat_id", ""),
        "chat_type": chat_type,
        "resolved_chat_type": chat_type,
        "sender_open_id": sender.get("id", ""),
        "sender_name": sender.get("id", ""),
        "matched_msg_id": selected["msg_id"],
        "matched_count": matched_count,
        "search_strategy": search_strategy,
        "selected_time_field": selected.get("time_field", ""),
        "selected_time_value": selected.get("time_value"),
        "detail_errors": detail_errors,
    }


def _source_resolution_meta(resolved, fallback, env_key=""):
    resolved = resolved or {}
    meta = {
        "status": "source_unresolved",
        "error": resolved.get("error", "no_match"),
        "search_strategy": resolved.get("search_strategy"),
        "matched_count": resolved.get("matched_count", 0),
        "resolved_chat_type": resolved.get("resolved_chat_type"),
        "expected_chat_type": resolved.get("expected_chat_type"),
        "detail_errors": resolved.get("detail_errors", []),
        "fallback": fallback,
    }
    if env_key:
        meta["env_key"] = env_key
    return meta


def resolve_send_target(
    args,
    env_chat_id,
    chat_key,
    chat_type,
    chat_type_key,
    sender_open_id,
    sender_key,
    default_private_key,
    default_private_chat_id,
    resolver=resolve_chat,
):
    sender_info = {}
    send_meta = {}

    if args.chat:
        return args.chat, "--chat", sender_info, send_meta, None

    if args.resolve_chat:
        source_query = (args.source_query or "").strip()
        if not source_query:
            return None, "", sender_info, send_meta, {
                "status": "error",
                "error": "missing_source_query",
                "message": (
                    "--resolve-chat 必须传 --source-query 用户原始问题，"
                    "禁止用摘要、分析标题或关键切片反查来源。"
                ),
                "fallback": "plain_text",
            }

        send_meta.update({
            "source_query_provided": True,
            "source_query_length": len(source_query),
        })

        resolved = resolver(source_query, args.resolve_window_minutes)
        if resolved and not resolved.get("unresolved") and resolved.get("chat_id"):
            chat_id = resolved["chat_id"]
            chat_source = resolved.get("search_strategy") or "--resolve-chat"
            sender_info = resolved
            send_meta.update({
                "search_strategy": resolved.get("search_strategy"),
                "matched_msg_id": resolved.get("matched_msg_id"),
                "matched_count": resolved.get("matched_count", 0),
                "resolved_chat_type": resolved.get("resolved_chat_type"),
                "selected_time_field": resolved.get("selected_time_field"),
                "selected_time_value": resolved.get("selected_time_value"),
            })
            if env_chat_id and env_chat_id != chat_id:
                send_meta["env_chat_conflict"] = {
                    "env_key": chat_key,
                    "env_chat_id": env_chat_id,
                    "resolved_chat_id": chat_id,
                }
            return chat_id, chat_source, sender_info, send_meta, None

        if resolved and not resolved.get("unresolved"):
            resolved = {
                **resolved,
                "unresolved": True,
                "error": "missing_resolved_chat_id",
            }

        if default_private_chat_id:
            send_meta["source_resolution"] = _source_resolution_meta(
                resolved,
                "default_private_chat",
                default_private_key,
            )
            return default_private_chat_id, default_private_key, sender_info, send_meta, None

        if env_chat_id:
            send_meta["source_resolution"] = _source_resolution_meta(
                resolved,
                "current_env_chat",
                chat_key,
            )
            return env_chat_id, chat_key, sender_info, send_meta, None

        source_meta = _source_resolution_meta(resolved, "plain_text")
        return None, "", sender_info, send_meta, {
            "status": "unresolved",
            "error": "missing_private_target",
            "source_error": source_meta.get("error", "no_match"),
            "warning": (
                "未搜索到可用的群聊 @Bot 或私聊 p2p 来源消息，且未配置 "
                "WORKBUDDY_HOME_CHANNEL_CHAT_ID，无法确定发送目标"
            ),
            "search_strategy": source_meta.get("search_strategy"),
            "matched_count": source_meta.get("matched_count", 0),
            "resolved_chat_type": source_meta.get("resolved_chat_type"),
            "expected_chat_type": source_meta.get("expected_chat_type"),
            "detail_errors": source_meta.get("detail_errors", []),
            "fallback": "plain_text",
        }

    if default_private_chat_id:
        return default_private_chat_id, default_private_key, sender_info, send_meta, None

    if env_chat_id:
        if sender_open_id:
            sender_info = {
                "sender_open_id": sender_open_id,
                "sender_name": sender_open_id,
                "chat_type": chat_type if chat_type in ("group", "p2p") else "group",
                "chat_source": chat_key,
                "sender_source": sender_key,
                "chat_type_source": chat_type_key,
            }
        return env_chat_id, chat_key, sender_info, send_meta, None

    return None, "", sender_info, send_meta, {
        "status": "error",
        "error": "missing_chat",
        "message": (
            "缺少发送目标：请传 --chat，或配置 WORKBUDDY_HOME_CHANNEL_CHAT_ID，"
            "或由 WorkBuddy 注入 FEISHU_CURRENT_CHAT_ID / AGENT_CURRENT_CHAT_ID，"
            "或显式使用 --resolve-chat --source-query。"
        ),
        "fallback": "plain_text",
    }


def build_card(title, color, cls_url, cls_url_expanded, data,
               sender_open_id="", sender_name="", chat_type="group"):
    elements = []

    if sender_open_id and chat_type == "group":
        display_name = sender_name if sender_name else sender_open_id
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f'<at user_id="{sender_open_id}">{display_name}</at>\n'}
        })

    summary_fields = data.get("summary_fields", [])
    if summary_fields:
        lines = [f"**{item['label']}**: {item['value']}" for item in summary_fields]
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(lines)}
        })
        elements.append({"tag": "hr"})

    call_chain = data.get("call_chain", [])
    log_count = data.get("log_count", len(call_chain))

    if call_chain:
        display_items = call_chain[:10] if log_count > 20 else call_chain
        chain_lines = []
        for item in display_items:
            chain_lines.append(_format_call_chain_item(item))
        if log_count > 20:
            chain_lines.append(f"\n... \u5171 **{log_count}** \u6761\u65e5\u5fd7\uff0c\u4ec5\u5c55\u793a\u6700\u8fd1 10 \u6761")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(chain_lines)}})
    elif log_count == 0 and not summary_fields:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**\u65e0\u5339\u914d\u65e5\u5fd7**\n\n\u53ef\u80fd\u539f\u56e0\uff1a\u67e5\u8be2\u65f6\u95f4\u8303\u56f4\u4e0d\u5bf9\u3001serviceName \u4e0d\u5339\u914d\u3001\u6216\u8be5\u8bf7\u6c42\u672a\u4ea7\u751f\u65e5\u5fd7\u3002"
            }
        })

    table_data = data.get("table_data", [])
    for td in table_data:
        headers = td.get("headers", [])
        rows = td.get("rows", [])
        if headers and rows:
            elements.append(build_table_element(headers, rows))

    analysis = data.get("analysis", "")
    if analysis:
        elements.append({"tag": "hr"})
        rich = build_rich_elements(f"**\U0001f4cb \u5206\u6790\u7ed3\u8bba:**\n{analysis}")
        elements.extend(rich)

    links = []
    if cls_url:
        links.append(f"[\U0001f517 \u8df3\u8f6c\u94fe\u63a5]({cls_url})")
    if cls_url_expanded:
        links.append(f"[\u23f1 \u6269\u5927\u67e5\u8be2\u8303\u56f4]({cls_url_expanded})")
    if links:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": " \u00b7 ".join(links)}
        })

    note_text = f"\U0001f550 \u5171\u67e5\u8be2\u5230 {log_count} \u6761\u65e5\u5fd7 | {time.strftime('%H:%M')}"
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"_{note_text}_"}
    })

    card = {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": COLOR_MAP.get(color, "blue")
        },
        "body": {
            "elements": elements
        }
    }
    return card


def send_card(chat_id, card, chat_source, meta=None, quiet_success=False):
    """通过 lark-cli bot 身份发送飞书卡片"""
    card_json = json.dumps(card, ensure_ascii=False)
    meta = meta or {}

    # Feishu interactive card content has a practical limit around 30KB
    # If too large, truncate progressively
    MAX_CARD_SIZE = 28000
    original_size = len(card_json)
    if original_size > MAX_CARD_SIZE:
        # Try removing trailing elements first (links, notes are least critical)
        body = card.get("body", {})
        elements = body.get("elements", [])
        while len(json.dumps(card, ensure_ascii=False)) > MAX_CARD_SIZE and elements:
            elements.pop()
        card_json = json.dumps(card, ensure_ascii=False)
        # If still too large, truncate raw JSON
        if len(card_json) > MAX_CARD_SIZE:
            card_json = card_json[:MAX_CARD_SIZE - 30] + '...\n\n_内容过长已截断_"}}'
        sys.stderr.write(f"[send_card] 卡片已截断: {original_size} -> {len(card_json)} bytes\n")

    # Use single-quote wrapping for shell safety. Single quotes protect all
    # special characters except single quotes themselves.
    # This avoids the issues with $(cat file) where large content can exceed
    # ARG_MAX or double quotes in JSON break shell parsing.
    escaped = card_json.replace("'", "'\\''")
    cmd = f"lark-cli im +messages-send --chat-id '{chat_id}' --as bot --msg-type interactive --content '{escaped}'"
    result = _lark_run(cmd)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        stderr_detail = result.stderr or "send failed"
        sys.stderr.write(f"[send_card] 解析失败: {stderr_detail[:500]}\n")
        output = {"status": "error", "detail": stderr_detail[:200],
                  "card_size": len(card_json), "chat_id": chat_id,
                  "chat_source": chat_source}
        if meta:
            output["meta"] = meta
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    if data.get("ok"):
        msg_id = data.get("data", {}).get("message_id", "unknown")
        if quiet_success:
            return
        output = {"status": "sent", "message_id": msg_id,
                  "chat_id": chat_id, "chat_source": chat_source}
        if meta:
            output["meta"] = meta
        print(json.dumps(output, ensure_ascii=False))
    else:
        sys.stderr.write(f"[send_card] API 错误: {json.dumps(data, ensure_ascii=False)[:500]}\n")
        output = {"status": "error", "detail": data,
                  "card_size": len(card_json), "chat_id": chat_id,
                  "chat_source": chat_source}
        if meta:
            output["meta"] = meta
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="发送飞书互动卡片")
    parser.add_argument("--chat", default=None, help="飞书会话 chat_id（手动模式，优先级最高）")
    parser.add_argument("--resolve-chat", action="store_true",
                        help="兜底：自动用 --source-query 搜索群聊 @Bot 或私聊 p2p 消息获取 chat_id")
    parser.add_argument("--source-query", default="",
                        help="用户原始问题，仅用于 --resolve-chat 来源反查；禁止传摘要或分析标题")
    parser.add_argument("--resolve-window-minutes", type=int, default=15,
                        help="--resolve-chat 精确搜索最近 N 分钟内的群聊 @Bot 或私聊 p2p 消息")
    parser.add_argument("--at-sender", action="store_true",
                        help="群聊卡片中 @提问者")
    parser.add_argument("--title", required=True,
                        help="卡片标题 (格式: [emoji] 场景简述 \u00b7 时间范围)")
    parser.add_argument("--color", default="blue",
                        choices=["red", "yellow", "green", "blue"],
                        help="red=ERROR/阻断, yellow=WARN/拦截, green=全部正常, blue=常规")
    parser.add_argument("--cls-url", default=None,
                        help="CLS 查询 URL (\U0001f517 \u8df3\u8f6c\u94fe\u63a5\u6309\u94ae)")
    parser.add_argument("--cls-url-expanded", default=None,
                        help="CLS 扩大时间范围 URL (\u23f1 扩大查询范围按钮)")
    parser.add_argument("--raw-text", default=None,
                        help="CLS 原始文本，自动解析为 call_chain（替代手动构建 --data 中的 call_chain）")
    parser.add_argument("--data", required=True,
                        help="JSON: {summary_fields, call_chain, analysis, log_count}")
    parser.add_argument("--quiet-success", action="store_true",
                        help="发送成功时不向 stdout 输出 status JSON，用于避免宿主应用重复回复")

    args = parser.parse_args()

    load_env()

    sender_info = {}
    send_meta = {}

    chat_id = None
    chat_source = ""
    chat_type_key, chat_type = _first_env(CURRENT_CHAT_TYPE_ENV_KEYS)
    sender_key, sender_open_id = _first_env(CURRENT_SENDER_ENV_KEYS)
    chat_key, env_chat_id = _first_env(CURRENT_CHAT_ENV_KEYS)
    if not env_chat_id:
        chat_key, env_chat_id = _first_env(EXTRA_CHAT_ENV_KEYS)
    default_private_key, default_private_chat_id = _first_env(DEFAULT_PRIVATE_CHAT_ENV_KEYS)

    chat_id, chat_source, sender_info, send_meta, target_error = resolve_send_target(
        args,
        env_chat_id,
        chat_key,
        chat_type,
        chat_type_key,
        sender_open_id,
        sender_key,
        default_private_key,
        default_private_chat_id,
    )
    if target_error:
        stream = sys.stderr if target_error.get("status") == "error" else sys.stdout
        print(json.dumps(target_error, ensure_ascii=False), file=stream)
        sys.exit(1 if target_error.get("status") == "error" else 2)

    data = json.loads(args.data)

    if args.raw_text and "call_chain" not in data:
        parsed = parse_cls_raw_text(args.raw_text)
        data.setdefault("call_chain", parsed["call_chain"])
        data.setdefault("log_count", parsed["log_count"])

    schema_error = validate_card_data(data)
    if schema_error:
        print(json.dumps(schema_error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    # 群聊自动 @：当 --resolve-chat 解析到 group 且有 sender_info 时自动生效
    should_at = args.at_sender or (
        sender_info and sender_info.get("chat_type") == "group" and sender_info.get("sender_open_id")
    )
    if should_at and sender_info:
        card = build_card(args.title, args.color, args.cls_url, args.cls_url_expanded,
                          data,
                          sender_open_id=sender_info.get("sender_open_id", ""),
                          sender_name=sender_info.get("sender_name", ""),
                          chat_type=sender_info.get("chat_type", "group"))
    else:
        card = build_card(args.title, args.color, args.cls_url, args.cls_url_expanded, data)

    send_card(chat_id, card, chat_source, meta=send_meta, quiet_success=args.quiet_success)


if __name__ == "__main__":
    main()
