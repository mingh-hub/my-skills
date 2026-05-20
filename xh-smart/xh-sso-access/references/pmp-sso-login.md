# PMP/XH Internal Platform — SSO Access Reference

## When To Read

Read when an internal PMP/boss-mgr/droolsCms page needs RSA SSO login, redirectUri construction, or cookie-domain troubleshooting. Routine Argus/JANUS handling should use `tools/argus_session.py` and `janus-argus-sso.md`.

## Contents

- SSO endpoints
- App IDs and redirectUri patterns
- RSA login flow
- Cookie injection and timing pitfalls

## SSO Endpoints

| Environment | SSO Host | PMP Host |
|---|---|---|
| UAT | `sso.xhqb.xyz` | `pmp-uat.xhdev.xyz` |
| Production | `sso.xiaohuaai.com` | `pmp.xiaohuaai.com` |

### Other xhdev.xyz Platforms

| Platform | URL | SSO Method |
|---|---|---|
| Argus (日志) | `argus.xhdev.xyz/cls/clsDatasightSave` | 飞书扫码 only — see `janus-argus-sso.md` |

> **Pitfall**: 不同平台 SSO 方式不同。PMP 支持账号密码（RSA加密），Argus 仅支持飞书扫码，无法自动化登录。

## Login API

**POST** `https://{sso-host}/sso-api/login`

```
Content-Type: application/x-www-form-urlencoded
```

### Fields

| Field | Description |
|---|---|
| `username` | Login username |
| `password` | RSA-encrypted password (see below) |
| `appId` | Application ID (`ei` for PMP, `bossmgr` for boss-mgr, `droolsCms` for droolsCms) |
| `userType` | `local` for test accounts, `ldap` for LDAP users |
| `redirectUri` | URL-encoded redirect to the destination page |

### RSA Encryption

The password must be encrypted with RSA PKCS1v15 before submission.

```python
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

PUBLIC_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCN06nvQZpPqLJyZQxFPNzCipeA3KWZ20hH6B9EK+bLcaK0QbN4t7UoKhdV+UGXQysDAdWI/RdXcSbxsZVOxrAhpAPxKIfVMTcn89k/Rtn9ymKQ2O7ZiJ87V74scn3bYUhctgICuhbnbc0MjfQ6HhkJywGyg2Lu08T1+Nl1ggmXqQIDAQAB"

def encrypt(txt):
    public_key_der = base64.b64decode(PUBLIC_KEY)
    public_key = serialization.load_der_public_key(public_key_der, backend=default_backend())
    encrypted = public_key.encrypt(txt.encode('utf-8'), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('utf-8')
```

### redirectUri Construction

#### PMP redirectUri

The redirectUri is double-URL-encoded. Pattern:

```
https%3A%2F%2F{host}%2Fpmp-web%2FpreLogin%3ForiginUrl%3Dhttps%253A%252F%252F{host}%252Fpmp%252FstoryList%252FstoryInfo%252F{storyId}
```

In Python:
```python
from urllib.parse import quote

origin_url = f"https://{host}/pmp/storyList/storyInfo/{story_id}"
redirect_uri = f"https://{host}/pmp-web/preLogin?originUrl={quote(origin_url, safe='')}"
encoded_redirect = quote(redirect_uri, safe='')
```

#### boss-mgr / droolsCms redirectUri

```python
server = {
    "bossmgr": "https%3A%2F%2Ftest3.xiaohuaai.com%2Fboss-mgr-api%2FpreLogin%3ForiginUrl%3Dhttps%253A%252F%252Ftest3.xiaohuaai.com%252Fbossmgr%252F%2523%252Fadv%252FBGALL",
    "droolsCms": "https%3A%2F%2Ftest3.xiaohuaai.com%2Fdrools-cms%2FpreLogin%3ForiginUrl%3Dhttps%253A%252F%252Ftest3.xiaohuaai.com%252Fstrategy-admin%252Fhome"
}
# 替换 test3 为实际环境域名
redirect_uri = server.get(app_id).replace("test3", env)
```

## Response Cookies

On success, the SSO returns these cookies (must capture both):

- `TGC-prod` — Ticket Granting Cookie (required for SPA authentication)
- `SESSION` — Session token

