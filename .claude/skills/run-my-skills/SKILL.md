---
name: run-my-skills
description: Run, test, and verify my-skills Python tools. Use when asked to smoke-test the tools, verify imports work, check cls_query URL building, or validate skill query anchors.
---

A collection of Hermes AI agent skills (not a traditional app). "Running" it means verifying the Python CLI tools under `xh-smart/*/tools/` are functional. Drive it via `.claude/skills/run-my-skills/smoke.sh`.

All paths below are relative to the repo root.

## Prerequisites

- Python 3.10+
- macOS (for full Chrome/AppleScript automation; smoke tests run without Chrome)
- Optional: `~/.hermes/.env` with `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_HOME_CHANNEL` for Feishu card sending

## Run (agent path)

```bash
bash .claude/skills/run-my-skills/smoke.sh
```

Runs all tools in safe mode (no Chrome, no network calls). Output is a pass/fail summary.

## Direct invocation

### CLS query — URL build only (no browser)

```bash
python3 xh-smart/xh-log-lookup/tools/cls_query.py \
  --env prod \
  --query 'serviceName:"order" AND message:"20161002000002677537"' \
  --no-browser
```

Returns JSON with `cls_url`, `expanded_url`, `topic_id`. No side effects.

### CLS query — open Chrome and extract page text

```bash
python3 xh-smart/xh-log-lookup/tools/cls_query.py \
  --env prod \
  --query 'traceId:"37426d42fdc699d1"' \
  --output /tmp/cls_output.txt
```

Opens a dedicated Chrome window via AppleScript, loads all pages, extracts `document.body.innerText`. Requires macOS + Chrome + CLS login session.

### Validate query anchors

```bash
python3 xh-smart/xh-log-lookup/tools/validate_query_anchors.py \
  --skill xh-smart/xh-log-lookup/xh-log-lookup-order/SKILL.md \
  --source-root /Users/user/mingh/workspace/order \
  --json
```

Checks that method entries, serviceNames, and message anchors in SKILL.md tables still match source code. Reports OK/WARN/skip per row.

### Send Feishu card

```bash
python3 xh-smart/xh-log-lookup/tools/send_feishu_card.py \
  --title "✅ 测试 · 05-20" \
  --color green \
  --data '{"summary_fields":[{"label":"状态","value":"正常"}],"analysis":"smoke test","log_count":0}'
```

Requires `FEISHU_APP_ID` + `FEISHU_APP_SECRET` in env or `~/.hermes/.env`.

### Argus session

```bash
python3 xh-smart/xh-sso-access/tools/argus_session.py ensure-window
python3 xh-smart/xh-sso-access/tools/argus_session.py verify-cookie
python3 xh-smart/xh-sso-access/tools/argus_session.py extract-cookie
```

Manages Chrome Argus SSO sessions. Requires macOS + Chrome.

## Gotchas

- **All browser automation requires macOS + Google Chrome.** AppleScript (`osascript`) is the only supported automation path. The smoke test avoids this by using `--no-browser` and `--help` flags.
- **`cls_query.py` cannot carry Chinese in `queryBase64`.** Chinese queries need the contenteditable injection workflow documented in `xh-smart/xh-log-lookup/references/cls-react-contenteditable-injection.md`.
- **Feishu tools need credentials.** Without `~/.hermes/.env` containing `FEISHU_APP_ID` and `FEISHU_APP_SECRET`, `send_feishu_card.py` will fail at runtime (but `--help` works).
- **`validate_query_anchors.py` reports "skip" when source roots are missing.** This is expected — it means it can't verify anchors against code, not that the skill is broken.
