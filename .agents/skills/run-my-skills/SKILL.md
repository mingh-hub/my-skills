---
name: run-my-skills
description: Run, test, and verify my-skills Python tools. Use when asked to smoke-test the tools, verify imports work, check cls_query URL building, or validate skill query anchors.
---

A collection of Hermes AI agent skills (not a traditional app). "Running" it means verifying the public CLIs under `xh-smart/xh-log-lookup/scripts/` plus the remaining `xh-smart/*/tools/` utilities. Drive it via `.agents/skills/run-my-skills/smoke.sh`.

All paths below are relative to the repo root.

## Prerequisites

- Python 3.10+
- macOS (for full Chrome/AppleScript automation; smoke tests run without Chrome)
- Optional: `~/.hermes/.env` with `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_HOME_CHANNEL` for Feishu card sending

## Run (agent path)

```bash
bash .agents/skills/run-my-skills/smoke.sh
```

Runs six `xh-log-lookup` CLI help checks, a shared-config import, a CLS URL-only check, advisory anchor validation, the complete unit suite, and agent YAML checks. It does not open Chrome or call CLS/Feishu network APIs.

## Direct invocation

### CLS query — URL build only (no browser)

```bash
python3 xh-smart/xh-log-lookup/scripts/cls_log_query.py \
  --env prod \
  --query 'serviceName:"order" AND message:"20161002000002677537"' \
  --method workbuddy
```

Returns JSON with `cls_url`, `expanded_url`, `topic_id`. No side effects.

### CLS query — open Chrome and extract page text

```bash
python3 xh-smart/xh-log-lookup/scripts/cls_log_query.py \
  --env prod \
  --query 'traceId:"37426d42fdc699d1"' \
  --method local-chrome --use-local-chrome \
  --output /tmp/cls_output.txt
```

Opens a dedicated Chrome window via AppleScript, loads all pages, extracts `document.body.innerText`. Requires macOS + Chrome + CLS login session.

### Validate query anchors

```bash
python3 xh-smart/xh-log-lookup/scripts/validate_query_anchors.py \
  --skill xh-smart/xh-log-lookup/references/modules/order.md \
  --source-root /Users/user/mingh/workspace/order \
  --json
```

Checks that method entries, serviceNames, and message anchors in SKILL.md tables still match source code. Missing source roots are reported as `unverified`; default mode is advisory, while `--strict` returns nonzero for warnings or unverified rows.

### Send Feishu card

```bash
python3 xh-smart/xh-log-lookup/scripts/send_feishu_card.py \
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

- **All browser automation requires macOS + Google Chrome.** AppleScript (`osascript`) is the only supported automation path. The smoke test avoids this by using `--method workbuddy` and `--help` flags.
- **Chinese queries are supported by the API path.** Only the browser fallback URL has `queryBase64` constraints; use `xh-smart/xh-log-lookup/references/common/cls-react-contenteditable-injection.md` when an ASCII-safe fallback query cannot preserve the intended condition.
- **Feishu tools need credentials.** Without `~/.hermes/.env` containing `FEISHU_APP_ID` and `FEISHU_APP_SECRET`, `send_feishu_card.py` will fail at runtime (but `--help` works).
- **`validate_query_anchors.py` reports `unverified` when source roots are missing.** This is advisory by default and means the anchors were not checked, not that they are valid or invalid.