**Critical:** `allow_redirects=True` is needed to capture the TGC-prod cookie, which is set during the SSO→App redirect. With `allow_redirects=False`, only SESSION is captured and the SPA won't authenticate.

**Cookie injection order — TWO approaches, prefer method A:**

**Method A (recommended — direct TGC-prod injection, bypasses SSO redirect):**
1. Login via Python with `allow_redirects=True` to capture both `TGC-prod` and `SESSION`.
2. Navigate browser to a static resource on the **PMP domain** (e.g. `pmp-uat.xhdev.xyz/pmp/favicon.ico`).
3. Inject the `TGC-prod` cookie on `.xhdev.xyz` (or `.xiaohuaai.com` for prod):
   ```javascript
   document.cookie = "TGC-prod=TGT-xxxxx; path=/; domain=.xhdev.xyz";
   ```
4. Navigate directly to the target page. The PMP SPA checks `TGC-prod` and authenticates without any SSO redirect.

**Method B (SSO redirect — less reliable):**
1. Navigate to `sso-host/favicon.ico`, inject `SESSION` cookie on `.xhqb.xyz`.
2. Navigate to the app. The SSO redirect chain should recognize SESSION and issue TGC-prod.
3. **Pitfall:** This often fails — the SSO login page appears despite SESSION being set. Prefer Method A.

**Login verification:** Check for `errorMessage=` in the 302 Location header, not the response body.

**Timing pitfall:** After injecting cookies and navigating, the React SPA may briefly show all fields as `"-"` before API data loads. Wait 2-5 seconds then re-check `document.body.innerText`. Empty fields do NOT necessarily mean permission denied — if the page shows the bug/story structure (tabs, labels) but empty values, the data is still loading. Permission-denied pages show an explicit "没有权限" message or a "温馨提示: 这是一个保密需求" dialog.

## Browser Login Form

The SSO login page has two modes:

| Radio | userType | Token field | Password format |
|-------|----------|-------------|-----------------|
| LDAP | `ldap` | Required (宁盾令牌) | Plaintext |
| Standard | `local` | Hidden | RSA-encrypted |

The hidden form fields include `appId`, `redirectUri`, and `userType`. The visible password field may differ from the hidden `name="password"` field — the Vue/Element UI form may encrypt the password client-side before populating the hidden field.

## Known Accounts

| Account | Type | Password | Access |
|---|---|---|---|
| `auto_test_standard` | `local` | `Auto@test` (RSA-encrypted) | Standard PMP access on both UAT and production; restricted stories show "没有权限" |
| `minghai` | `ldap` | Requires 宁盾 dynamic token (6-digit) | Broader access, can view restricted stories |

**Note:** `minghai` with `userType=local` returns "账号+密码错误"。The account is LDAP-type and requires a real-time 宁盾 token. Even with fresh tokens the LDAP flow consistently fails — the 1-2 second latency between token generation and API call may be the blocker.

## SSO Platform Isolation

| SSO System | Domain | Platforms | Auth Method |
|---|---|---|---|
| XH SSO | `sso.xiaohuaai.com` / `sso.xhqb.xyz` | PMP, boss-mgr, droolsCms | Password (local RSA / ldap token) |
| JANUS | `janus.xiaohuaai.com` | Argus (argus.xhdev.xyz) | 飞书扫码 ONLY |

> **Critical:** These two SSO systems are COMPLETELY isolated. Cookies from XH SSO (TGC-prod, SESSION) do NOT authenticate with JANUS. There is NO programmatic path from XH SSO credentials to JANUS/Argus access.

## PMP Page Structure

- Title: `项目管理平台`
- SPA framework: React (antd component library)
- Bug detail page path: `/onlineBugDetail/{bugId}`
- Bug list page path: `/onlineBugList`

### Data Extraction

```javascript
// Quick check — is data loaded or still "-"?
document.body.innerText

// Get tab panel content
Array.from(document.querySelectorAll('.ant-tabs-tabpane')).map(t => t.innerText)
```

### Permission Errors

If the account lacks access, the page renders:
```
温馨提示
这是一个保密需求，
您没有权限访问。
```
