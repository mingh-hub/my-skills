#!/usr/bin/env python3
"""Argus/JANUS local Chrome session helper for xh-sso-access."""

import argparse
import http.server
import json
import subprocess
import threading
import time
import urllib.parse


ARGUS_FAVICON = "https://argus.xhdev.xyz/favicon.ico"


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


def ensure_window(url: str = ARGUS_FAVICON) -> str:
    script = f'''
tell application "Google Chrome"
    set targetUrl to "{apple_string(url)}"
    set targetWindow to missing value
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "argus.xhdev.xyz" or u contains "datasight-1300455117.internal.clsconsole.tencent-cloud.com" then
                set targetWindow to w
                exit repeat
            end if
        end repeat
        if targetWindow is not missing value then exit repeat
    end repeat
    if targetWindow is missing value then set targetWindow to make new window
    set URL of active tab of targetWindow to targetUrl
    return id of targetWindow
end tell
'''
    return run_osascript(script, timeout=15)


def execute_js(window_id: str, js: str, timeout: int = 30) -> str:
    script = f'''
tell application "Google Chrome"
    return execute active tab of (first window whose id is {window_id}) javascript "{apple_string(js)}"
end tell
'''
    return run_osascript(script, timeout=timeout)


def verify_cookie(window_id: str) -> bool:
    execute_js(window_id, "window.location.href='https://argus.xhdev.xyz/favicon.ico'", timeout=10)
    time.sleep(1)
    return execute_js(window_id, "document.cookie.includes('argus-token') ? 'true' : 'false'") == "true"


def extract_cookie(window_id: str, port: int) -> str:
    data = {"value": ""}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data["value"] = urllib.parse.unquote(body.decode("utf-8"))
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            return

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        execute_js(window_id, f"window.location.href='{ARGUS_FAVICON}'", timeout=10)
        time.sleep(1)
        execute_js(
            window_id,
            f"var x=new XMLHttpRequest();x.open('POST','http://127.0.0.1:{port}/',false);x.send(encodeURIComponent(document.cookie))",
            timeout=15,
        )
        time.sleep(0.5)
    finally:
        server.shutdown()

    if not data["value"]:
        raise RuntimeError("No cookie data received from local Chrome")
    return data["value"]


def parse_cookies(raw: str) -> dict[str, str]:
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            cookies[key] = value
    return cookies


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local Chrome Argus session.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_window = sub.add_parser("ensure-window")
    p_window.add_argument("--url", default=ARGUS_FAVICON)

    p_verify = sub.add_parser("verify-cookie")
    p_verify.add_argument("--window-id")

    p_extract = sub.add_parser("extract-cookie")
    p_extract.add_argument("--window-id")
    p_extract.add_argument("--port", type=int, default=9877)

    args = parser.parse_args()
    if args.cmd == "ensure-window":
        window_id = ensure_window(args.url)
        print(json.dumps({"window_id": window_id, "url": args.url}, ensure_ascii=False))
    elif args.cmd == "verify-cookie":
        window_id = args.window_id or ensure_window()
        print(json.dumps({"window_id": window_id, "has_argus_token": verify_cookie(window_id)}, ensure_ascii=False))
    elif args.cmd == "extract-cookie":
        window_id = args.window_id or ensure_window()
        raw = extract_cookie(window_id, args.port)
        cookies = parse_cookies(raw)
        print(json.dumps({
            "window_id": window_id,
            "cookie_names": sorted(cookies),
            "has_argus_token": "argus-token" in cookies,
            "raw_cookie": raw,
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
