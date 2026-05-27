#!/usr/bin/env python3
"""CLS query helper for xh-log-lookup.

Builds CLS URLs by default. It only opens the user's local Chrome when
--use-local-chrome is explicitly provided.
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CLS URLs; optionally execute via local Chrome.")
    parser.add_argument("--query", help="ASCII CLS query used for execution.")
    parser.add_argument("--close", action="store_true", help="Close CLS/Argus windows and exit.")
    parser.add_argument("--url-query", help="ASCII query used in jump URLs; defaults to --query.")
    parser.add_argument("--env", choices=sorted(TOPICS), default="prod")
    parser.add_argument("--time", dest="time_range")
    parser.add_argument("--expanded-time")
    parser.add_argument("--output", default="/tmp/cls_output.txt")
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
        help="Only build URLs; retained for compatibility and now the default.",
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
    url_query = args.url_query or args.query
    time_range = args.time_range or TOPICS[args.env]["default_time"]
    expanded_time = args.expanded_time or TOPICS[args.env]["expanded_time"]

    cls_url = build_url(url_query, args.env, time_range)
    expanded_url = build_url(url_query, args.env, expanded_time)

    if args.require_complete and not args.use_local_chrome and not args.input_text:
        result = {
            "error": "LOCAL_CHROME_OPT_IN_REQUIRED",
            "message": (
                "--require-complete needs extracted CLS text. Use WorkBuddy browser "
                "for the default path, or add --use-local-chrome only after "
                "explicitly switching to the local Chrome backup path."
            ),
            "cls_url": cls_url,
            "expanded_url": expanded_url,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    text = ""
    window_id = None
    load_more_clicks = 0
    has_more = False
    output_path = args.output

    if args.input_text:
        text = Path(args.input_text).read_text(encoding="utf-8", errors="replace")
    elif args.use_local_chrome and not args.no_browser:
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
        "env": args.env,
        "topic_id": TOPICS[args.env]["topic_id"],
        "topic_name": TOPICS[args.env]["name"],
        "query": run_query,
        "url_query": url_query,
        "time": time_range,
        "expanded_time": expanded_time,
        "cls_url": cls_url,
        "expanded_url": expanded_url,
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
