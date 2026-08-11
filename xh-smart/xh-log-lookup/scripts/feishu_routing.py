"""Feishu source-message routing and non-sensitive route auditing."""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from feishu_transport import (
    ZERO_RESULT_RETRY_DELAYS,
    _extract_message_ids,
    _extract_messages,
    fetch_message_detail,
    search_messages,
)


BOT_OPEN_ID = os.environ.get(
    "FEISHU_BOT_OPEN_ID", "ou_ae0341a3578d833a22b5f2927b103988"
)
AT_TOM_FALLBACK_PAGE_LIMIT = 5
AT_TOM_FALLBACK_PAGE_SIZE = 10
AT_TOM_FALLBACK_SIMILARITY_THRESHOLD = 0.72
AT_TOM_FALLBACK_SIMILARITY_EPSILON = 0.01


def _now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _truncate(value, limit=500):
    return ("" if value is None else str(value))[:limit]


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
            Path(self.debug_log_dir).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone(timedelta(hours=8))).strftime(
                "%Y%m%d_%H%M%S"
            )
            path = Path(self.debug_log_dir) / (
                f"send_feishu_card_route_{timestamp}_{os.getpid()}.json"
            )
            path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return str(path)
        except Exception as exc:
            sys.stderr.write(f"[route_audit] flush failed: {_truncate(exc, 200)}\n")
            return ""


@dataclass
class SendTarget:
    chat_id: str | None = None
    chat_source: str = ""
    sender_info: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    @property
    def target_type(self) -> str:
        return self.sender_info.get("target_type", "chat")

    @property
    def user_id(self) -> str | None:
        return self.sender_info.get("user_id")

    def as_legacy(self):
        return self.chat_id, self.chat_source, self.sender_info, self.meta, self.error


def _message_needs_detail(message):
    if not isinstance(message, dict) or not message.get("chat_id"):
        return True
    chat_type = message.get("chat_type") or message.get("chat_type_v2")
    if chat_type not in ("group", "p2p"):
        return True
    if not isinstance(message.get("sender"), dict) or not message["sender"].get("id"):
        return True
    return chat_type == "group" and "mentions" not in message


def _group_mentions_bot(message):
    mentions = message.get("mentions") if isinstance(message, dict) else None
    if not isinstance(mentions, list):
        return False
    return any(
        isinstance(mention, dict)
        and (
            mention.get("id") == BOT_OPEN_ID
            or str(mention.get("name", "")).strip().lower() == "tom"
        )
        for mention in mentions
    )


def _candidate_from_message(message, source, search_order):
    return {
        "msg_id": message.get("message_id", "") if isinstance(message, dict) else "",
        "msg": message,
        "source": source,
        "search_order": search_order,
    }


def _candidates_from_search_payload(payload, source):
    messages = _extract_messages(payload)
    message_ids = _extract_message_ids(payload)
    candidates = []
    seen_ids = set()
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = message.get("message_id") or f"inline:{len(candidates)}"
        if message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        candidates.append(_candidate_from_message(message, source, len(candidates)))
    if candidates:
        return candidates, ""
    try:
        source_count = max(len(message_ids), int(payload.get("total") or 0))
    except (TypeError, ValueError):
        source_count = len(message_ids)
    if source_count > 0 and not message_ids:
        return [], "search_returned_count_without_message_ids"
    for message_id in message_ids:
        if message_id not in seen_ids:
            seen_ids.add(message_id)
            candidates.append(
                {
                    "msg_id": message_id,
                    "source": source,
                    "search_order": len(candidates),
                }
            )
    return candidates, ""


