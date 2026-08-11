"""Feishu card schema, rendering, raw-log parsing, and size fitting."""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Iterator


MAX_CARD_SIZE_BYTES = 28_000
CARD_TRUNCATION_NOTICE = "⚠️ 内容过长已截断；完整证据请查看 CLS 链接或原始输出。"
LEVEL_ICON = {
    "INFO": "🟢",
    "WARN": "🟡",
    "WARNING": "🟡",
    "ERROR": "🔴",
}
COLOR_MAP = {"red": "red", "yellow": "yellow", "green": "green", "blue": "blue"}
CARD_DATA_SCHEMA = {
    "summary_fields": "list[{label, value}]",
    "call_chain": (
        "list[object], recommended keys: level/time/service/content; "
        "aliases are rendered automatically"
    ),
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
    r"(?:^|\n)"
    r"(\|[^\n]+\|)\n"
    r"(\|[-:\| ]+\|)\n"
    r"((?:\|[^\n]+\|\n?)+)",
    re.MULTILINE,
)


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

    log_count = data.get(
        "log_count", len(call_chain) if isinstance(call_chain, list) else 0
    )
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
            if not isinstance(table.get("headers"), list):
                field_errors.append(f"table_data[{index}].headers must be a list")
            rows = table.get("rows")
            if not isinstance(rows, list) or any(
                not isinstance(row, list) for row in rows
            ):
                field_errors.append(
                    f"table_data[{index}].rows must be a list of lists"
                )

    if not isinstance(data.get("analysis", ""), str):
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
        if text:
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
    icon = LEVEL_ICON.get(level.upper(), "🟢") if level else "🟢"
    extra = _format_extra_fields(item, consumed_keys)
    detail = " ".join(part for part in (content, extra) if part).strip()
    if not detail:
        detail = _format_extra_fields(item, set())
    parts = [icon]
    if timestamp:
        parts.append(f"`{timestamp}`")
    if service:
        parts.append(f"**{service}**")
    if detail:
        parts.append(detail)
    return " ".join(parts)


def _split_row(row):
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def parse_markdown_tables(text):
    segments = []
    last_end = 0
    for match in MD_TABLE_RE.finditer(text):
        before = text[last_end : match.start()].strip()
        if before:
            segments.append(("text", before))
        headers = _split_row(match.group(1))
        rows = [_split_row(line) for line in match.group(3).strip().splitlines()]
        segments.append(("table", {"columns": headers, "rows": rows}))
        last_end = match.end()
    after = text[last_end:].strip()
    if after:
        segments.append(("text", after))
    return segments


def build_table_element(columns, rows):
    col_defs = [
        {
            "name": f"col_{index}",
            "display_name": heading,
            "data_type": "markdown",
            "width": "auto",
        }
        for index, heading in enumerate(columns)
    ]
    row_data = []
    for row in rows:
        row_data.append(
            {
                f"col_{index}": str(row[index]) if index < len(row) else ""
                for index in range(len(columns))
            }
        )
    return {
        "tag": "table",
        "columns": col_defs,
        "rows": row_data,
        "row_height": "auto",
        "row_max_height": "200px",
    }


def build_rich_elements(text):
    segments = parse_markdown_tables(text)
    if len(segments) == 1 and segments[0][0] == "text":
        return [
            {"tag": "div", "text": {"tag": "lark_md", "content": segments[0][1]}}
        ]
    elements = []
    for segment_type, segment_data in segments:
        if segment_type == "text":
            elements.append(
                {"tag": "div", "text": {"tag": "lark_md", "content": segment_data}}
            )
        else:
            elements.append(
                build_table_element(segment_data["columns"], segment_data["rows"])
            )
    return elements


def parse_cls_raw_text(raw_text):
    count_match = re.search(r"日志条数\s+([\d,]+)", raw_text)
    total_count = int(count_match.group(1).replace(",", "")) if count_match else 0
    rows = []
    pattern = r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+).*?message:(.*?)(?=\n\t|\Z)"
    service_match = re.search(r'serviceName[=:]\s*"?(\w+)"?', raw_text)
    service = service_match.group(1) if service_match else "unknown"
    for match in re.finditer(pattern, raw_text, re.DOTALL):
        timestamp = match.group(1).strip()
        message = match.group(2).strip()[:300]
        if "ERROR" in message or "异常" in message or "错误" in message:
            level = "ERROR"
        elif "WARN" in message or "拦截" in message:
            level = "WARN"
        else:
            level = "INFO"
        rows.append(
            {
                "time": timestamp.split()[-1] if " " in timestamp else timestamp,
                "service": service,
                "level": level,
                "content": message,
            }
        )
    return {"call_chain": rows[:20], "log_count": total_count or len(rows)}


