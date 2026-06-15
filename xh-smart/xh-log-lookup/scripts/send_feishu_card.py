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
import difflib
import json
import os
import re
import shlex
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
LARK_CLI_ABSOLUTE = "/Users/user/.workbuddy/binaries/node/cli-connector-packages/bin/lark-cli"
LARK_CLI_BIN_DIR = os.path.dirname(LARK_CLI_ABSOLUTE)
WORKBUDDY_NODE_BIN_DIR = "/Users/user/.workbuddy/binaries/node/versions/22.22.2/bin"
EXTRA_CHAT_ENV_KEYS = ("WORKBUDDY_CURRENT_CHAT_ID", "CHAT_ID", "CURRENT_CHAT_ID", "FEISHU_CHAT_ID")
DEFAULT_PRIVATE_CHAT_ENV_KEYS = (
    "WORKBUDDY_HOME_CHANNEL_CHAT_ID",
    "FEISHU_DEFAULT_PRIVATE_CHAT_ID",
    "AGENT_DEFAULT_PRIVATE_CHAT_ID",
)
SEARCH_RETRY_DELAYS = (5, 10, 15)
ZERO_RESULT_RETRY_DELAYS = (3, 4, 4, 4)
AT_TOM_FALLBACK_PAGE_LIMIT = 5
AT_TOM_FALLBACK_PAGE_SIZE = 10
AT_TOM_FALLBACK_SIMILARITY_THRESHOLD = 0.72
AT_TOM_FALLBACK_SIMILARITY_EPSILON = 0.01

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
    path_parts = [
        WORKBUDDY_NODE_BIN_DIR,
        LARK_CLI_BIN_DIR,
        env.get("PATH", ""),
    ]
    env["PATH"] = ":".join(part for part in path_parts if part)
    return env


def _lark_run(cmd_str):
    """通过 shell 执行 lark-cli 命令（绕过 Python subprocess sandbox 限制）"""
    if not os.path.isfile(LARK_CLI_ABSOLUTE) or not os.access(LARK_CLI_ABSOLUTE, os.X_OK):
        raise FileNotFoundError(f"lark-cli not found or not executable: {LARK_CLI_ABSOLUTE}")
    cmd_str = cmd_str.replace("lark-cli ", f"{shlex.quote(LARK_CLI_ABSOLUTE)} ", 1)
    return subprocess.run(cmd_str, shell=True, capture_output=True, text=True,
                          timeout=15, env=_lark_env())


def _first_env(keys):
    for key in keys:
        value = os.environ.get(key)
        if value:
            return key, value
    return "", ""


def _now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _truncate(value, limit=500):
    text = "" if value is None else str(value)
    return text[:limit]


def _redact_audit_text(value, sensitive_text="", limit=500):
    text = "" if value is None else str(value)
    if sensitive_text:
        text = text.replace(sensitive_text, "<redacted_source_query>")
    return text[:limit]


