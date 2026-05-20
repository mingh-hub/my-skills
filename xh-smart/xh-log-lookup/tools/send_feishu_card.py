#!/usr/bin/env python3
"""
飞书互动卡片发送工具 — xh-log-lookup 专用

用法:
  # 健康检查卡片（汇总表格）
  python3 send_feishu_card.py \
    --title "✅ 下单正常 · 05-17 00:00~23:59" \
    --color green \
    --cls-url "https://datasight-xxx/cls/search?..." \
    --cls-url-expanded "https://datasight-xxx/cls/search?...&time=..." \
    --data '{
      "summary_fields": [
        {"label": "下单请求总数", "value": "20 笔"},
        {"label": "✅ 成功", "value": "17 笔 (¥148,800)"},
        {"label": "⚠️ 业务异常", "value": "2 笔"},
        {"label": "❌ 系统错误", "value": "0 笔"}
      ],
      "analysis": "业务异常走重试后全部成功，系统健康",
      "log_count": 20
    }'

  # 链路追踪卡片（调用链）
  python3 send_feishu_card.py \
    --title "❌ 下单出现系统错误 · 05-17 10:00~10:30" \
    --color red \
    --cls-url "https://datasight-xxx/cls/search?..." \
    --data '{
      "call_chain": [
        {"time":"10:28:14","service":"order","level":"INFO","content":"[借款下单]下单请求为:{...}"},
        {"time":"10:28:15","service":"order","level":"ERROR","content":"[借款下单]请求出现业务异常:xxx"}
      ],
      "analysis": "订单在反欺诈环节被拒绝，错误码: ANTI_FRAUD_REJECT",
      "log_count": 2
    }'

  # 从 CLS 原始文本自动解析
  python3 send_feishu_card.py \
    --title "📋 日志查询结果 · 05-17 09:00~10:00" \
    --color blue \
    --raw-text "$(cat /tmp/cls_output.txt)" \
    --data '{"analysis": "自动解析的查询结果"}'

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

FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

LEVEL_ICON = {"INFO": "🟢", "WARN": "🟡", "WARNING": "🟡", "ERROR": "🔴"}
COLOR_MAP = {"red": "red", "yellow": "yellow", "green": "green", "blue": "blue"}


def load_env():
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def get_token():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise ValueError("FEISHU_APP_ID / FEISHU_APP_SECRET not set")

    try:
        import requests
        r = requests.post(FEISHU_TOKEN_URL,
                          json={"app_id": app_id, "app_secret": app_secret},
                          timeout=5)
        return r.json()["tenant_access_token"]
    except Exception:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", "-X", "POST", FEISHU_TOKEN_URL,
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"app_id": app_id, "app_secret": app_secret})],
            capture_output=True, text=True
        )
        return json.loads(result.stdout)["tenant_access_token"]


def parse_cls_raw_text(raw_text):
    """从 CLS 页面原始文本提取结构化数据，自动构建 call_chain"""
    count_match = re.search(r'日志条数\s+([\d,]+)', raw_text)
    total_count = int(count_match.group(1).replace(',', '')) if count_match else 0

    rows = []
    pattern = r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+).*?message:(.*?)(?=\n\t|\Z)'
    for m in re.finditer(pattern, raw_text, re.DOTALL):
        timestamp = m.group(1).strip()
        msg = m.group(2).strip()[:300]
        level = "ERROR" if "ERROR" in msg or "异常" in msg or "错误" in msg else \
                "WARN" if "WARN" in msg or "拦截" in msg else "INFO"
        svc_match = re.search(r'serviceName[=:]\s*"?(\w+)"?', raw_text)
        service = svc_match.group(1) if svc_match else "unknown"
        rows.append({
            "time": timestamp.split()[-1] if ' ' in timestamp else timestamp,
            "service": service,
            "level": level,
            "content": msg
        })

    return {"call_chain": rows[:20], "log_count": total_count or len(rows)}


def build_card(title, color, cls_url, cls_url_expanded, data):
    elements = []

    summary_fields = data.get("summary_fields", [])
    if summary_fields:
        fields = []
        for item in summary_fields:
            fields.append({
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**{item['label']}**"}
            })
            fields.append({
                "is_short": True,
                "text": {"tag": "lark_md", "content": item["value"]}
            })
        elements.append({"tag": "div", "fields": fields})
        elements.append({"tag": "hr"})

    call_chain = data.get("call_chain", [])
    log_count = data.get("log_count", len(call_chain))

    if call_chain:
        display_items = call_chain[:10] if log_count > 20 else call_chain
        chain_lines = []
        for item in display_items:
            icon = LEVEL_ICON.get(item.get("level", "INFO").upper(), "🟢")
            t = item.get("time", "")
            svc = item.get("service", "")
            content = item.get("content", "")
            chain_lines.append(f"{icon} `{t}` **{svc}** {content}")
        if log_count > 20:
            chain_lines.append(f"\n... 共 **{log_count}** 条日志，仅展示最近 10 条")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(chain_lines)}})
    elif log_count == 0 and not summary_fields:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**无匹配日志**\n\n可能原因：查询时间范围不对、serviceName 不匹配、或该请求未产生日志。"}
        })

    analysis = data.get("analysis", "")
    if analysis:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**📋 分析结论:**\n{analysis}"}
        })

    actions = []
    if cls_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔗 跳转链接"},
            "type": "primary",
            "url": cls_url
        })
    if cls_url_expanded:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "⏱ 扩大查询范围"},
            "type": "default",
            "url": cls_url_expanded
        })
    if actions:
        elements.append({"tag": "hr"})
        elements.append({"tag": "action", "actions": actions})

    note_text = f"🕐 共查询到 {log_count} 条日志 | {time.strftime('%H:%M')}"
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": note_text}]
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": COLOR_MAP.get(color, "blue")
        },
        "elements": elements
    }
    return card


def send_card(chat_id, card):
    token = get_token()
    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False)
    }

    try:
        import requests
        r = requests.post(
            FEISHU_MSG_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15
        )
        result = r.json()
    except Exception:
        tmp_file = "/tmp/feishu_card_payload.json"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "15", "-X", "POST", FEISHU_MSG_URL,
             "-H", f"Authorization: Bearer {token}",
             "-H", "Content-Type: application/json",
             "-d", f"@{tmp_file}"],
            capture_output=True, text=True
        )
        result = json.loads(proc.stdout) if proc.stdout else {"code": -1, "msg": proc.stderr}

    if result.get("code") == 0:
        msg_id = result.get("data", {}).get("message_id", "unknown")
        print(json.dumps({"status": "sent", "message_id": msg_id}, ensure_ascii=False))
    else:
        print(json.dumps({"status": "error", "detail": result}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="发送飞书互动卡片")
    parser.add_argument("--chat", default=None, help="飞书群 chat_id")
    parser.add_argument("--title", required=True,
                        help="卡片标题 (格式: [emoji] 场景简述 · 时间范围)")
    parser.add_argument("--color", default="blue",
                        choices=["red", "yellow", "green", "blue"],
                        help="red=ERROR/阻断, yellow=WARN/拦截, green=全部正常, blue=常规")
    parser.add_argument("--cls-url", default=None,
                        help="CLS 查询 URL (🔗 跳转链接按钮)")
    parser.add_argument("--cls-url-expanded", default=None,
                        help="CLS 扩大时间范围 URL (⏱ 扩大查询范围按钮)")
    parser.add_argument("--raw-text", default=None,
                        help="CLS 原始文本，自动解析为 call_chain（替代手动构建 --data 中的 call_chain）")
    parser.add_argument("--data", required=True,
                        help="JSON: {summary_fields, call_chain, analysis, log_count}")

    args = parser.parse_args()

    load_env()

    chat_id = args.chat or os.environ.get("FEISHU_HOME_CHANNEL")
    if not chat_id:
        print("Error: --chat or FEISHU_HOME_CHANNEL required", file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.data)

    if args.raw_text and "call_chain" not in data:
        parsed = parse_cls_raw_text(args.raw_text)
        data.setdefault("call_chain", parsed["call_chain"])
        data.setdefault("log_count", parsed["log_count"])

    card = build_card(args.title, args.color, args.cls_url, args.cls_url_expanded, data)
    send_card(chat_id, card)


if __name__ == "__main__":
    main()
