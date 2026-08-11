"""Feishu SDK/CLI transport with lazy runtime discovery and argv-only calls."""

from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from feishu_card import fit_card_payload, serialize_card


HERMES_ENV_PATH = os.path.expanduser("~/.hermes/.env")
HERMES_PYTHON_CANDIDATES = (
    os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python"),
    os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python3"),
)
LARK_CLI_CANDIDATE_PATHS = (
    os.path.expanduser(
        "~/.workbuddy/binaries/node/cli-connector-packages/bin/lark-cli"
    ),
)
WORKBUDDY_NODE_BIN_DIR = os.environ.get(
    "WORKBUDDY_NODE_BIN_DIR",
    os.path.expanduser("~/.workbuddy/binaries/node/versions/22.22.2/bin"),
)
SEARCH_RETRY_DELAYS = (5, 10, 15)
ZERO_RESULT_RETRY_DELAYS = (3, 4, 4, 4)
AUDIT_CREDENTIAL_ENV_KEYS = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_ACCESS_TOKEN",
    "FEISHU_TENANT_ACCESS_TOKEN",
    "LARK_ACCESS_TOKEN",
    "FEISHU_COOKIE",
)
AUDIT_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(app[_-]?secret|access[_-]?token|tenant[_-]?access[_-]?token|"
    r"authorization|cookie)\b(\s*[:=]\s*)([^\s,;]+)"
)

_LARK_OAPI_MODULE = None
_LARK_OAPI_IMPORT_FAILED = False
_LARK_OAPI_CLIENT = None
_LARK_OAPI_CLIENT_FAILED = False


@dataclass(frozen=True)
class TransportResult:
    status: str
    message_id: str = ""
    transport: str = ""
    detail: Any = None
    original_size_bytes: int = 0
    final_size_bytes: int = 0
    truncated: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "sent"


class TransportError(RuntimeError):
    def __init__(self, output: dict[str, Any], exit_code: int = 1):
        super().__init__(str(output.get("detail") or output.get("error") or "send failed"))
        self.output = output
        self.exit_code = exit_code


def import_lark_oapi():
    global _LARK_OAPI_MODULE, _LARK_OAPI_IMPORT_FAILED
    if _LARK_OAPI_MODULE is not None:
        return _LARK_OAPI_MODULE
    if _LARK_OAPI_IMPORT_FAILED:
        return None
    try:
        _LARK_OAPI_MODULE = importlib.import_module("lark_oapi")
    except Exception:
        _LARK_OAPI_IMPORT_FAILED = True
        return None
    return _LARK_OAPI_MODULE


def maybe_relaunch_with_hermes_python(importer=import_lark_oapi):
    """Compatibility helper. The CLI no longer invokes this during --help."""
    if importer() is not None:
        return
    current_python = os.path.realpath(sys.executable)
    for candidate in HERMES_PYTHON_CANDIDATES:
        if (
            os.path.isfile(candidate)
            and os.access(candidate, os.X_OK)
            and os.path.realpath(candidate) != current_python
        ):
            os.execv(candidate, [candidate] + sys.argv)


def load_env_credentials():
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if app_id and app_secret:
        return app_id, app_secret
    try:
        with open(HERMES_ENV_PATH, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if line.startswith("FEISHU_APP_ID=") and not app_id:
                    app_id = line.split("=", 1)[1].strip()
                elif line.startswith("FEISHU_APP_SECRET=") and not app_secret:
                    app_secret = line.split("=", 1)[1].strip()
    except OSError:
        pass
    return app_id, app_secret


def lark_oapi_client(
    importer: Callable[[], Any] = import_lark_oapi,
    credential_loader: Callable[[], tuple[str, str]] = load_env_credentials,
):
    global _LARK_OAPI_CLIENT, _LARK_OAPI_CLIENT_FAILED
    if _LARK_OAPI_CLIENT is not None:
        return _LARK_OAPI_CLIENT
    if _LARK_OAPI_CLIENT_FAILED:
        return None
    sdk = importer()
    if sdk is None:
        _LARK_OAPI_CLIENT_FAILED = True
        return None
    app_id, app_secret = credential_loader()
    if not app_id or not app_secret:
        _LARK_OAPI_CLIENT_FAILED = True
        return None
    try:
        _LARK_OAPI_CLIENT = (
            sdk.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(sdk.LogLevel.ERROR)
            .build()
        )
    except Exception:
        _LARK_OAPI_CLIENT_FAILED = True
        return None
    return _LARK_OAPI_CLIENT


def resolve_lark_cli():
    candidates = []
    configured = os.environ.get("LARK_CLI_PATH", "").strip()
    if configured:
        candidates.append(os.path.expanduser(configured))
    candidates.extend(LARK_CLI_CANDIDATE_PATHS)
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("lark-cli")
    if found:
        return found
    raise FileNotFoundError(
        "lark-cli not found: checked " + ", ".join(candidates) + " and PATH"
    )


def lark_env(lark_cli=None):
    env = os.environ.copy()
    env["LARK_CLI_NO_PROXY"] = "1"
    path_parts = (
        WORKBUDDY_NODE_BIN_DIR,
        os.path.dirname(lark_cli) if lark_cli else "",
        env.get("PATH", ""),
    )
    env["PATH"] = os.pathsep.join(part for part in path_parts if part)
    return env


def lark_run(args):
    lark_cli = resolve_lark_cli()
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
        env=lark_env(lark_cli),
    )