class RouteAudit:
    def __init__(self, debug_log_dir=""):
        self.debug_log_dir = debug_log_dir or ""
        self.data = {
            "created_at": _now_iso(),
            "pid": os.getpid(),
            "source_query_length": 0,
            "resolve_window_minutes": None,
            "start_time": "",
            "searches": [],
            "mget": [],
            "selection": {},
            "fallback": {},
            "send": {},
        }

    def enabled(self):
        return bool(self.debug_log_dir)

    def set_context(self, source_query, resolve_window_minutes, start_time):
        self.data["source_query_length"] = len(source_query or "")
        self.data["resolve_window_minutes"] = resolve_window_minutes
        self.data["start_time"] = start_time or ""

    def add_search(self, entry):
        self.data["searches"].append(entry)

    def add_mget(self, entry):
        self.data["mget"].append(entry)

    def set_selection(self, **kwargs):
        self.data["selection"].update(kwargs)

    def set_fallback(self, **kwargs):
        self.data["fallback"].update(kwargs)

    def set_send(self, **kwargs):
        self.data["send"].update(kwargs)

    def flush(self):
        if not self.enabled():
            return ""
        try:
            os.makedirs(self.debug_log_dir, exist_ok=True)
            ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
            path = os.path.join(
                self.debug_log_dir,
                f"send_feishu_card_route_{ts}_{os.getpid()}.json",
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return path
        except Exception as exc:
            sys.stderr.write(f"[route_audit] flush failed: {_truncate(exc, 200)}\n")
            return ""


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


def _search_messages(query, start, audit=None, source="mixed",
                     retry_delays=SEARCH_RETRY_DELAYS,
                     zero_result_retry_delays=ZERO_RESULT_RETRY_DELAYS,
                     sleep_func=time.sleep, page_limit=1, page_size=5):
    parts = [
        "lark-cli im +messages-search",
        "--as user",
    ]
    escaped_query = query.replace("'", "'\\''")
    parts.append(f"--query '{escaped_query}'")
    parts.extend([
        f"--start '{start}'",
        f"--page-limit {page_limit}",
        f"--page-size {page_size}",
    ])
    cmd = " ".join(parts)
    attempts = []
    delays = tuple(retry_delays or ())
    zero_delays = tuple(zero_result_retry_delays or ())
    data = None
    result = None
    error_retry_index = 0
    zero_retry_index = 0

    while True:
        started = time.monotonic()
        attempt = {
            "attempt": len(attempts) + 1,
            "ok": False,
            "zero_result": False,
            "timeout": False,
            "returncode": None,
            "total": None,
            "message_ids_count": 0,
            "elapsed_ms": 0,
            "error_summary": "",
            "stderr_summary": "",
        }
        try:
            result = _lark_run(cmd)
            attempt["returncode"] = getattr(result, "returncode", 0)
            data = _load_json_output(result.stdout, result.stderr, "resolve_chat.search")
            attempt["ok"] = bool(isinstance(data, dict) and data.get("ok") and attempt["returncode"] == 0)
            if attempt["ok"]:
                payload = data.get("data", {}) if isinstance(data.get("data", {}), dict) else {}
                message_ids = _extract_message_ids(payload)
                messages = _extract_messages(payload)
                total = payload.get("total")
                try:
                    total_count = int(total) if total is not None else None
                except (TypeError, ValueError):
                    total_count = None
                attempt["total"] = total
                attempt["message_ids_count"] = len(message_ids)
                attempt["zero_result"] = not (
                    message_ids
                    or messages
                    or (total_count is not None and total_count > 0)
                )
            if isinstance(data, dict):
                attempt["error_summary"] = _redact_audit_text(data.get("error"), query, 500)
            else:
                attempt["error_summary"] = "parse_failed"
            attempt["stderr_summary"] = _redact_audit_text(getattr(result, "stderr", ""), query, 500)
        except subprocess.TimeoutExpired as exc:
            attempt["timeout"] = True
            attempt["error_summary"] = "timeout"
            attempt["stderr_summary"] = _redact_audit_text(getattr(exc, "stderr", ""), query, 500)
            data = None
        finally:
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)

        if attempt["ok"] and not attempt["zero_result"]:
            break
        if attempt["ok"] and attempt["zero_result"]:
            if zero_retry_index < len(zero_delays):
                sleep_func(zero_delays[zero_retry_index])
                zero_retry_index += 1
                continue
            break
        if error_retry_index < len(delays):
            sleep_func(delays[error_retry_index])
            error_retry_index += 1
            continue
        break

    if audit:
        payload = data.get("data", {}) if isinstance(data, dict) else {}
        message_ids = _extract_message_ids(payload) if isinstance(payload, dict) else []
        audit.add_search({
            "source": source,
            "query_length": len(query or ""),
            "chat_type_filter": "",
            "at_bot": False,
            "has_at_chatter_ids": False,
            "uses_sender_type": False,
            "uses_chat_type_filter": False,
            "page_limit": page_limit,
            "page_size": page_size,
            "start": start,
            "ok": data.get("ok") if isinstance(data, dict) else False,
            "total": payload.get("total") if isinstance(payload, dict) else None,
            "message_ids_count": len(message_ids),
            "message_ids_preview": message_ids[:5],
            "attempt_count": len(attempts),
            "attempts": attempts,
            "zero_result_retry_enabled": bool(zero_delays),
            "zero_result_retry_count": sum(1 for item in attempts[:-1] if item.get("zero_result")),
            "error_summary": (
                _redact_audit_text(data.get("error"), query, 500)
                if isinstance(data, dict) else "parse_failed"
            ),
            "stderr_summary": _redact_audit_text(getattr(result, "stderr", ""), query, 500),
        })
    return data