def build_card(
    title,
    color,
    cls_url,
    cls_url_expanded,
    data,
    sender_open_id="",
    sender_name="",
    chat_type="group",
    content_mode="log",
):
    elements = []
    if sender_open_id and chat_type == "group":
        display_name = sender_name or sender_open_id
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f'<at user_id="{sender_open_id}">{display_name}</at>\n',
                },
            }
        )

    summary_fields = data.get("summary_fields", [])
    if summary_fields:
        lines = [f"**{item['label']}**: {item['value']}" for item in summary_fields]
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
        )
        elements.append({"tag": "hr"})

    call_chain = data.get("call_chain", [])
    log_count = data.get("log_count", len(call_chain))
    if call_chain:
        display_items = call_chain[:10] if log_count > 20 else call_chain
        chain_lines = [_format_call_chain_item(item) for item in display_items]
        if log_count > 20:
            chain_lines.append(f"\n... 共 **{log_count}** 条日志，仅展示最近 10 条")
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(chain_lines)},
            }
        )
    elif content_mode == "log" and log_count == 0 and not summary_fields:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**无匹配日志**\n\n可能原因：查询时间范围不对、serviceName 不匹配、"
                        "或该请求未产生日志。"
                    ),
                },
            }
        )

    for table in data.get("table_data", []):
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        if headers and rows:
            elements.append(build_table_element(headers, rows))

    analysis = data.get("analysis", "")
    if analysis:
        elements.append({"tag": "hr"})
        elements.extend(build_rich_elements(f"**📋 分析结论:**\n{analysis}"))

    links = []
    if cls_url:
        links.append(f"[🔗 跳转链接]({cls_url})")
    if cls_url_expanded:
        links.append(f"[⏱ 扩大查询范围]({cls_url_expanded})")
    if links:
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": " · ".join(links)},
                },
            ]
        )

    if content_mode == "business-logic":
        note = f"🧭 本地业务逻辑分析 | {time.strftime('%H:%M')}"
    elif content_mode == "combined":
        note = f"🧭 源码 + 日志联合分析 · {log_count} 条日志 | {time.strftime('%H:%M')}"
    else:
        note = f"🕐 共查询到 {log_count} 条日志 | {time.strftime('%H:%M')}"
    elements.append(
        {"tag": "div", "text": {"tag": "lark_md", "content": f"_{note}_"}}
    )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": COLOR_MAP.get(color, "blue"),
        },
        "body": {"elements": elements},
    }


def serialize_card(card):
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def card_size_bytes(card):
    return len(serialize_card(card).encode("utf-8"))


def _truncate_utf8(value, max_bytes, suffix=""):
    suffix_bytes = suffix.encode("utf-8")
    if max_bytes <= len(suffix_bytes):
        return suffix_bytes[:max_bytes].decode("utf-8", errors="ignore")
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value
    prefix = raw[: max_bytes - len(suffix_bytes)].decode("utf-8", errors="ignore")
    return prefix + suffix


def _text_slots(value) -> Iterator[tuple[object, object, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield value, key, item
            else:
                yield from _text_slots(item)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                yield value, index, item
            else:
                yield from _text_slots(item)


def _truncation_element():
    return {
        "tag": "div",
        "text": {"tag": "lark_md", "content": CARD_TRUNCATION_NOTICE},
    }


def fit_card_payload(card, max_bytes=MAX_CARD_SIZE_BYTES):
    if max_bytes <= 0:
        raise ValueError("max_bytes must be > 0")
    fitted = copy.deepcopy(card)
    original_size = card_size_bytes(fitted)
    if original_size <= max_bytes:
        return fitted, {
            "original_size_bytes": original_size,
            "final_size_bytes": original_size,
            "truncated": False,
        }

    body = fitted.setdefault("body", {})
    elements = body.setdefault("elements", [])
    notice = _truncation_element()
    elements.append(notice)
    while card_size_bytes(fitted) > max_bytes:
        current_size = card_size_bytes(fitted)
        candidates = [
            (len(text.encode("utf-8")), parent, key, text)
            for parent, key, text in _text_slots(fitted)
            if text != CARD_TRUNCATION_NOTICE and len(text.encode("utf-8")) > 16
        ]
        if candidates:
            text_size, parent, key, text = max(candidates, key=lambda item: item[0])
            target = max(0, text_size - (current_size - max_bytes) - 64)
            parent[key] = _truncate_utf8(
                text, target, suffix="...\n\n" + CARD_TRUNCATION_NOTICE
            )
            continue
        removable = [item for item in elements if item is not notice]
        if removable:
            elements.remove(max(removable, key=card_size_bytes))
            continue
        minimal = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "结果"},
                "template": "blue",
            },
            "body": {"elements": [notice]},
        }
        if card_size_bytes(minimal) > max_bytes:
            raise ValueError("max_bytes is too small for a valid Feishu card")
        fitted = minimal
        break

    return fitted, {
        "original_size_bytes": original_size,
        "final_size_bytes": card_size_bytes(fitted),
        "truncated": True,
    }


# Compatibility aliases used by existing informal Python callers.
_serialize_card = serialize_card
_card_size_bytes = card_size_bytes