def load_env_files():
    for env_path in (
        "~/.hermes/.env",
        "~/Desktop/feishu/.env",
        "~/.workbuddy/.env",
        "~/.lark/.env",
    ):
        resolved = os.path.expanduser(env_path)
        if not os.path.exists(resolved):
            continue
        with open(resolved, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def oapi_get_user_request(uid, uid_type):
    from lark_oapi.api.contact.v3 import GetUserRequest

    return GetUserRequest.builder().user_id(uid).user_id_type(uid_type).build()


def oapi_get_message_request(message_id):
    from lark_oapi.api.im.v1 import GetMessageRequest

    return GetMessageRequest.builder().message_id(message_id).build()


def to_open_id(
    uid,
    uid_type="user_id",
    client_factory=lark_oapi_client,
    runner=lark_run,
    request_builder=oapi_get_user_request,
):
    if not uid:
        return None
    uid = str(uid).strip()
    if uid.startswith("ou_"):
        return uid
    if uid_type not in ("user_id", "union_id", "open_id"):
        uid_type = "user_id"
    client = client_factory()
    if client is not None:
        try:
            response = client.contact.v3.user.get(request_builder(uid, uid_type))
            if response.success():
                user = getattr(response.data, "user", None)
                open_id = getattr(user, "open_id", None)
                if open_id:
                    return open_id
        except Exception:
            pass
    try:
        result = runner(
            [
                "contact",
                "+get-user",
                "--user-id",
                uid,
                "--user-id-type",
                uid_type,
                "--as",
                "bot",
            ]
        )
        data = json.loads(result.stdout)
    except (AttributeError, json.JSONDecodeError, OSError, subprocess.SubprocessError):
        return None
    if data.get("ok"):
        return ((data.get("data") or {}).get("user") or {}).get("open_id") or None
    return None


def _truncate(value, limit=500):
    return ("" if value is None else str(value))[:limit]


def _redact_audit_text(value, sensitive_text="", limit=500):
    text = "" if value is None else str(value)
    if sensitive_text:
        text = text.replace(sensitive_text, "<redacted_source_query>")
    for key in AUDIT_CREDENTIAL_ENV_KEYS:
        credential = os.environ.get(key, "")
        if len(credential) >= 4:
            text = text.replace(credential, "<redacted_credential>")
    text = AUDIT_CREDENTIAL_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}<redacted_credential>"
        ),
        text,
    )
    return text[:limit]


