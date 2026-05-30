#!/usr/bin/env python3
"""CLS query helper for xh-log-lookup.

Queries CLS through the internal HTTP API by default. Browser paths are
fallbacks: WorkBuddy URL first, then local Chrome only when explicitly selected.
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote


TOPICS = {
    "prod": {
        "topic_id": "f6748b3a-8ab8-4191-b848-cb90b1598901",
        "name": "logsvr-prod",
        "default_time": "now-7d,now",
        "expanded_time": "now-30d,now",
    },
    "test": {
        "topic_id": "1f92a7ca-cf46-4f4f-92dd-72c5df5910dc",
        "name": "logsvr-test-standard-lowfreq",
        "default_time": "now-1d,now",
        "expanded_time": "now-7d,now",
    },
}

BASE_URL = "https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search"
API_URL = "https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/api/cls?i=cls/SearchLog&uin=100034610027"


def ensure_ascii(value: str, label: str) -> None:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise SystemExit(
            f"{label} contains non-ASCII text. CLS queryBase64 cannot reliably "
            "carry Chinese; pass an ASCII --url-query for the jump URL and handle "
            "Chinese filtering from extracted page text."
        )


def query_b64(query: str) -> str:
    ensure_ascii(query, "--query/--url-query")
    return base64.b64encode(query.encode("ascii")).decode("ascii")


def build_url(query: str, env: str, time_range: str) -> str:
    topic_id = TOPICS[env]["topic_id"]
    b64 = quote(query_b64(query), safe="")
    return f"{BASE_URL}?region=ap-beijing&topic_id={topic_id}&time={time_range}&queryBase64={b64}"


def is_ascii(value: str) -> bool:
    try:
        value.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def derive_ascii_url_query(query: str) -> str:
    """Best-effort ASCII query for browser fallback URLs when API query has Chinese."""
    if is_ascii(query):
        return query

    clauses = []
    for field, value in re.findall(r'([A-Za-z0-9_.@-]+):"([^"]+)"', query):
        if is_ascii(value):
            clauses.append(f'{field}:"{value}"')
    return " AND ".join(clauses) if clauses else "*"


def build_fallback_urls(
    run_query: str,
    url_query: Optional[str],
    env: str,
    time_range: str,
    expanded_time: str,
) -> tuple[str, str, str, list[str]]:
    warnings = []
    effective_url_query = url_query or run_query
    if not is_ascii(effective_url_query):
        effective_url_query = derive_ascii_url_query(run_query)
        warnings.append(
            "browser fallback URL uses an ASCII-safe query because queryBase64 cannot carry Chinese"
        )
    return (
        build_url(effective_url_query, env, time_range),
        build_url(effective_url_query, env, expanded_time),
        effective_url_query,
        warnings,
    )


def apple_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def run_osascript(script: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


WINDOW_ID_FILE = Path("/tmp/cls_query_window_id.txt")


def _read_saved_window_id() -> str:
    try:
        return WINDOW_ID_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _save_window_id(window_id: str) -> None:
    WINDOW_ID_FILE.write_text(window_id)


def _clear_window_id() -> None:
    WINDOW_ID_FILE.unlink(missing_ok=True)


def _window_exists(window_id: str) -> bool:
    script = f'''
tell application "Google Chrome"
    try
        set w to first window whose id is {window_id}
        return "yes"
    on error
        return "no"
    end try
end tell
'''
    try:
        return run_osascript(script, timeout=10).strip() == "yes"
    except Exception:
        return False


def ensure_window(url: str) -> str:
    saved_id = _read_saved_window_id()
    if saved_id and _window_exists(saved_id):
        script = f'''
tell application "Google Chrome"
    set targetWindow to first window whose id is {saved_id}
    set URL of active tab of targetWindow to "{apple_string(url)}"
    return id of targetWindow
end tell
'''
        return run_osascript(script, timeout=15)

    script = f'''
tell application "Google Chrome"
    set targetWindow to make new window
    set URL of active tab of targetWindow to "{apple_string(url)}"
    return id of targetWindow
end tell
'''
    window_id = run_osascript(script, timeout=15)
    _save_window_id(window_id)
    return window_id


def close_cls_windows() -> int:
    """Close the script-created CLS window only; leave user-opened windows alone."""
    saved_id = _read_saved_window_id()
    _clear_window_id()
    if not saved_id or not _window_exists(saved_id):
        return 0
    script = f'''
tell application "Google Chrome"
    close (first window whose id is {saved_id})
    return 1
end tell
'''
    try:
        return int(run_osascript(script, timeout=15) or "0")
    except Exception:
        return 0


def check_login(window_id: str) -> bool:
    """Return True if page is on CLS, False if redirected to Argus login."""
    script = f'''
tell application "Google Chrome"
    return URL of active tab of (first window whose id is {window_id})
end tell
'''
    current_url = run_osascript(script, timeout=10)
    return "argus.xhdev.xyz" not in current_url


def execute_js(window_id: str, js: str, timeout: int = 30) -> str:
    script = f'''
tell application "Google Chrome"
    return execute active tab of (first window whose id is {window_id}) javascript "{apple_string(js)}"
end tell
'''
    return run_osascript(script, timeout=timeout)


def load_more(window_id: str, max_clicks: int, delay: float) -> tuple[int, bool]:
    """返回 (点击次数, 是否还有更多未加载的日志)"""
    clicks = 0
    for _ in range(max_clicks):
        execute_js(
            window_id,
            "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '加载更多')?.click()",
            timeout=10,
        )
        clicks += 1
        time.sleep(delay)
        has_more = execute_js(
            window_id,
            "document.body.innerText.includes('加载更多') ? 'yes' : 'no'",
            timeout=10,
        )
        if has_more.strip() != "yes":
            return clicks, False
    still_has_more = execute_js(
        window_id,
        "document.body.innerText.includes('加载更多') ? 'yes' : 'no'",
        timeout=10,
    )
    return clicks, still_has_more.strip() == "yes"


def parse_log_count(text: str) -> int:
    match = re.search(r"日志条数\s*([\d,]+)", text)
    return int(match.group(1).replace(",", "")) if match else 0


def count_loaded_logs(text: str) -> int:
    """从提取的全文中统计实际加载的日志条目数（按时间戳行计数）"""
    return len(re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}", text))


def parse_contracts(text: str) -> list[str]:
    return sorted(set(re.findall(r'contractNo":"(C[KS][^"]+)"', text)))


def parse_services(text: str) -> list[str]:
    return sorted(set(re.findall(r"serviceName[:=]\s*\"?([A-Za-z0-9_-]+)", text)))


def write_text(path: str, text: str) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return str(output)


def parse_time_bound(value: str, now: datetime) -> datetime:
    value = value.strip()
    if value == "now":
        return now

    relative = re.fullmatch(r"now-(\d+)([mhd])", value)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit == "m":
            return now - timedelta(minutes=amount)
        if unit == "h":
            return now - timedelta(hours=amount)
        return now - timedelta(days=amount)

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"unsupported time bound: {value}")


def parse_time_range_for_api(time_range: str) -> tuple[int, int]:
    if "," not in time_range:
        raise ValueError(
            f"unsupported time range: {time_range}. Use 'now-7d,now' or "
            "'YYYY-MM-DD HH:MM:SS,YYYY-MM-DD HH:MM:SS'."
        )
    start_value, end_value = time_range.split(",", 1)
    now = datetime.now()
    start = parse_time_bound(start_value, now)
    end = parse_time_bound(end_value, now)
    if start >= end:
        raise ValueError(f"invalid time range: start must be before end ({time_range})")
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _pick_total_count(response_data: dict, loaded_count: int) -> tuple[int, bool]:
    count_keys = ("TotalCount", "Total", "Count", "LogCount")
    for key in count_keys:
        value = response_data.get(key)
        if isinstance(value, int):
            return value, True
        if isinstance(value, str) and value.isdigit():
            return int(value), True
    return loaded_count, False


def _extract_message(log_json: object) -> str:
    if isinstance(log_json, dict):
        nested_log = log_json.get("log")
        if isinstance(nested_log, dict) and nested_log.get("message"):
            return str(nested_log["message"])
        if log_json.get("message"):
            return str(log_json["message"])
        fields = log_json.get("fields")
        if isinstance(fields, dict) and fields.get("message"):
            return str(fields["message"])
        return json.dumps(log_json, ensure_ascii=False)
    return str(log_json) if log_json is not None else ""


def _extract_service(log_json: object, message: str) -> str:
    if isinstance(log_json, dict):
        for key in ("serviceName", "service_name"):
            if log_json.get(key):
                return str(log_json[key])
        fields = log_json.get("fields")
        if isinstance(fields, dict):
            for key in ("application", "serviceName", "service_name"):
                if fields.get(key):
                    return str(fields[key])
    match = re.search(r"serviceName[:=]\s*\"?([A-Za-z0-9_-]+)", message)
    return match.group(1) if match else ""


def parse_api_response(response: dict, api_limit: int) -> tuple[list[dict], int, bool, bool]:
    response_data = response.get("Response", {})
    results = response_data.get("Results", [])
    logs = []

    for item in results:
        timestamp_ms = item.get("Time", 0) or 0
        if timestamp_ms:
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S.")
            timestamp += f"{timestamp_ms % 1000:03d}"
        else:
            timestamp = ""

        raw_log_json = item.get("LogJson", "")
        try:
            log_json = json.loads(raw_log_json) if isinstance(raw_log_json, str) else raw_log_json
        except Exception:
            log_json = raw_log_json

        message = _extract_message(log_json)
        service = _extract_service(log_json, message)
        log_entry = {
            "timestamp": timestamp,
            "timestamp_ms": timestamp_ms,
            "level": "INFO",
            "message": message,
            "serviceName": service,
            "source": item.get("TopicName", ""),
            "host": item.get("Source", ""),
        }
        highlights = item.get("HighLights", [])
        if highlights:
            log_entry["highlight"] = "; ".join(str(h) for h in highlights)
        logs.append(log_entry)

    total_count, total_count_available = _pick_total_count(response_data, len(logs))
    is_complete = total_count <= len(logs) if total_count_available else len(logs) < api_limit
    return logs, total_count, total_count_available, is_complete


def format_api_text(logs: list[dict]) -> str:
    lines = []
    for log in logs:
        service = f' serviceName:"{log["serviceName"]}"' if log.get("serviceName") else ""
        lines.append(f"{log.get('timestamp', '')}{service} {log.get('message', '')}".rstrip())
    return "\n".join(lines)


def query_cls_api(
    query: str,
    env: str,
    time_range: str,
    api_limit: int,
    timeout: int,
) -> tuple[list[dict], int, bool, bool]:
    from_ts, to_ts = parse_time_range_for_api(time_range)
    payload = {
        "service": "cls",
        "region": "ap-beijing",
        "action": "SearchLog",
        "version": "2020-10-16",
        "data": {
            "Query": query,
            "SamplingRate": 1,
            "From": from_ts,
            "To": to_ts,
            "QueryOptimize": 0,
            "SyntaxRule": 1,
            "Limit": api_limit,
            "Sort": "desc",
            "HighLight": True,
            "TopicId": TOPICS[env]["topic_id"],
            "UseNewAnalysis": True,
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {error_body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    return parse_api_response(json.loads(response_body), api_limit)


def build_base_result(
    args,
    run_query: str,
    url_query: str,
    time_range: str,
    expanded_time: str,
    cls_url: str,
    expanded_url: str,
    warnings: list[str],
) -> dict:
    return {
        "env": args.env,
        "topic_id": TOPICS[args.env]["topic_id"],
        "topic_name": TOPICS[args.env]["name"],
        "query": run_query,
        "url_query": url_query,
        "time": time_range,
        "expanded_time": expanded_time,
        "cls_url": cls_url,
        "expanded_url": expanded_url,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Query CLS by API first; browser paths are fallbacks.")
    parser.add_argument("--query", help="CLS query used for execution. API mode supports Chinese.")
    parser.add_argument("--close", action="store_true", help="Close CLS/Argus windows and exit.")
    parser.add_argument("--url-query", help="ASCII query used in jump URLs; defaults to --query.")
    parser.add_argument(
        "--method",
        choices=("auto", "api", "workbuddy", "local-chrome"),
        default="auto",
        help="Query method. auto tries API first, then returns WorkBuddy fallback URLs.",
    )
    parser.add_argument("--env", choices=sorted(TOPICS), default="prod")
    parser.add_argument("--time", dest="time_range")
    parser.add_argument("--expanded-time")
    parser.add_argument("--output", default="/tmp/cls_output.txt")
    parser.add_argument(
        "--api-limit",
        type=int,
        default=500,
        help="CLS API result limit. Defaults to 500 for stats probing and small exact stats.",
    )
    parser.add_argument("--api-timeout", type=int, default=60, help="CLS API timeout in seconds.")
    parser.add_argument("--max-load-more", type=int, default=15)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--wait", type=float, default=8.0)
    parser.add_argument(
        "--use-local-chrome",
        action="store_true",
        help="Open and operate a dedicated local Chrome window. Backup path only.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Only build WorkBuddy URLs; retained for compatibility.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="强制完整数据加载。自动重试加载更多；仍不完整时返回错误 JSON。",
    )
    parser.add_argument("--input-text", help="Parse an existing CLS text file instead of reading Chrome.")
    args = parser.parse_args()

    if args.close:
        closed = close_cls_windows()
        print(json.dumps({"closed_windows": closed}))
        return 0

    if not args.query:
        parser.error("--query is required unless --close is used")

    run_query = args.query
    time_range = args.time_range or TOPICS[args.env]["default_time"]
    expanded_time = args.expanded_time or TOPICS[args.env]["expanded_time"]
    method = args.method
    if args.use_local_chrome and method == "auto":
        method = "local-chrome"
    elif args.no_browser and method == "auto":
        method = "workbuddy"

    cls_url, expanded_url, url_query, warnings = build_fallback_urls(
        run_query,
        args.url_query,
        args.env,
        time_range,
        expanded_time,
    )
    base_result = build_base_result(
        args,
        run_query,
        url_query,
        time_range,
        expanded_time,
        cls_url,
        expanded_url,
        warnings,
    )

    if method == "workbuddy":
        result = {
            **base_result,
            "source": "workbuddy",
            "fallback_method": None,
            "output_path": None,
            "window_id": None,
            "log_count": None,
            "loaded_count": None,
            "has_more": None,
            "is_complete": None,
            "completeness_ratio": None,
            "services": [],
            "contracts": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if method in {"auto", "api"}:
        try:
            logs, total_count, total_count_available, is_complete = query_cls_api(
                run_query,
                args.env,
                time_range,
                args.api_limit,
                args.api_timeout,
            )
            text = format_api_text(logs)
            output_path = write_text(args.output, text)
            loaded_count = len(logs)

            result = {
                **base_result,
                "source": "api",
                "fallback_method": None if is_complete else "workbuddy",
                "output_path": output_path,
                "window_id": None,
                "load_more_clicks": 0,
                "log_count": total_count,
                "loaded_count": loaded_count,
                "total_count_available": total_count_available,
                "has_more": not is_complete,
                "is_complete": is_complete,
                "completeness_ratio": (
                    round(loaded_count / max(total_count, 1), 3)
                    if total_count_available and total_count > 0
                    else (1.0 if is_complete else None)
                ),
                "services": parse_services(text),
                "contracts": parse_contracts(text),
                "logs": logs,
            }
            if args.require_complete and not is_complete:
                result.update(
                    {
                        "error": "INCOMPLETE_DATA",
                        "error_message": (
                            "[FATAL] API 数据不完整，禁止统计分析。"
                            "请使用 WorkBuddy 内置浏览器完整加载，或显式切换本地 Chrome 备用路径。"
                        ),
                        "action_required": "FALLBACK_TO_WORKBUDDY",
                        "PROHIBITION": (
                            "本次 API 查询未确认完整。严禁基于此不完整数据进行任何统计、计数、"
                            "占比或汇总分析。"
                        ),
                    }
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            result = {
                **base_result,
                "source": "api_failed",
                "fallback_method": "workbuddy",
                "error": str(exc),
                "output_path": None,
                "window_id": None,
                "log_count": None,
                "loaded_count": None,
                "has_more": None,
                "is_complete": None,
                "completeness_ratio": None,
                "services": [],
                "contracts": [],
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if method == "auto" else 1

    text = ""
    window_id = None
    load_more_clicks = 0
    has_more = False
    output_path = args.output

    if args.input_text:
        text = Path(args.input_text).read_text(encoding="utf-8", errors="replace")
    elif method == "local-chrome":
        ensure_ascii(run_query, "--query")
        window_id = ensure_window(build_url(run_query, args.env, time_range))
        time.sleep(args.wait)
        if not check_login(window_id):
            result = {
                "error": "login_required",
                "message": "CLS 登录态已过期，页面跳转到 Argus 登录页。请在 Chrome 中完成登录后重新执行查询。",
                "window_id": window_id,
                "cls_url": cls_url,
                "expanded_url": expanded_url,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        load_more_clicks, has_more = load_more(window_id, args.max_load_more, args.delay)
        if args.require_complete and has_more:
            total_clicks = load_more_clicks
            for cap in [50, 100, 200]:
                if not has_more or total_clicks >= cap:
                    continue
                extra_clicks, has_more = load_more(window_id, cap - total_clicks, args.delay)
                total_clicks += extra_clicks
                load_more_clicks = total_clicks
                if not has_more:
                    break
        text = execute_js(window_id, "document.body.innerText", timeout=60)
        output_path = write_text(args.output, text)

    log_count = parse_log_count(text) if text else 0
    loaded_count = count_loaded_logs(text) if text else 0

    if args.require_complete and has_more:
        result = {
            "error": "INCOMPLETE_DATA",
            "error_message": (
                f"[FATAL] 数据不完整，禁止统计分析。"
                f"已加载 {loaded_count}/{log_count} 条"
                f"（{loaded_count * 100 // max(log_count, 1)}%）。"
                f"请缩小时间范围或拆分查询后重试。"
            ),
            "action_required": "SPLIT_AND_RETRY",
            "suggested_actions": [
                "缩小 --time 范围（如 now-1d,now 拆为 now-12h,now 和 now-1d,now-12h）",
                "添加额外过滤条件（如 AND level:\"ERROR\"）减少结果集",
                f"使用 --max-load-more {min(load_more_clicks * 3, 500)} 增大加载次数",
            ],
            "env": args.env,
            "query": run_query,
            "cls_url": cls_url,
            "expanded_url": expanded_url,
            "output_path": output_path,
            "log_count": log_count,
            "loaded_count": loaded_count,
            "has_more": True,
            "is_complete": False,
            "completeness_ratio": round(loaded_count / max(log_count, 1), 3),
            "PROHIBITION": (
                "本次查询使用了 --require-complete 但数据未能完全加载。"
                "严禁基于此不完整数据进行任何统计、计数、占比或汇总分析。"
            ),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    has_text = bool(text)
    result = {
        **base_result,
        "source": "local-chrome" if method == "local-chrome" else "input-text",
        "fallback_method": None,
        "output_path": output_path if has_text else None,
        "window_id": window_id,
        "load_more_clicks": load_more_clicks,
        "log_count": log_count if has_text else None,
        "loaded_count": loaded_count if has_text else None,
        "has_more": has_more if has_text else None,
        "is_complete": (not has_more) if has_text else None,
        "completeness_ratio": (
            round(loaded_count / max(log_count, 1), 3) if has_text and log_count > 0 else None
        ),
        "services": parse_services(text) if has_text else [],
        "contracts": parse_contracts(text) if has_text else [],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