def _extract_message_ids(search_payload):
    message_ids = search_payload.get("message_ids", [])
    if not message_ids and search_payload.get("messages"):
        message_ids = [
            item.get("message_id")
            for item in search_payload.get("messages", [])
            if item.get("message_id")
        ]
    return message_ids


def _extract_messages(search_payload):
    messages = search_payload.get("messages", [])
    return messages if isinstance(messages, list) else []


def _message_needs_detail(msg):
    if not isinstance(msg, dict):
        return True
    if not msg.get("chat_id"):
        return True
    chat_type = msg.get("chat_type") or msg.get("chat_type_v2")
    if chat_type not in ("group", "p2p"):
        return True
    if not isinstance(msg.get("sender"), dict) or not msg.get("sender", {}).get("id"):
        return True
    if chat_type == "group" and "mentions" not in msg:
        return True
    return False


def _group_mentions_bot(msg):
    mentions = msg.get("mentions") if isinstance(msg, dict) else None
    if not isinstance(mentions, list):
        return False
    for mention in mentions:
        if not isinstance(mention, dict):
            continue
        if mention.get("id") == BOT_OPEN_ID:
            return True
        if str(mention.get("name", "")).strip().lower() == "tom":
            return True
    return False


def _candidate_from_message(msg, source, search_order):
    msg_id = msg.get("message_id", "") if isinstance(msg, dict) else ""
    return {
        "msg_id": msg_id,
        "msg": msg,
        "source": source,
        "search_order": search_order,
    }


def _candidates_from_search_payload(search_payload, source):
    messages = _extract_messages(search_payload)
    message_ids = _extract_message_ids(search_payload)
    candidates = []
    seen_ids = set()

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_id = msg.get("message_id") or f"inline:{len(candidates)}"
        if msg_id in seen_ids:
            continue
        seen_ids.add(msg_id)
        candidates.append(_candidate_from_message(msg, source, len(candidates)))

    if candidates:
        return candidates, ""

    source_count = max(len(message_ids), int(search_payload.get("total") or 0))
    if source_count > 0 and not message_ids:
        return [], "search_returned_count_without_message_ids"

    for msg_id in message_ids:
        if msg_id not in seen_ids:
            seen_ids.add(msg_id)
            candidates.append({
                "msg_id": msg_id,
                "source": source,
                "search_order": len(candidates),
            })
    return candidates, ""


