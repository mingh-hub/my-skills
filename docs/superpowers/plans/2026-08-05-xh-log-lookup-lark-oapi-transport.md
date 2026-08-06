# xh-log-lookup lark_oapi Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `lark_oapi` transport for card delivery, ID conversion, and message detail lookup while preserving the current request-scoped routing and lark-cli security fixes.

**Architecture:** Keep `send_feishu_card.py` as the public CLI and add lazy SDK/client helpers inside it. Each OAPI operation returns a normal value or a failure sentinel, allowing the existing lark-cli path to remain the single fallback. Invoke Hermes Python relaunch only from the script entry point so importing the module has no process-level side effects.

**Tech Stack:** Python 3.9/3.11, `lark_oapi` IM v1 and Contact v3 SDK, `unittest`, `unittest.mock`.

---

### Task 1: Optional SDK Runtime And Credentials

**Files:**
- Modify: `xh-smart/xh-log-lookup/scripts/send_feishu_card.py:28-90`
- Create: `xh-smart/xh-log-lookup/tests/test_send_feishu_card_oapi.py`

- [ ] **Step 1: Write failing runtime tests**

Create a test module that loads `send_feishu_card.py` with `importlib.util`, then add tests equivalent to:

```python
def test_load_env_credentials_prefers_process_environment(self):
    with mock.patch.dict(os.environ, {
        "FEISHU_APP_ID": "env-id",
        "FEISHU_APP_SECRET": "env-secret",
    }, clear=True), mock.patch("builtins.open") as opened:
        self.assertEqual(module._load_env_credentials(), ("env-id", "env-secret"))
    opened.assert_not_called()

def test_load_env_credentials_falls_back_to_hermes_env_file(self):
    env_text = "FEISHU_APP_ID=file-id\nFEISHU_APP_SECRET=file-secret\n"
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
        "builtins.open", mock.mock_open(read_data=env_text)
    ):
        self.assertEqual(module._load_env_credentials(), ("file-id", "file-secret"))

def test_relaunch_uses_hermes_python_only_when_sdk_is_missing(self):
    with mock.patch.object(module, "_import_lark_oapi", return_value=None), \
         mock.patch.object(module.os.path, "isfile", return_value=True), \
         mock.patch.object(module.os, "access", return_value=True), \
         mock.patch.object(module.os, "execv") as execv:
        module._maybe_relaunch_with_hermes_python()
    candidate = module.HERMES_PYTHON_CANDIDATES[0]
    execv.assert_called_once_with(candidate, [candidate] + sys.argv)
```

- [ ] **Step 2: Run runtime tests and verify RED**

Run:

```bash
cd xh-smart/xh-log-lookup
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_send_feishu_card_oapi.OapiRuntimeTest
```

Expected: errors because `_load_env_credentials`, `_import_lark_oapi`, `HERMES_PYTHON_CANDIDATES`, and `_maybe_relaunch_with_hermes_python` do not exist.

- [ ] **Step 3: Implement lazy runtime helpers**

Add `import importlib` and these responsibilities to `send_feishu_card.py`:

```python
HERMES_ENV_PATH = os.path.expanduser("~/.hermes/.env")
HERMES_PYTHON_CANDIDATES = (
    os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python"),
    os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python3"),
)
_LARK_OAPI_MODULE = None
_LARK_OAPI_IMPORT_FAILED = False
_LARK_OAPI_CLIENT = None
_LARK_OAPI_CLIENT_FAILED = False

def _import_lark_oapi():
    global _LARK_OAPI_MODULE, _LARK_OAPI_IMPORT_FAILED
    if _LARK_OAPI_MODULE is not None:
        return _LARK_OAPI_MODULE
    if _LARK_OAPI_IMPORT_FAILED:
        return None
    try:
        _LARK_OAPI_MODULE = importlib.import_module("lark_oapi")
    except (ImportError, SyntaxError):
        _LARK_OAPI_IMPORT_FAILED = True
        return None
    return _LARK_OAPI_MODULE

def _maybe_relaunch_with_hermes_python():
    if _import_lark_oapi() is not None:
        return
    current = os.path.realpath(sys.executable)
    for candidate in HERMES_PYTHON_CANDIDATES:
        if (os.path.isfile(candidate) and os.access(candidate, os.X_OK)
                and os.path.realpath(candidate) != current):
            os.execv(candidate, [candidate] + sys.argv)

def _load_env_credentials():
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
```

Implement `_lark_oapi_client()` using the imported module's `Client.builder()`, credentials above, `LogLevel.ERROR`, and the cached failure flags. Call `_maybe_relaunch_with_hermes_python()` only inside the `if __name__ == "__main__"` block immediately before `main()`.

- [ ] **Step 4: Run runtime tests and verify GREEN**

Run the command from Step 2. Expected: `Ran 3 tests ... OK`.

### Task 2: OAPI ID Conversion And Message Detail Lookup