def _message_time_value(message):
    for key in ("create_time", "update_time", "timestamp"):
        raw_value = message.get(key)
        if raw_value is None or raw_value == "":
            continue
        try:
            value = int(str(raw_value))
        except (TypeError, ValueError):
            value = None
        if value is None:
            text = str(raw_value).strip()
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S%z",
            ):
                try:
                    parsed = datetime.strptime(text, fmt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(
                            tzinfo=timezone(timedelta(hours=8))
                        )
                    return int(parsed.timestamp() * 1000), key
                except ValueError:
                    continue
            continue
        if value < 10_000_000_000:
            value *= 1000
        return value, key
    return None, ""


def _detail_candidates(candidates, audit=None, detail_fetcher=fetch_message_detail):
    detailed = []
    errors = []
    for candidate in candidates:
        message = candidate.get("msg")
        if _message_needs_detail(message):
            if not candidate.get("msg_id"):
                errors.append(
                    {
                        "msg_id": "",
                        "source": candidate["source"],
                        "error": "missing_message_id_for_detail_fetch",
                    }
                )
                continue
            message, error = detail_fetcher(
                candidate["msg_id"], audit=audit, source=candidate["source"]
            )
            if message is None:
                errors.append(
                    {
                        "msg_id": candidate["msg_id"],
                        "source": candidate["source"],
                        "error": error,
                    }
                )
                continue
        time_value, time_field = _message_time_value(message)
        candidate.update(
            msg=message, time_value=time_value, time_field=time_field
        )
        detailed.append(candidate)
    return detailed, errors


def _valid_source_candidates(candidates, allow_p2p=True):
    valid = []
    group_count = group_at_count = group_filtered = unsupported = 0
    for candidate in candidates:
        message = candidate["msg"]
        chat_type = message.get("chat_type") or message.get("chat_type_v2") or ""
        if chat_type == "group":
            group_count += 1
            if _group_mentions_bot(message):
                group_at_count += 1
                valid.append(candidate)
            else:
                group_filtered += 1
        elif chat_type == "p2p" and allow_p2p:
            valid.append(candidate)
        else:
            unsupported += 1
    return valid, group_count, group_at_count, group_filtered, unsupported


def _select_latest_candidate(candidates):
    timed = [candidate for candidate in candidates if candidate["time_value"] is not None]
    if timed:
        return max(timed, key=lambda item: (item["time_value"], item["search_order"]))
    return candidates[0]


def _message_text_value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            return _message_text_value(json.loads(text))
        except Exception:
            return text
    if isinstance(value, dict):
        parts = [_message_text_value(value.get(key)) for key in ("text", "content", "title") if key in value]
        parts.extend(
            _message_text_value(item)
            for item in value.values()
            if isinstance(item, (dict, list))
        )
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(_message_text_value(item) for item in value)
    return str(value)


def _message_content_text(message):
    if not isinstance(message, dict):
        return ""
    for key in ("content", "text", "body"):
        text = _message_text_value(message.get(key))
        if text:
            return text
    return ""


def _normalize_route_text(text):
    text = re.sub(
        r"<at\b[^>]*>.*?</at>", "", str(text or ""), flags=re.IGNORECASE
    )
    text = re.sub(r"[@＠]\s*tom\b", "", text, flags=re.IGNORECASE).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _route_similarity(source_query, message):
    expected = _normalize_route_text(source_query)
    actual = _normalize_route_text(_message_content_text(message))
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
    message = selected["msg"]
    source = selected["source"]
    chat_type = message.get("chat_type") or message.get("chat_type_v2") or ""
    sender = message.get("sender", {})
    result = {
        "chat_id": message.get("chat_id", ""),
        "chat_type": chat_type,
        "resolved_chat_type": chat_type,
        "sender_open_id": sender.get("id", ""),
        "sender_name": sender.get("name") or sender.get("id", ""),
        "matched_msg_id": selected["msg_id"],
        "matched_count": matched_count,
        "search_strategy": f"latest_query_{source}_{window_minutes}m",
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
        selection = {
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
            selection["highest_similarity"] = round(similarity_score, 4)
        if valid_candidate_count is not None:
            selection["valid_candidate_count"] = valid_candidate_count
        audit.set_selection(**selection)
    return result


def _resolve_at_tom_fallback(
    query,
    start,
    window_minutes,
    audit=None,
    zero_result_retry_delays=ZERO_RESULT_RETRY_DELAYS,
    sleep_func=time.sleep,
    searcher=search_messages,
    detail_fetcher=fetch_message_detail,
):
    source = "mixed_at_tom_fallback"
    search_data = searcher(
        query="@Tom",
        start=start,
        audit=audit,
        source=source,
        zero_result_retry_delays=zero_result_retry_delays,
        sleep_func=sleep_func,
        page_limit=AT_TOM_FALLBACK_PAGE_LIMIT,
        page_size=AT_TOM_FALLBACK_PAGE_SIZE,
    )
    strategy = f"latest_query_{source}_{window_minutes}m"
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
            "search_strategy": strategy,
            **extra,
        }

    if search_data is None or not search_data.get("ok"):
        extra = {}
        if isinstance(search_data, dict):
            extra["search_error"] = search_data.get("error", "fallback search failed")
        return unresolved("at_tom_fallback_search_failed", **extra)
    candidates, candidate_error = _candidates_from_search_payload(
        search_data.get("data", {}), source
    )
    if candidate_error:
        return unresolved(candidate_error)
    if not candidates:
        return unresolved("at_tom_fallback_no_candidates")
    matched_count = len(candidates)
    detailed, errors = _detail_candidates(
        candidates, audit=audit, detail_fetcher=detail_fetcher
    )
    if not detailed:
        return unresolved(
            "at_tom_fallback_detail_fetch_failed",
            matched_count=matched_count,
            detail_errors=errors[:3],
        )
    valid, group_count, at_count, filtered, unsupported = _valid_source_candidates(
        detailed, allow_p2p=False
    )
    if not valid:
        return unresolved(
            "at_tom_fallback_no_valid_group_mention",
            matched_count=matched_count,
            detail_errors=errors[:3],
            group_candidate_count=group_count,
            group_at_bot_count=at_count,
            group_filtered_count=filtered,
            unsupported_chat_type_count=unsupported,
        )
    scored = sorted(
        ((_route_similarity(query, item["msg"]), item) for item in valid),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, selected = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else None
    if best_score < AT_TOM_FALLBACK_SIMILARITY_THRESHOLD:
        return unresolved(
            "at_tom_fallback_low_similarity",
            matched_count=matched_count,
            valid_candidate_count=len(valid),
            highest_similarity=round(best_score, 4),
        )
    if second_score is not None and (
        best_score - second_score
    ) <= AT_TOM_FALLBACK_SIMILARITY_EPSILON:
        return unresolved(
            "at_tom_fallback_ambiguous_similarity",
            matched_count=matched_count,
            valid_candidate_count=len(valid),
            highest_similarity=round(best_score, 4),
            second_similarity=round(second_score, 4),
        )
    return _result_from_selected_candidate(
        selected,
        matched_count,
        errors,
        group_count,
        at_count,
        filtered,
        unsupported,
        window_minutes,
        audit=audit,
        similarity_score=best_score,
        valid_candidate_count=len(valid),
    )


def _recent_start(minutes):
    tz = timezone(timedelta(hours=8))
    return (datetime.now(tz) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%S+08:00"
    )


def resolve_chat(
    query,
    window_minutes=15,
    audit=None,
    zero_result_retry_delays=ZERO_RESULT_RETRY_DELAYS,
    sleep_func=time.sleep,
    searcher=search_messages,
    detail_fetcher=fetch_message_detail,
):
    query = (query or "").strip()
    if not query:
        return {}
    start = _recent_start(window_minutes)
    if audit:
        audit.set_context(query, window_minutes, start)
    source = "mixed"
    data = searcher(
        query=query,
        start=start,
        audit=audit,
        source=source,
        zero_result_retry_delays=zero_result_retry_delays,
        sleep_func=sleep_func,
    )
    strategy = f"latest_query_mixed_{window_minutes}m"
    if data is None or not data.get("ok"):
        if audit:
            audit.set_selection(reason="search_failed")
        result = {
            "unresolved": True,
            "error": "search_failed",
            "matched_count": 0,
            "search_strategy": strategy,
        }
        if isinstance(data, dict):
            result["search_error"] = data.get("error", "mixed search failed")
        return result
    candidates, candidate_error = _candidates_from_search_payload(
        data.get("data", {}), source
    )
    if not candidates:
        if candidate_error:
            if audit:
                audit.set_selection(reason=candidate_error)
            return {
                "unresolved": True,
                "error": candidate_error,
                "matched_count": 0,
                "search_strategy": strategy,
            }
        return _resolve_at_tom_fallback(
            query,
            start,
            window_minutes,
            audit=audit,
            zero_result_retry_delays=zero_result_retry_delays,
            sleep_func=sleep_func,
            searcher=searcher,
            detail_fetcher=detail_fetcher,
        )
    matched_count = len(candidates)
    detailed, errors = _detail_candidates(
        candidates, audit=audit, detail_fetcher=detail_fetcher
    )
    if not detailed:
        if audit:
            audit.set_selection(reason="detail_fetch_failed")
        return {
            "unresolved": True,
            "error": "detail_fetch_failed",
            "matched_count": matched_count,
            "search_strategy": strategy,
            "detail_errors": errors[:3],
        }
    valid, group_count, at_count, filtered, unsupported = _valid_source_candidates(
        detailed, allow_p2p=True
    )
    if not valid:
        if audit:
            audit.set_selection(
                reason="no_valid_chat_type_or_group_mention",
                matched_count=matched_count,
                group_candidate_count=group_count,
                group_at_bot_count=at_count,
                group_filtered_count=filtered,
                unsupported_chat_type_count=unsupported,
            )
        return {
            "unresolved": True,
            "error": "no_valid_chat_type_or_group_mention",
            "matched_count": matched_count,
            "search_strategy": strategy,
            "detail_errors": errors[:3],
            "group_candidate_count": group_count,
            "group_at_bot_count": at_count,
            "group_filtered_count": filtered,
            "unsupported_chat_type_count": unsupported,
        }
    return _result_from_selected_candidate(
        _select_latest_candidate(valid),
        matched_count,
        errors,
        group_count,
        at_count,
        filtered,
        unsupported,
        window_minutes,
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


def resolve_send_target_model(
    args,
    env_chat_id,
    chat_key,
    chat_type,
    chat_type_key,
    sender_open_id,
    sender_key,
    default_private_key,
    default_private_chat_id,
    allow_home_channel_fallback=False,
    resolver=resolve_chat,
    audit=None,
):
    user_id = getattr(args, "user_id", None)
    direct_chat_id = getattr(args, "chat_id", None)
    direct_chat_type = getattr(args, "chat_type", None)
    direct_sender = getattr(args, "sender_open_id", None)
    if user_id:
        return SendTarget(
            chat_source="--user-id",
            sender_info={
                "target_type": "user",
                "user_id": user_id,
                "chat_type": direct_chat_type or "p2p",
                "sender_open_id": direct_sender or user_id,
                "sender_name": direct_sender or user_id,
            },
        )
    if direct_chat_id:
        return SendTarget(
            chat_id=direct_chat_id,
            chat_source="--chat-id",
            sender_info={
                "target_type": "chat",
                "chat_id": direct_chat_id,
                "chat_type": direct_chat_type or "group",
                "sender_open_id": direct_sender or "",
                "sender_name": direct_sender or "",
            },
        )
    if args.chat:
        return SendTarget(chat_id=args.chat, chat_source="--chat")
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
            return SendTarget(
                error={
                    "status": "error",
                    "error": "missing_source_query",
                    "message": (
                        "--resolve-chat 必须传 --source-query 用户原始问题，"
                        "禁止用摘要、分析标题或关键切片反查来源。"
                    ),
                    "fallback": "plain_text",
                }
            )
        meta = {
            "source_query_provided": True,
            "source_query_length": len(source_query),
        }
        if audit:
            audit.set_context(source_query, args.resolve_window_minutes, "")
        resolved = resolver(source_query, args.resolve_window_minutes, audit=audit)
        if resolved and not resolved.get("unresolved") and resolved.get("chat_id"):
            resolved_chat = resolved["chat_id"]
            source = resolved.get("search_strategy") or "--resolve-chat"
            meta.update(
                {
                    "search_strategy": resolved.get("search_strategy"),
                    "matched_msg_id": resolved.get("matched_msg_id"),
                    "matched_count": resolved.get("matched_count", 0),
                    "resolved_chat_type": resolved.get("resolved_chat_type"),
                    "selected_time_field": resolved.get("selected_time_field"),
                    "selected_time_value": resolved.get("selected_time_value"),
                }
            )
            if env_chat_id and env_chat_id != resolved_chat:
                meta["env_chat_conflict"] = {
                    "env_key": chat_key,
                    "env_chat_id": env_chat_id,
                    "resolved_chat_id": resolved_chat,
                }
            if audit:
                audit.set_fallback(
                    fallback_target="",
                    fallback_reason="resolved_source",
                    chat_source=source,
                    env_key="",
                )
            return SendTarget(resolved_chat, source, resolved, meta)
        if resolved and not resolved.get("unresolved"):
            resolved = {**resolved, "unresolved": True, "error": "missing_resolved_chat_id"}
        if env_chat_id:
            meta["source_resolution"] = _source_resolution_meta(
                resolved, "current_env_chat", chat_key
            )
            if audit:
                audit.set_fallback(
                    fallback_target="current_env_chat",
                    fallback_reason=meta["source_resolution"].get("error", "no_match"),
                    chat_source=chat_key,
                    env_key=chat_key,
                )
            return SendTarget(env_chat_id, chat_key, meta=meta)
        if default_private_chat_id and allow_home_channel_fallback:
            meta["source_resolution"] = _source_resolution_meta(
                resolved, "default_private_chat", default_private_key
            )
            if audit:
                audit.set_fallback(
                    fallback_target="default_private_chat",
                    fallback_reason=meta["source_resolution"].get("error", "no_match"),
                    chat_source=default_private_key,
                    env_key=default_private_key,
                )
            return SendTarget(default_private_chat_id, default_private_key, meta=meta)
        source_meta = _source_resolution_meta(resolved, "plain_text")
        if audit:
            audit.set_fallback(
                fallback_target="plain_text",
                fallback_reason=source_meta.get("error", "no_match"),
                chat_source="",
                env_key="",
            )
        return SendTarget(
            meta=meta,
            error={
                "status": "unresolved",
                "error": "missing_private_target",
                "source_error": source_meta.get("error", "no_match"),
                "warning": (
                    "未搜索到可用的群聊 @Bot 或私聊 p2p 来源消息，无法确定发送目标；"
                    "降级为纯文本结论，由宿主 Agent 回复通道送达发起人"
                ),
                "search_strategy": source_meta.get("search_strategy"),
                "matched_count": source_meta.get("matched_count", 0),
                "resolved_chat_type": source_meta.get("resolved_chat_type"),
                "expected_chat_type": source_meta.get("expected_chat_type"),
                "detail_errors": source_meta.get("detail_errors", []),
                "fallback": "plain_text",
            },
        )
    if env_chat_id:
        sender_info = {}
        if sender_open_id:
            sender_info = {
                "sender_open_id": sender_open_id,
                "sender_name": sender_open_id,
                "chat_type": chat_type if chat_type in ("group", "p2p") else "group",
                "chat_source": chat_key,
                "sender_source": sender_key,
                "chat_type_source": chat_type_key,
            }
        return SendTarget(env_chat_id, chat_key, sender_info)
    if default_private_chat_id and allow_home_channel_fallback:
        return SendTarget(default_private_chat_id, default_private_key)
    return SendTarget(
        error={
            "status": "error",
            "error": "missing_chat",
            "message": (
                "缺少发送目标：请传 --chat，或由宿主 Agent 注入 "
                "FEISHU_CURRENT_CHAT_ID / AGENT_CURRENT_CHAT_ID，"
                "或显式使用 --resolve-chat --source-query，"
                "或配置 WORKBUDDY_HOME_CHANNEL_CHAT_ID 并显式传 "
                "--allow-home-channel-fallback。"
            ),
            "fallback": "plain_text",
        }
    )


def resolve_send_target(*args, **kwargs):
    return resolve_send_target_model(*args, **kwargs).as_legacy()