def _fetch_message_detail(msg_id, audit=None, source=""):
    cmd = f"lark-cli im +messages-mget --message-ids '{msg_id}' --as bot"
    detail_result = _lark_run(cmd)

    detail_data = _load_json_output(detail_result.stdout, detail_result.stderr, "resolve_chat.mget")
    if detail_data is None:
        if audit:
            audit.add_mget({
                "source": source,
                "message_id": msg_id,
                "ok": False,
                "error": "mget parse failed",
                "stderr_summary": _truncate(getattr(detail_result, "stderr", ""), 500),
            })
        return None, "mget parse failed"

    if not detail_data.get("ok"):
        error = detail_data.get("error", "mget failed")
        if audit:
            audit.add_mget({
                "source": source,
                "message_id": msg_id,
                "ok": False,
                "error": _truncate(error, 500),
                "stderr_summary": _truncate(getattr(detail_result, "stderr", ""), 500),
            })
        return None, error

    msgs = detail_data.get("data", {}).get("messages", [])
    if not msgs:
        if audit:
            audit.add_mget({
                "source": source,
                "message_id": msg_id,
                "ok": False,
                "error": "mget returned no messages",
                "stderr_summary": _truncate(getattr(detail_result, "stderr", ""), 500),
            })
        return None, "mget returned no messages"

    msg = msgs[0]
    if audit:
        sender = msg.get("sender", {})
        audit.add_mget({
            "source": source,
            "message_id": msg_id,
            "ok": True,
            "chat_id": msg.get("chat_id", ""),
            "chat_type": msg.get("chat_type") or msg.get("chat_type_v2") or "",
            "sender_id": sender.get("id", ""),
            "create_time": msg.get("create_time", ""),
            "update_time": msg.get("update_time", ""),
            "timestamp": msg.get("timestamp", ""),
        })
    return msg, ""


def _detail_candidates(candidates, audit=None):
    detailed_candidates = []
    detail_errors = []
    for candidate in candidates:
        msg = candidate.get("msg")
        if _message_needs_detail(msg):
            if not candidate.get("msg_id"):
                detail_errors.append({
                    "msg_id": "",
                    "source": candidate["source"],
                    "error": "missing_message_id_for_detail_fetch",
                })
                continue
            msg, error_detail = _fetch_message_detail(
                candidate["msg_id"],
                audit=audit,
                source=candidate["source"],
            )
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
    return detailed_candidates, detail_errors


def _valid_source_candidates(detailed_candidates, allow_p2p=True):
    valid_candidates = []
    group_candidate_count = 0
    group_at_bot_count = 0
    group_filtered_count = 0
    unsupported_chat_type_count = 0
    for candidate in detailed_candidates:
        msg = candidate["msg"]
        chat_type = msg.get("chat_type") or msg.get("chat_type_v2") or ""
        if chat_type == "group":
            group_candidate_count += 1
            if _group_mentions_bot(msg):
                group_at_bot_count += 1
                valid_candidates.append(candidate)
            else:
                group_filtered_count += 1
        elif chat_type == "p2p" and allow_p2p:
            valid_candidates.append(candidate)
        else:
            unsupported_chat_type_count += 1
    return (
        valid_candidates,
        group_candidate_count,
        group_at_bot_count,
        group_filtered_count,
        unsupported_chat_type_count,
    )


def _select_latest_candidate(valid_candidates):
    timed_candidates = [c for c in valid_candidates if c["time_value"] is not None]
    if timed_candidates:
        return max(timed_candidates, key=lambda c: (c["time_value"], c["search_order"]))
    return valid_candidates[0]