**Files:**
- Modify: `xh-smart/xh-log-lookup/scripts/send_feishu_card.py:147-175`
- Modify: `xh-smart/xh-log-lookup/scripts/send_feishu_card.py:716-780`
- Modify: `xh-smart/xh-log-lookup/tests/test_send_feishu_card_oapi.py`

- [ ] **Step 1: Add failing conversion and detail tests**

Use fake fluent request builders and fake clients. Cover these assertions:

```python
def test_to_open_id_uses_oapi_before_cli(self):
    response = SimpleNamespace(
        success=lambda: True,
        data=SimpleNamespace(user=SimpleNamespace(open_id="ou_oapi")),
    )
    client = SimpleNamespace(
        contact=SimpleNamespace(v3=SimpleNamespace(
            user=SimpleNamespace(get=mock.Mock(return_value=response))
        ))
    )
    with mock.patch.object(module, "_lark_oapi_client", return_value=client), \
         mock.patch.object(module, "_oapi_get_user_request", return_value=object()), \
         mock.patch.object(module, "_lark_run") as cli:
        self.assertEqual(module._to_open_id("tenant-user"), "ou_oapi")
    cli.assert_not_called()

def test_to_open_id_falls_back_to_shell_safe_cli(self):
    uid = "user'; touch /tmp/injected; '"
    cli_response = SimpleNamespace(
        stdout='{"ok": true, "data": {"user": {"open_id": "ou_cli"}}}',
        stderr="",
    )
    with mock.patch.object(module, "_lark_oapi_client", return_value=None), \
         mock.patch.object(module, "_lark_run", return_value=cli_response) as cli:
        self.assertEqual(module._to_open_id(uid), "ou_cli")
    self.assertIn(shlex.quote(uid), cli.call_args.args[0])

def test_fetch_message_detail_uses_oapi_mapping(self):
    item = SimpleNamespace(
        message_id="om_1", chat_id="oc_1", chat_type="group",
        create_time="100", update_time="101",
        sender=SimpleNamespace(id="ou_sender"),
    )
    response = SimpleNamespace(
        success=lambda: True,
        data=SimpleNamespace(items=[item]),
    )
    client = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(
        message=SimpleNamespace(get=mock.Mock(return_value=response))
    )))
    with mock.patch.object(module, "_lark_oapi_client", return_value=client), \
         mock.patch.object(module, "_oapi_get_message_request", return_value=object()), \
         mock.patch.object(module, "_lark_run") as cli:
        message, error = module._fetch_message_detail("om_1")
    self.assertEqual(error, "")
    self.assertEqual(message["sender"]["id"], "ou_sender")
    cli.assert_not_called()
```

Add one more detail test where OAPI raises and the existing lark-cli `messages-mget` response is returned.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_send_feishu_card_oapi.OapiLookupTest
```

Expected: errors because `_oapi_get_user_request` and `_oapi_get_message_request` are absent and current functions do not call OAPI.

- [ ] **Step 3: Implement request factories and OAPI-first lookup**

Add request helpers that import generated SDK classes only when invoked:

```python
def _oapi_get_user_request(uid, uid_type):
    from lark_oapi.api.contact.v3 import GetUserRequest
    return GetUserRequest.builder().user_id(uid).user_id_type(uid_type).build()

def _oapi_get_message_request(message_id):
    from lark_oapi.api.im.v1 import GetMessageRequest
    return GetMessageRequest.builder().message_id(message_id).build()
```

Update `_to_open_id` to call `client.contact.v3.user.get(...)` before its current `_lark_run` block. Return only a non-empty `open_id`; catch OAPI exceptions and continue to the existing shell-safe CLI command unchanged.

Update `_fetch_message_detail` to call `client.im.v1.message.get(...)`, map the first item to the current message dictionary, include `transport: lark_oapi` in audit, and continue to the existing `messages-mget` block on any unavailable/failed/empty response.

Only accept the OAPI detail when all routing-required fields are present: a supported `chat_type`, non-empty `chat_id`, sender ID and body content, plus a present mentions field for group messages. The installed SDK `Message` model does not expose `chat_type`, so its normal response must continue to `messages-mget` rather than suppressing the CLI fallback.

- [ ] **Step 4: Run lookup tests and existing security tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_send_feishu_card_oapi.OapiLookupTest \
  tests.test_send_feishu_card_target.DirectSendTest
```

Expected: all lookup tests and existing direct-send shell-quoting tests pass.

### Task 3: OAPI-First Card Delivery

**Files:**
- Modify: `xh-smart/xh-log-lookup/scripts/send_feishu_card.py:1598-1685`
- Modify: `xh-smart/xh-log-lookup/tests/test_send_feishu_card_oapi.py`
- Modify: `xh-smart/xh-log-lookup/tests/test_send_feishu_card_target.py:394-550`

- [ ] **Step 1: Add failing card delivery tests**

Add fake create-message request coverage:

```python
def test_send_card_via_oapi_uses_open_id_for_user(self):
    captured = {}
    request = object()
    response = SimpleNamespace(
        success=lambda: True,
        data=SimpleNamespace(message_id="om_sent"),
    )
    client = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(
        message=SimpleNamespace(create=mock.Mock(return_value=response))
    )))
    with mock.patch.object(module, "_lark_oapi_client", return_value=client), \
         mock.patch.object(
             module, "_oapi_create_message_request",
             side_effect=lambda card, receive_id, receive_id_type: captured.update(
                 receive_id=receive_id, receive_id_type=receive_id_type
             ) or request,
         ):
        result = module._send_card_via_oapi({}, "user", None, "ou_target")
    self.assertEqual(result, (True, "om_sent"))
    self.assertEqual(captured, {
        "receive_id": "ou_target", "receive_id_type": "open_id"
    })
```

Add a corresponding chat test expecting `chat_id`, a `send_card` success test asserting `transport=lark_oapi` and no CLI invocation, and an OAPI failure test asserting the current quoted lark-cli command is used.

Patch `_send_card_via_oapi` to return `(False, "unavailable")` in existing `DirectSendTest` methods that specifically inspect lark-cli command strings. This guarantees those tests never contact a real SDK client under any interpreter.

- [ ] **Step 2: Run card tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_send_feishu_card_oapi.OapiSendTest \
  tests.test_send_feishu_card_target.DirectSendTest
```

Expected: new OAPI tests fail because `_send_card_via_oapi` and `_oapi_create_message_request` do not exist; existing CLI tests remain isolated.

- [ ] **Step 3: Implement OAPI request creation and send fallback**

Add:

```python
def _oapi_create_message_request(card, receive_id, receive_id_type):
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

def _send_card_via_oapi(card, target_type, chat_id, user_id):
    client = _lark_oapi_client()
    if client is None:
        return False, "lark_oapi unavailable"
    receive_id = user_id if target_type == "user" and user_id else chat_id
    receive_id_type = "open_id" if target_type == "user" and user_id else "chat_id"
    try:
        request = _oapi_create_message_request(card, receive_id, receive_id_type)
        response = client.im.v1.message.create(request)
        if response.success():
            message_id = getattr(response.data, "message_id", None)
            if not message_id:
                return False, "missing message_id"
            return True, message_id
        return False, f"code={response.code} msg={response.msg}"
    except Exception as exc:
        return False, str(exc)
```

Call `_send_card_via_oapi` in `send_card` after card-size handling and before CLI command construction. On success, preserve current `quiet_success`, metadata, and audit behavior while adding `transport=lark_oapi`; on failure, continue into the unchanged `_quote_lark_id` CLI path.

- [ ] **Step 4: Run card tests and verify GREEN**

Run the command from Step 2. Expected: all OAPI send and DirectSend tests pass with no network access.

### Task 4: Skill Documentation, Development Log, And Verification

**Files:**
- Modify: `xh-smart/xh-log-lookup/SKILL.md:218-280`
- Modify: `xh-smart/xh-notes/skill-build-dev-notes.md:5`
- Verify: `xh-smart/xh-log-lookup/scripts/resolve_hermes_session.py`

- [ ] **Step 1: Update skill instructions**

Document that card delivery, ID conversion, and message detail lookup prefer `lark_oapi`; `messages-search` remains lark-cli-only; SDK/credentials/request failures fall back to lark-cli; CLI entry may relaunch under Hermes Python; OAPI success records `transport=lark_oapi` unless `--quiet-success` suppresses stdout. Keep the current direct-target templates and helper fallback rules unchanged.

- [ ] **Step 2: Update the existing 2026-08-05 development-log entry**

Append the OAPI-first transport, interpreter behavior, preserved safety constraints, fake-client coverage, and final test counts to the existing row rather than creating a duplicate date row.

- [ ] **Step 3: Run full verification**

Run:

```bash
cd xh-smart/xh-log-lookup
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPYCACHEPREFIX=/private/tmp/xh-log-lookup-pycache python3 -m py_compile \
  scripts/send_feishu_card.py scripts/resolve_hermes_session.py
cd ../../..
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/run-my-skills/smoke.sh
git diff --check
```

Expected: all Python tests pass, smoke reports `3 passed, 0 failed` with optional `cryptography` skipped, compilation exits 0, and `git diff --check` emits no output.

- [ ] **Step 4: Validate skill structure and safety invariants**

Run `quick_validate.py` if `PyYAML` is installed; otherwise parse the frontmatter with Ruby YAML as in the prior change. Inspect the final diff to confirm `resolve_hermes_session.py` remains request-scoped, `_quote_lark_id` remains in every lark-cli direct-ID path, `getattr` compatibility remains, and conversion failure still clears the mention target.

- [ ] **Step 5: Request independent code review**

Ask the existing reviewer to inspect the working-tree diff for network side effects, secret exposure, fallback correctness, request-scoped routing, shell injection, and missing OAPI tests. Resolve every Critical and Important finding before reporting completion.

No commit or push is included because the current request authorizes implementation but does not explicitly request repository history changes.
