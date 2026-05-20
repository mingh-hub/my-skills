# Chinese Characters in CLS queryBase64 — Experiment Results

**Date:** 2026-05-17
**CLS Platform URL:** `https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/cls/search`
**Test Query:** `serviceName:"order" AND message:"[借款下单]下单请求为"`

## Problem

CLS uses raw JavaScript `atob()` to decode the `queryBase64` URL parameter. `atob()` only supports Latin1 (single-byte characters). Chinese UTF-8 multi-byte characters are garbled by `atob()`, producing invalid text in the search box.

## Experiments

### Encoding

| # | Approach | Encoding | CLS Result | Reason |
|---|----------|----------|------------|--------|
| 4 | JS trick: `btoa(unescape(encodeURIComponent()))` | Same as UTF-8 (identical b64 output) | ❌ Same as UTF-8 | `unescape(encodeURIComponent())` = UTF-8 bytes decoded as Latin1; functionally identical to approach 1 |
| 1 | UTF-8 base64 | `base64(query.encode('utf-8'))` | ❌ Search box blank | atob produces Latin1 garbage → page discards it |
| 2 | `\uXXXX` escape | `\\u005B\\u501F...` (pure ASCII) | ❌ Shows literal `\u005B\u501F...` | CLS does NOT interpret JS escape sequences |
| 3 | URL-encoded `%XX` | `%5B%E5%80%9F...` | ❌ Shows literal `%5B%E5%80%9F...` | CLS does NOT URL-decode after atob |

## Technical Details

### CLS Page Architecture

- Built on **Next.js** (confirmed via `window.__NEXT_DATA__`)
- `queryBase64` parameter is handled **client-side** in the React app, not SSR
- No alternative URL parameters exist (checked `query`, `search`, `searchQuery`, etc.)
- Session/local storage contain search history but cannot inject queries

### How atob Garbles Chinese

```
# Chinese "[借款下单]" in UTF-8:
E5 80 9F E6 AC BE E4 B8 8B E5 8D 95  (bytes)
→ atob() treats each byte as Latin1:
  å (0xE5) € (0x80) Ÿ (0x9F) æ (0xE6) ¬ (0xAC)...
```

### Workaround (Confirmed Working)

Pass **only the ASCII prefix** via `queryBase64`:

```python
import base64
placeholder = 'serviceName:"order"'
b64 = base64.b64encode(placeholder.encode()).decode()
# b64 = "c2VydmljZU5hbWU6Im9yZGVyIg=="

# Button URL:
url = (
    f"{BASE_URL}?region=ap-beijing"
    f"&topic_id={TOPIC_ID}"
    f"&time=now-15m,now"
    f"&queryBase64={b64}"
)
```

This pre-fills `serviceName:"order"` in the search box. The user must manually type the Chinese portion (`AND message:"[借款下单]下单请求为"`).