def _load_json_output(stdout, stderr, context):
    raw = (stdout or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    pass
    sys.stderr.write(f"[{context}] parse failed: {(stderr or raw)[:500]}\n")
    return None


def _extract_message_ids(payload):
    message_ids = payload.get("message_ids", [])
    if not message_ids and payload.get("messages"):
        message_ids = [
            item.get("message_id")
            for item in payload.get("messages", [])
            if isinstance(item, dict) and item.get("message_id")
        ]
    return message_ids if isinstance(message_ids, list) else []


def _extract_messages(payload):
    messages = payload.get("messages", [])
    return messages if isinstance(messages, list) else []


def search_messages(
    query,
    start,
    audit=None,
    source="mixed",
    retry_delays=SEARCH_RETRY_DELAYS,
    zero_result_retry_delays=ZERO_RESULT_RETRY_DELAYS,
    sleep_func=time.sleep,
    page_limit=1,
    page_size=5,
    runner=lark_run,
):
    command = [
        "im",
        "+messages-search",
        "--as",
        "user",
        "--query",
        query,
        "--start",
        start,
        "--page-limit",
        str(page_limit),
        "--page-size",
        str(page_size),
    ]
    attempts = []
    delays = tuple(retry_delays or ())
    zero_delays = tuple(zero_result_retry_delays or ())
    data = result = None
    error_retry_index = zero_retry_index = 0
    while True:
        fatal_transport_error = False
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
            result = runner(command)
            attempt["returncode"] = getattr(result, "returncode", 0)
            data = _load_json_output(
                result.stdout, result.stderr, "resolve_chat.search"
            )
            attempt["ok"] = bool(
                isinstance(data, dict)
                and data.get("ok")
                and attempt["returncode"] == 0
            )
            if attempt["ok"]:
                payload = data.get("data", {})
                payload = payload if isinstance(payload, dict) else {}
                ids, messages = _extract_message_ids(payload), _extract_messages(payload)
                total = payload.get("total")
                try:
                    total_count = int(total) if total is not None else None
                except (TypeError, ValueError):
                    total_count = None
                attempt.update(
                    total=total,
                    message_ids_count=len(ids),
                    zero_result=not (
                        ids
                        or messages
                        or (total_count is not None and total_count > 0)
                    ),
                )
            attempt["error_summary"] = (
                _redact_audit_text(data.get("error"), query)
                if isinstance(data, dict)
                else "parse_failed"
            )
            attempt["stderr_summary"] = _redact_audit_text(
                getattr(result, "stderr", ""), query
            )
        except subprocess.TimeoutExpired as exc:
            attempt.update(timeout=True, error_summary="timeout")
            attempt["stderr_summary"] = _redact_audit_text(
                getattr(exc, "stderr", ""), query
            )
            data = None
        except (OSError, subprocess.SubprocessError) as exc:
            attempt["error_summary"] = (
                f"transport_error:{type(exc).__name__}"
            )
            data = None
            fatal_transport_error = True
        finally:
            attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            attempts.append(attempt)
        if attempt["ok"] and not attempt["zero_result"]:
            break
        if fatal_transport_error:
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
        payload = payload if isinstance(payload, dict) else {}
        message_ids = _extract_message_ids(payload)
        audit.add_search(
            {
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
                "total": payload.get("total"),
                "message_ids_count": len(message_ids),
                "message_ids_preview": message_ids[:5],
                "attempt_count": len(attempts),
                "attempts": attempts,
                "zero_result_retry_enabled": bool(zero_delays),
                "zero_result_retry_count": sum(
                    1 for item in attempts[:-1] if item.get("zero_result")
                ),
                "error_summary": (
                    _redact_audit_text(data.get("error"), query)
                    if isinstance(data, dict)
                    else "parse_failed"
                ),
                "stderr_summary": _redact_audit_text(
                    getattr(result, "stderr", ""), query
                ),
            }
        )
    return data


def _message_needs_detail(message):
    if not isinstance(message, dict) or not message.get("chat_id"):
        return True
    chat_type = message.get("chat_type") or message.get("chat_type_v2")
    if chat_type not in ("group", "p2p"):
        return True
    if not isinstance(message.get("sender"), dict) or not message["sender"].get("id"):
        return True
    return chat_type == "group" and "mentions" not in message


def fetch_message_detail(
    message_id,
    audit=None,
    source="",
    client_factory=lark_oapi_client,
    runner=lark_run,
    request_builder=oapi_get_message_request,
):
    client = client_factory()
    if client is not None:
        try:
            response = client.im.v1.message.get(request_builder(message_id))
            if response.success():
                items = getattr(response.data, "items", None) or []
                if items:
                    item = items[0]
                    sender = getattr(item, "sender", None)
                    body = getattr(item, "body", None)
                    chat_type = (
                        getattr(item, "chat_type", "")
                        or getattr(item, "chat_type_v2", "")
                        or ""
                    )
                    raw_mentions = getattr(item, "mentions", None)
                    mentions = [
                        {
                            key: getattr(mention, key, "") or ""
                            for key in ("key", "id", "id_type", "name", "tenant_key")
                        }
                        for mention in raw_mentions or []
                    ]
                    body_content = (getattr(body, "content", "") if body else "") or ""
                    message = {
                        "message_id": getattr(item, "message_id", None) or message_id,
                        "chat_id": getattr(item, "chat_id", "") or "",
                        "chat_type": chat_type,
                        "create_time": getattr(item, "create_time", "") or "",
                        "update_time": getattr(item, "update_time", "") or "",
                        "timestamp": getattr(item, "create_time", "") or "",
                        "sender": {
                            "id": getattr(sender, "id", "") if sender else "",
                            "name": (
                                getattr(sender, "sender_name", "") if sender else ""
                            )
                            or "",
                        },
                        "body": {"content": body_content},
                        "mentions": mentions,
                    }
                    complete = (
                        not _message_needs_detail(message)
                        and bool(body_content)
                        and (chat_type != "group" or raw_mentions is not None)
                    )
                    if complete and audit:
                        audit.add_mget(
                            {
                                "source": source,
                                "message_id": message_id,
                                "ok": True,
                                "chat_id": message["chat_id"],
                                "chat_type": message["chat_type"],
                                "sender_id": message["sender"]["id"],
                                "create_time": message["create_time"],
                                "update_time": message["update_time"],
                                "timestamp": message["timestamp"],
                                "transport": "lark_oapi",
                            }
                        )
                    if complete:
                        return message, ""
        except Exception:
            pass

    result = None
    try:
        result = runner(
            ["im", "+messages-mget", "--message-ids", str(message_id), "--as", "bot"]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        error = f"mget transport failed: {type(exc).__name__}"
    else:
        data = _load_json_output(result.stdout, result.stderr, "resolve_chat.mget")
        if data is None:
            error = "mget parse failed"
        elif not data.get("ok"):
            error = data.get("error", "mget failed")
        else:
            messages = (data.get("data") or {}).get("messages", [])
            if messages:
                message = messages[0]
                if audit:
                    sender = message.get("sender", {})
                    audit.add_mget(
                        {
                            "source": source,
                            "message_id": message_id,
                            "ok": True,
                            "chat_id": message.get("chat_id", ""),
                            "chat_type": message.get("chat_type")
                            or message.get("chat_type_v2")
                            or "",
                            "sender_id": sender.get("id", ""),
                            "create_time": message.get("create_time", ""),
                            "update_time": message.get("update_time", ""),
                            "timestamp": message.get("timestamp", ""),
                            "transport": "lark_cli",
                        }
                    )
                return message, ""
            error = "mget returned no messages"
    if audit:
        audit.add_mget(
            {
                "source": source,
                "message_id": message_id,
                "ok": False,
                "error": _redact_audit_text(error),
                "stderr_summary": _redact_audit_text(
                    getattr(result, "stderr", "")
                ),
                "transport": "lark_cli",
            }
        )
    return None, error


def oapi_create_message_request(card, receive_id, receive_id_type):
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    body = CreateMessageRequestBody()
    body.receive_id = receive_id
    body.msg_type = "interactive"
    body.content = json.dumps(card, ensure_ascii=False)
    return (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(body)
        .build()
    )


def send_card_via_oapi(
    card,
    target_type,
    chat_id,
    user_id,
    client_factory=lark_oapi_client,
    request_builder=oapi_create_message_request,
):
    client = client_factory()
    if client is None:
        return False, "lark_oapi unavailable"
    is_user = target_type == "user" and bool(user_id)
    receive_id = user_id if is_user else chat_id
    receive_type = "open_id" if is_user else "chat_id"
    try:
        response = client.im.v1.message.create(
            request_builder(card, receive_id, receive_type)
        )
        if response.success():
            message_id = getattr(response.data, "message_id", None)
            return (True, message_id) if message_id else (False, "missing message_id")
        return False, (
            f"code={getattr(response, 'code', 'unknown')} "
            f"msg={getattr(response, 'msg', 'unknown')}"
        )
    except Exception as exc:
        return False, str(exc)


def send_card(
    chat_id,
    card,
    chat_source,
    meta=None,
    quiet_success=False,
    audit=None,
    target_type="chat",
    user_id=None,
    oapi_sender=send_card_via_oapi,
    runner=lark_run,
):
    meta = meta or {}
    fitted_card, size_meta = fit_card_payload(card)
    card_json = serialize_card(fitted_card)
    if size_meta["truncated"]:
        sys.stderr.write(
            "[send_card] 卡片已截断: "
            f"{size_meta['original_size_bytes']} -> {size_meta['final_size_bytes']} bytes\n"
        )
    oapi_ok, oapi_result = oapi_sender(
        fitted_card, target_type, chat_id, user_id
    )
    if oapi_ok:
        output = {
            "status": "sent",
            "message_id": oapi_result,
            "chat_id": chat_id,
            "chat_source": chat_source,
            "transport": "lark_oapi",
        }
        if meta:
            output["meta"] = meta
        path = ""
        if audit:
            audit.set_send(
                status="sent",
                message_id=oapi_result,
                chat_id=chat_id,
                chat_source=chat_source,
                transport="lark_oapi",
                **size_meta,
            )
            path = audit.flush()
        if path:
            output["route_audit_path"] = path
        result = TransportResult(
            status="sent",
            message_id=oapi_result,
            transport="lark_oapi",
            payload=output,
            **size_meta,
        )
        if not quiet_success:
            print(json.dumps(output, ensure_ascii=False))
        return result

    command = ["im", "+messages-send"]
    if target_type == "user" and user_id:
        command.extend(["--user-id", user_id])
    else:
        command.extend(["--chat-id", chat_id])
    command.extend(
        ["--as", "bot", "--msg-type", "interactive", "--content", card_json]
    )
    try:
        result = runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            failure_reason = "lark_cli_timeout"
            detail = "lark-cli send timed out"
        elif isinstance(exc, FileNotFoundError):
            failure_reason = "lark_cli_unavailable"
            detail = "lark-cli is unavailable"
        else:
            failure_reason = "lark_cli_transport_error"
            detail = "lark-cli transport failed"
        error = {
            "status": "error",
            "detail": detail,
            "card_size": len(card_json.encode("utf-8")),
            "chat_id": chat_id,
            "chat_source": chat_source,
        }
        if meta:
            error["meta"] = meta
        if audit:
            audit.set_send(
                status="error",
                chat_id=chat_id,
                chat_source=chat_source,
                error="send_transport_error",
                transport="lark_cli",
                oapi_failure_reason=_redact_audit_text(oapi_result, limit=200),
                transport_failure_reason=failure_reason,
                **size_meta,
            )
            path = audit.flush()
            if path:
                error["route_audit_path"] = path
        raise TransportError(error) from exc
    try:
        data = json.loads(result.stdout)
    except (AttributeError, json.JSONDecodeError):
        detail = getattr(result, "stderr", "") or "send failed"
        error = {
            "status": "error",
            "detail": detail[:200],
            "card_size": len(card_json.encode("utf-8")),
            "chat_id": chat_id,
            "chat_source": chat_source,
        }
        audit_error = "send_response_parse_failed"
        audit_detail = {"stderr_summary": _redact_audit_text(detail)}
    else:
        if data.get("ok"):
            message_id = (data.get("data") or {}).get("message_id", "unknown")
            output = {
                "status": "sent",
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_source": chat_source,
            }
            if meta:
                output["meta"] = meta
            path = ""
            if audit:
                audit.set_send(
                    status="sent",
                    message_id=message_id,
                    chat_id=chat_id,
                    chat_source=chat_source,
                    transport="lark_cli",
                    oapi_failure_reason=_redact_audit_text(
                        oapi_result, limit=200
                    ),
                    **size_meta,
                )
                path = audit.flush()
            if path:
                output["route_audit_path"] = path
            transport_result = TransportResult(
                status="sent",
                message_id=message_id,
                transport="lark_cli",
                detail=oapi_result,
                payload=output,
                **size_meta,
            )
            if not quiet_success:
                print(json.dumps(output, ensure_ascii=False))
            return transport_result
        error = {
            "status": "error",
            "detail": data,
            "card_size": len(card_json.encode("utf-8")),
            "chat_id": chat_id,
            "chat_source": chat_source,
        }
        audit_error = "send_api_error"
        audit_detail = {
            "detail": _redact_audit_text(json.dumps(data, ensure_ascii=False))
        }
    if meta:
        error["meta"] = meta
    if audit:
        audit.set_send(
            status="error",
            chat_id=chat_id,
            chat_source=chat_source,
            error=audit_error,
            transport="lark_cli",
            oapi_failure_reason=_redact_audit_text(oapi_result, limit=200),
            **audit_detail,
            **size_meta,
        )
        path = audit.flush()
        if path:
            error["route_audit_path"] = path
    raise TransportError(error)


# Compatibility names retained for callers that imported the old monolith.
_import_lark_oapi = import_lark_oapi
_maybe_relaunch_with_hermes_python = maybe_relaunch_with_hermes_python
_load_env_credentials = load_env_credentials
_lark_oapi_client = lark_oapi_client
_resolve_lark_cli = resolve_lark_cli
_lark_env = lark_env
_lark_run = lark_run
_to_open_id = to_open_id
_search_messages = search_messages
_fetch_message_detail = fetch_message_detail
_oapi_create_message_request = oapi_create_message_request
_send_card_via_oapi = send_card_via_oapi
load_env = load_env_files
