# AppleScript Cookie Extraction from Local Chrome

## When To Read

Read when Argus cookie extraction fails or AppleScript appears to truncate cookie/JWT values. Routine extraction should use `tools/argus_session.py extract-cookie`.

## Contents

- Problem
- Working XHR approach
- Broken clipboard/keychain approaches
- Short-cookie fallback

## Problem

AppleScript's `execute t javascript` truncates JavaScript return values by inserting literal `...` into strings. Even short strings (500 chars) get corrupted. This makes JWT token extraction unreliable.

## Solution: Clipboard Bypass

### Step 1: Write cookie to clipboard via JavaScript

```applescript
osascript -e '
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t contains "argus.xhdev.xyz" then
                execute t javascript "
                    (async () => {
                        const c = document.cookie;
                        const blob = new Blob([c], {type: \"text/plain\"});
                        const item = new ClipboardItem({\"text/plain\": blob});
                        await navigator.clipboard.write([item]);
                    })();
                "
                delay 1
            end if
        end repeat
    end repeat
end tell'
```

The `navigator.clipboard.write()` method accepts ClipboardItem objects (requires secure context — satisfied in Chrome). The Blob wrapping ensures the full string is copied without truncation.

### Step 2: Read from system clipboard

```bash
pbpaste > /tmp/cookie.txt
```

### Step 3: Parse with Python

```python
cookie_str = open('/tmp/cookie.txt').read().strip()
cookies = {}
for part in cookie_str.split('; '):
    if '=' in part:
        k, v = part.split('=', 1)
        cookies[k] = v
print(cookies['argus-token'])  # Full, untruncated JWT
```

## Verification

Always verify extraction with:

```bash
xxd /tmp/cookie.txt | grep '2e2e2e'
```

If grep finds matches (the hex for `...`), the extraction was corrupted. No matches = clean extraction.

## 2026-05-13 Update: Verified Barriers to Clipboard Bypass

All the clipboard-based approaches below were re-tested in this session and remain broken in modern Chrome (v148):

| Approach | Result | Root Cause |
|----------|--------|------------|
| `navigator.clipboard.write([ClipboardItem])` | ❌ `Document is not focused` | JS clipboard API requires active user focus on the specific document, not just the app |
| `navigator.clipboard.writeText(text)` | ❌ Same error | Same focus requirement |
| `document.execCommand('copy')` | ❌ Returns `false` | Deprecated API blocked by modern Chrome without user gesture |
| `document.title` → read via AppleScript | ❌ Reverted by SPA | Argus CLS (React/Vue) overwrites `document.title` back to original within seconds |
| `do shell script` within AppleScript | ❌ Truncated | AppleScript string variable is truncated before being passed to shell |
| `browser_cookie3` Python library | ❌ Times out | Underlying `pycryptodomex` hangs on encrypted cookie DB with Chrome running |
| `security find-generic-password` | ❌ Times out | Shows macOS keychain dialog that blocks terminal until user clicks "Allow" |
| Direct SQLite `encrypted_value` decryption | ❌ Blocked | `v10` format (AES-256-GCM) requires key stored in macOS Keychain — same dialog problem |

## What DOES Work for Multi-Cookie Extraction

Extract short-valued cookies (< 255 chars) one at a time via `execute t javascript`:

```python
import subprocess

script_template = '''
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t) contains "argus.xhdev.xyz" and (URL of t) contains "clsDatasight" then
                return execute t javascript "document.cookie.split('; ').find(c => c.startsWith('%s')).split('=')[1]"
            end if
        end repeat
    end repeat
    return "not found"
end tell
'''

for cookie_name in ["user_name", "isAdmin", "TGC-prod"]:
    script = script_template % cookie_name
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    print(f"{cookie_name} = {result.stdout.strip()}")
```

This returns complete values for cookies under ~255 chars. For the `argus-token` JWT (492 chars), it will still be truncated — the clipboard bypass is the only path, and it's currently blocked by document focus requirements.
