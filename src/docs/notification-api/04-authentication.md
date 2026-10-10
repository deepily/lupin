> Part 4 of 16 of the [Lupin Notification API Reference](../notification-api.md): authentication.

## 3. Authentication

### Dual Auth Model

The notification API supports two authentication methods. **Either one is
sufficient** — you do not need to provide both.

#### Method 1: API Key (`X-API-Key` header)

API key authentication is the primary method for service-to-service communication.
This is what CLI clients, MCP tools, and agentic jobs use.

**Key format**:

```
ck_live_{64+ alphanumeric/underscore/hyphen characters}
```

**Format regex**: `^ck_live_[A-Za-z0-9_-]{64,}$`

**How validation works**:

1. Format check: regex match against the key format (fast rejection of malformed keys)
2. Database lookup: query all active keys from the `api_keys` table
3. Timing-safe comparison: `bcrypt.checkpw()` against each stored hash
4. On success: `last_used_at` timestamp updated, user UUID returned
5. On failure: HTTP 401 with descriptive error message

**Source**: `src/cosa/rest/middleware/api_key_auth.py`

#### Method 2: JWT Bearer Token (`Authorization` header)

JWT authentication is used primarily by the browser UI. Tokens are obtained
through the standard login flow.

**How to obtain a JWT**:

```bash
curl -s -X POST http://localhost:7999/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "your_password"}' \
  | jq -r '.access_token'
```

**How validation works**:

1. Extract token from `Authorization: Bearer <token>` header
2. Validate via `verify_token()` from `cosa.rest.auth`
3. On success: user UUID extracted from token claims
4. On failure: HTTP 401 with error details

---

### Auth Resolution Order

When both headers are present, the server tries them in this order:

1. **API Key** (`X-API-Key`) — checked first
2. **JWT** (`Authorization: Bearer`) — checked second
3. If neither succeeds: HTTP 401

**Source**: `require_api_key_or_jwt()` in `src/cosa/rest/middleware/api_key_auth.py`

---

### How to Obtain an API Key

API keys follow a **service account model**. They are stored as bcrypt hashes
in the PostgreSQL `api_keys` table, associated with a user account.

To create a new API key:

1. Contact the system administrator, or
2. Use the admin API to create keys programmatically

> **Security note**: API keys are stored as bcrypt hashes. The plaintext key is
> only available at creation time and cannot be retrieved from the database.

---

### Configuration Precedence (CLI Clients)

When using the Python CLI clients (`notify_user_sync.py`, `notify_user_async.py`),
credentials are resolved in this order:

```
Environment Variables  >  Config File  >  Hardcoded Defaults
```

#### Environment Variables

| Variable | Purpose | Default |
|-------------------------------|----------------------------------|----------------------------|
| `LUPIN_API_URL`               | Server base URL | `http://localhost:7999`    |
| `LUPIN_APP_SERVER_URL`        | Server base URL (legacy alias) | `http://localhost:7999`    |
| `LUPIN_API_KEY_FILE`          | Path to file containing API key | From config |
| `LUPIN_DEV_EMAIL`             | Default target user email | From config |
| `LUPIN_ENV`                   | Environment name for config | `local`                    |

#### Config File

The configuration manager reads from `src/conf/lupin-app.ini` using the
`LUPIN_CONFIG_MGR_CLI_ARGS` environment variable.

---

### Auth Header Examples

**API Key authentication**:

```bash
curl -X POST "http://localhost:7999/api/notify" \
  -H "X-API-Key: ck_live_abc123def456..." \
  -d "message=Hello+world" \
  -d "type=task" \
  -d "priority=medium" \
  -d "target_user=user@example.com"
```

**JWT Bearer authentication**:

```bash
# Step 1: Obtain a JWT token
TOKEN=$( curl -s -X POST http://localhost:7999/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "your_password"}' \
  | jq -r '.access_token' )

# Step 2: Use the token
curl -X POST "http://localhost:7999/api/notify" \
  -H "Authorization: Bearer $TOKEN" \
  -d "message=Hello+world" \
  -d "type=task" \
  -d "priority=medium" \
  -d "target_user=user@example.com"
```

---

### Error Responses

| Status Code | Condition | Error Detail |
|-------------|------------------------------------------|------------------------------------------------------------------------------|
| 401 | No auth header provided | `Missing auth. Provide X-API-Key or Authorization: Bearer <jwt>`             |
| 401 | API key format invalid | `Invalid API key format. Expected format: ck_live_{64+ characters}`          |
| 401 | API key not found or inactive | `Invalid or inactive API key. Verify your key is correct and active.`        |
| 401 | JWT validation failed | `Invalid JWT: <error details>`                                               |

All 401 responses include the `WWW-Authenticate` header:

```
WWW-Authenticate: API-Key, Bearer
```

---