def _message_text_value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        return _message_text_value(parsed)
    if isinstance(value, dict):
        parts = []
        for key in ("text", "content", "title"):
            if key in value:
                parts.append(_message_text_value(value.get(key)))
        for item in value.values():
            if isinstance(item, (dict, list)):
                parts.append(_message_text_value(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(_message_text_value(item) for item in value)
    return str(value)


def _message_content_text(msg):
    if not isinstance(msg, dict):
        return ""
    for key in ("content", "text", "body"):
        text = _message_text_value(msg.get(key))
        if text:
            return text
    return ""


def _normalize_route_text(text):
    text = str(text or "")
    text = re.sub(r'<at\b[^>]*>.*?</at>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[@＠]\s*tom\b', '', text, flags=re.IGNORECASE)
    text = text.lower()
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', text)


def _route_similarity(source_query, msg):
    expected = _normalize_route_text(source_query)
    actual = _normalize_route_text(_message_content_text(msg))
    if not expected or not actual:
        return 0.0
    return difflib.SequenceMatcher(None, expected, actual).ratio()


def _result_from_selected_candidate(
    selected,
    matched_count,
    detail_errors,
    group_candidate_count,
    group_at_bot_count,
    group_filtered_count,
    unsupported_chat_type_count,
    window_minutes,
    audit=None,
    similarity_score=None,
    valid_candidate_count=None,
):
    msg = selected["msg"]
    source = selected["source"]
    search_strategy = f"latest_query_{source}_{window_minutes}m"
    sender = msg.get("sender", {})
    chat_type = msg.get("chat_type") or msg.get("chat_type_v2") or ""

    result = {
        "chat_id": msg.get("chat_id", ""),
        "chat_type": chat_type,
        "resolved_chat_type": chat_type,
        "sender_open_id": sender.get("id", ""),
        "sender_name": sender.get("name") or sender.get("id", ""),
        "matched_msg_id": selected["msg_id"],
        "matched_count": matched_count,
        "search_strategy": search_strategy,
        "selected_time_field": selected.get("time_field", ""),
        "selected_time_value": selected.get("time_value"),
        "detail_errors": detail_errors,
        "group_candidate_count": group_candidate_count,
        "group_at_bot_count": group_at_bot_count,
        "group_filtered_count": group_filtered_count,
    }
    if similarity_score is not None:
        result["similarity_score"] = similarity_score
    if valid_candidate_count is not None:
        result["valid_candidate_count"] = valid_candidate_count

    if audit:
        audit_selection = {
            "selected_source": source,
            "matched_msg_id": selected["msg_id"],
            "resolved_chat_id": result["chat_id"],
            "resolved_chat_type": chat_type,
            "matched_count": matched_count,
            "selected_time_field": selected.get("time_field", ""),
            "selected_time_value": selected.get("time_value"),
            "group_candidate_count": group_candidate_count,
            "group_at_bot_count": group_at_bot_count,
            "group_filtered_count": group_filtered_count,
            "unsupported_chat_type_count": unsupported_chat_type_count,
        }
        if similarity_score is not None:
            audit_selection["highest_similarity"] = round(similarity_score, 4)
        if valid_candidate_count is not None:
            audit_selection["valid_candidate_count"] = valid_candidate_count
        audit.set_selection(**audit_selection)
    return result


def _resolve_at_tom_fallback(
    query,
    start,
    window_minutes,
    audit=None,
    zero_result_retry_delays=ZERO_RESULT_RETRY_DELAYS,
    sleep_func=time.sleep,
):
    source = "mixed_at_tom_fallback"
    search_data = _search_messages(
        query="@Tom",
        start=start,
        audit=audit,
        source=source,
        zero_result_retry_delays=zero_result_retry_delays,
        sleep_func=sleep_func,
        page_limit=AT_TOM_FALLBACK_PAGE_LIMIT,
        page_size=AT_TOM_FALLBACK_PAGE_SIZE,
    )
    search_strategy = f"latest_query_{source}_{window_minutes}m"
    candidate_limit = AT_TOM_FALLBACK_PAGE_LIMIT * AT_TOM_FALLBACK_PAGE_SIZE

    def unresolved(error, **extra):
        if audit:
            audit.set_selection(
                selected_source=source,
                matched_msg_id="",
                resolved_chat_id="",
                resolved_chat_type="",
                reason=error,
                fallback_candidate_limit=candidate_limit,
                **extra,
            )
        return {
            "unresolved": True,
            "error": error,
            "matched_count": extra.get("matched_count", 0),
            "search_strategy": search_strategy,
            **extra,
        }

    if search_data is None:
        return unresolved("at_tom_fallback_search_failed")
    if not search_data.get("ok"):
        return unresolved(
            "at_tom_fallback_search_failed",
            search_error=search_data.get("error", "fallback search failed"),
        )

    search_payload = search_data.get("data", {})
    candidates, candidate_error = _candidates_from_search_payload(search_payload, source)
    if candidate_error:
        return unresolved(candidate_error)
    if not candidates:
        return unresolved("at_tom_fallback_no_candidates")

    matched_count = len(candidates)
    detailed_candidates, detail_errors = _detail_candidates(candidates, audit=audit)
    if not detailed_candidates:
        sys.stderr.write(f"[resolve_chat] @Tom fallback mget error: {json.dumps(detail_errors[:3], ensure_ascii=False)[:500]}\n")
        return unresolved(
            "at_tom_fallback_detail_fetch_failed",
            matched_count=matched_count,
            detail_errors=detail_errors[:3],
        )

    (
        valid_candidates,
        group_candidate_count,
        group_at_bot_count,
        group_filtered_count,
        unsupported_chat_type_count,
    ) = _valid_source_candidates(detailed_candidates, allow_p2p=False)

    if not valid_candidates:
        return unresolved(
            "at_tom_fallback_no_valid_group_mention",
            matched_count=matched_count,
            detail_errors=detail_errors[:3],
            group_candidate_count=group_candidate_count,
            group_at_bot_count=group_at_bot_count,
            group_filtered_count=group_filtered_count,
            unsupported_chat_type_count=unsupported_chat_type_count,
        )

    scored = []
    for candidate in valid_candidates:
        score = _route_similarity(query, candidate["msg"])
        candidate["similarity_score"] = score
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, selected = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else None

    if best_score < AT_TOM_FALLBACK_SIMILARITY_THRESHOLD:
        return unresolved(
            "at_tom_fallback_low_similarity",
            matched_count=matched_count,
            valid_candidate_count=len(valid_candidates),
            highest_similarity=round(best_score, 4),
        )
    if second_score is not None and (best_score - second_score) <= AT_TOM_FALLBACK_SIMILARITY_EPSILON:
        return unresolved(
            "at_tom_fallback_ambiguous_similarity",
            matched_count=matched_count,
            valid_candidate_count=len(valid_candidates),
            highest_similarity=round(best_score, 4),
            second_similarity=round(second_score, 4),
        )

    return _result_from_selected_candidate(
        selected=selected,
        matched_count=matched_count,
        detail_errors=detail_errors,
        group_candidate_count=group_candidate_count,
        group_at_bot_count=group_at_bot_count,
        group_filtered_count=group_filtered_count,
        unsupported_chat_type_count=unsupported_chat_type_count,
        window_minutes=window_minutes,
        audit=audit,
        similarity_score=best_score,
        valid_candidate_count=len(valid_candidates),
    )


def _message_time_value(msg):
    """Return a comparable millisecond timestamp and the source field name."""
    for key in ("create_time", "update_time", "timestamp"):
        raw_value = msg.get(key)
        if raw_value is None or raw_value == "":
            continue
        try:
            value = int(str(raw_value))
        except (TypeError, ValueError):
            value = None
        if value is None:
            text = str(raw_value).strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
                    return int(parsed.timestamp() * 1000), key
                except ValueError:
                    continue
            continue
        if value < 10_000_000_000:
            value *= 1000
        return value, key
    return None, ""


def _recent_start(minutes):
    tz = timezone(timedelta(hours=8))
    return (datetime.now(tz) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def resolve_chat(
    query,
    window_minutes=15,
    audit=None,
    zero_result_retry_delays=ZERO_RESULT_RETRY_DELAYS,
    sleep_func=time.sleep,
):
    """在时间窗内用问题文本混合搜索群聊/私聊来源消息。

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
    if audit:
        audit.set_context(query, window_minutes, start)

    source = "mixed"
    search_data = _search_messages(
        query=query,
        start=start,
        audit=audit,
        source=source,
        zero_result_retry_delays=zero_result_retry_delays,
        sleep_func=sleep_func,
    )
    if search_data is None:
        if audit:
            audit.set_selection(
                selected_source="",
                matched_msg_id="",
                resolved_chat_id="",
                resolved_chat_type="",
                reason="search_failed",
            )
        return {
            "unresolved": True,
            "error": "search_failed",
            "matched_count": 0,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
        }

    if not search_data.get("ok"):
        error_detail = search_data.get("error", "mixed search failed")
        sys.stderr.write(f"[resolve_chat] mixed search error: {json.dumps(error_detail, ensure_ascii=False)[:500]}\n")
        if audit:
            audit.set_selection(
                selected_source="",
                matched_msg_id="",
                resolved_chat_id="",
                resolved_chat_type="",
                reason="search_failed",
            )
        return {
            "unresolved": True,
            "error": "search_failed",
            "matched_count": 0,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
            "search_error": error_detail,
        }

    search_payload = search_data.get("data", {})
    candidates, candidate_error = _candidates_from_search_payload(search_payload, source)

    if not candidates:
        if candidate_error:
            if audit:
                audit.set_selection(
                    selected_source="",
                    matched_msg_id="",
                    resolved_chat_id="",
                    resolved_chat_type="",
                    reason=candidate_error,
                )
            return {
                "unresolved": True,
                "error": candidate_error,
                "matched_count": 0,
                "search_strategy": f"latest_query_mixed_{window_minutes}m",
            }
        fallback_result = _resolve_at_tom_fallback(
            query,
            start,
            window_minutes,
            audit=audit,
            zero_result_retry_delays=zero_result_retry_delays,
            sleep_func=sleep_func,
        )
        if fallback_result:
            return fallback_result
        if audit:
            audit.set_selection(
                selected_source="",
                matched_msg_id="",
                resolved_chat_id="",
                resolved_chat_type="",
                reason="no_candidates",
            )
        return {
            "unresolved": True,
            "matched_count": 0,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
        }
    matched_count = len(candidates)

    detailed_candidates, detail_errors = _detail_candidates(candidates, audit=audit)

    if not detailed_candidates:
        sys.stderr.write(f"[resolve_chat] mget error: {json.dumps(detail_errors[:3], ensure_ascii=False)[:500]}\n")
        if audit:
            audit.set_selection(
                selected_source="",
                matched_msg_id="",
                resolved_chat_id="",
                resolved_chat_type="",
                reason="detail_fetch_failed",
            )
        return {
            "unresolved": True,
            "error": "detail_fetch_failed",
            "matched_count": matched_count,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
            "detail_errors": detail_errors[:3],
        }

    (
        valid_candidates,
        group_candidate_count,
        group_at_bot_count,
        group_filtered_count,
        unsupported_chat_type_count,
    ) = _valid_source_candidates(detailed_candidates, allow_p2p=True)

    if not valid_candidates:
        if audit:
            audit.set_selection(
                selected_source="",
                matched_msg_id="",
                resolved_chat_id="",
                resolved_chat_type="",
                reason="no_valid_chat_type_or_group_mention",
                matched_count=matched_count,
                group_candidate_count=group_candidate_count,
                group_at_bot_count=group_at_bot_count,
                group_filtered_count=group_filtered_count,
                unsupported_chat_type_count=unsupported_chat_type_count,
            )
        return {
            "unresolved": True,
            "error": "no_valid_chat_type_or_group_mention",
            "matched_count": matched_count,
            "search_strategy": f"latest_query_mixed_{window_minutes}m",
            "detail_errors": detail_errors[:3],
            "group_candidate_count": group_candidate_count,
            "group_at_bot_count": group_at_bot_count,
            "group_filtered_count": group_filtered_count,
            "unsupported_chat_type_count": unsupported_chat_type_count,
        }

    selected = _select_latest_candidate(valid_candidates)
    return _result_from_selected_candidate(
        selected=selected,
        matched_count=matched_count,
        detail_errors=detail_errors,
        group_candidate_count=group_candidate_count,
        group_at_bot_count=group_at_bot_count,
        group_filtered_count=group_filtered_count,
        unsupported_chat_type_count=unsupported_chat_type_count,
        window_minutes=window_minutes,
        audit=audit,
    )


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
    audit=None,
):
    sender_info = {}
    send_meta = {}

    if args.chat:
        return args.chat, "--chat", sender_info, send_meta, None

    if args.resolve_chat:
        source_query = (args.source_query or "").strip()
        if not source_query:
            if audit:
                audit.set_fallback(
                    fallback_target="plain_text",
                    fallback_reason="missing_source_query",
                    chat_source="",
                    env_key="",
                )
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
        if audit:
            audit.set_context(source_query, args.resolve_window_minutes, "")

        resolved = resolver(source_query, args.resolve_window_minutes, audit=audit)
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
            if audit:
                audit.set_fallback(
                    fallback_target="",
                    fallback_reason="resolved_source",
                    chat_source=chat_source,
                    env_key="",
                )
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
            if audit:
                audit.set_fallback(
                    fallback_target="default_private_chat",
                    fallback_reason=send_meta["source_resolution"].get("error", "no_match"),
                    chat_source=default_private_key,
                    env_key=default_private_key,
                )
            return default_private_chat_id, default_private_key, sender_info, send_meta, None

        if env_chat_id:
            send_meta["source_resolution"] = _source_resolution_meta(
                resolved,
                "current_env_chat",
                chat_key,
            )
            if audit:
                audit.set_fallback(
                    fallback_target="current_env_chat",
                    fallback_reason=send_meta["source_resolution"].get("error", "no_match"),
                    chat_source=chat_key,
                    env_key=chat_key,
                )
            return env_chat_id, chat_key, sender_info, send_meta, None

        source_meta = _source_resolution_meta(resolved, "plain_text")
        if audit:
            audit.set_fallback(
                fallback_target="plain_text",
                fallback_reason=source_meta.get("error", "no_match"),
                chat_source="",
                env_key="",
            )
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


def send_card(chat_id, card, chat_source, meta=None, quiet_success=False, audit=None):
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
        if audit:
            audit.set_send(
                status="error",
                chat_id=chat_id,
                chat_source=chat_source,
                error="send_response_parse_failed",
                stderr_summary=_truncate(stderr_detail, 500),
            )
            path = audit.flush()
            if path:
                output["route_audit_path"] = path
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    if data.get("ok"):
        msg_id = data.get("data", {}).get("message_id", "unknown")
        if audit:
            audit.set_send(
                status="sent",
                message_id=msg_id,
                chat_id=chat_id,
                chat_source=chat_source,
            )
            path = audit.flush()
        else:
            path = ""
        if quiet_success:
            return
        output = {"status": "sent", "message_id": msg_id,
                  "chat_id": chat_id, "chat_source": chat_source}
        if meta:
            output["meta"] = meta
        if path:
            output["route_audit_path"] = path
        print(json.dumps(output, ensure_ascii=False))
    else:
        sys.stderr.write(f"[send_card] API 错误: {json.dumps(data, ensure_ascii=False)[:500]}\n")
        output = {"status": "error", "detail": data,
                  "card_size": len(card_json), "chat_id": chat_id,
                  "chat_source": chat_source}
        if meta:
            output["meta"] = meta
        if audit:
            audit.set_send(
                status="error",
                chat_id=chat_id,
                chat_source=chat_source,
                error="send_api_error",
                detail=_truncate(json.dumps(data, ensure_ascii=False), 500),
            )
            path = audit.flush()
            if path:
                output["route_audit_path"] = path
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
    parser.add_argument("--debug-log-dir", default="",
                        help="可选：将来源反查审计日志写入该目录，便于追踪 fallback 到 home channel 的原因")
    parser.add_argument("--quiet-success", action="store_true",
                        help="发送成功时不向 stdout 输出 status JSON，用于避免宿主应用重复回复")

    args = parser.parse_args()

    load_env()

    sender_info = {}
    send_meta = {}
    audit = RouteAudit(args.debug_log_dir)

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
        audit=audit,
    )
    if target_error:
        audit.set_send(status="not_sent", error=target_error.get("error", "target_error"))
        path = audit.flush()
        if path:
            target_error["route_audit_path"] = path
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

    send_card(
        chat_id,
        card,
        chat_source,
        meta=send_meta,
        quiet_success=args.quiet_success,
        audit=audit,
    )


if __name__ == "__main__":
    main()
