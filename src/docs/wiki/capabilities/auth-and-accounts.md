---
capability: auth-and-accounts
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.jwt_service.create_access_token@9802b174e8
  - cosa.rest.jwt_service.decode_and_validate_token@91d44cf713
  - cosa.rest.routers.auth.login@59ab1f21ed
  - cosa.rest.refresh_token_service.rotate_refresh_token@ec964812ca
  - cosa.rest.rate_limiter.check_account_lockout@d2aa947aba
  - cosa.rest.middleware.api_key_auth.require_api_key@8f714353bd
  - cosa.rest.auth.verify_token@d3ed427a0d
  - cosa.rest.admin_service.admin_delete_user@60d01a2fa4
---
# Auth and accounts

Login, JWT access and refresh tokens, API keys, user accounts, password rules, email tokens, and the audit log. Reuse the FastAPI dependencies here to protect a route; do not write a new token check. Table access goes through [[db-repositories]] and [[db-session-and-schema]].

## Tokens
- `create_access_token` signs HS256 by default (`jwt algorithm`), with `sub`, `email`, `roles`, `exp`, `iat`, `jti`. Lifetime is `jwt access token expire minutes`, default 30. A refresh token carries `token_type="refresh"`, lives `jwt refresh token expire days`, default 7.
- `decode_and_validate_token( token, expected_type )` checks signature and expiry. `"access"` rejects a token whose `token_type` is `refresh`. `"refresh"` rejects any token without `token_type="refresh"`. With no `expected_type`, no type check is made; `PUT /auth/change-password` calls it that way.
- `verify_token` picks the verifier from env `AUTH_MODE`, else config `auth mode`, else `mock`. `jwt` mode checks an access token, then loads the user row and rejects an inactive account (401). `mock` mode accepts `mock_token_*` strings and checks no password. Any other value, `firebase` included, is 401.

## Protecting a route
- `get_current_user` (in `auth_middleware`) requires a Bearer header and returns the `verify_token` dict. `get_current_user_optional` returns `None` when the header is absent, and still raises 401 on a bad token.
- `require_roles( [...] )` passes a user holding any listed role; `require_all_roles` needs every one. Both answer 403. `require_admin` is `require_roles( ["admin"] )`.
- `require_api_key` reads `X-API-Key`. The key must match `ck_live_` plus 64 or more of `[A-Za-z0-9_-]`, or it is 401 before any database call. It then runs bcrypt against the active keys, off the event loop, and stops at the first match, whose `user_id` it returns. A stored hash that is not valid bcrypt is logged by key id and skipped; the keys after it are still checked. A database error becomes 401.
- `require_api_key_or_jwt` uses the API key alone when `X-API-Key` is present, with no fall-through to JWT. Otherwise it needs a Bearer token.

## Login, lockout, refresh
- `POST /auth/login` first calls `check_account_lockout`. A locked email gets 429 and an audited `login_failure`, and the password is not checked.
- Any `authenticate_user` failure (unknown email, inactive account, wrong password) calls `record_failed_login( email, ip )`, audits `login_failure`, and returns 401. Success calls `clear_failed_attempts` and audits `login_success`.
- Locked means failed rows within `auth lockout duration minutes` (default 15) number at least `auth max failed attempts` (default 5). A database error in the check returns not locked.
- `POST /auth/refresh` calls `rotate_refresh_token`. The old token must verify as a refresh token, have a stored row, be unrevoked, and match its stored SHA-256 hash. The old row is revoked before the new token is made and stored, and no step undoes the revoke if a later step fails.
- `POST /auth/logout` revokes the refresh token by `jti`. If the token fails verification for any reason, such as expiry or a bad signature, it reads the `jti` without checking the signature and revokes that. No code looks an access token up in a revocation table, so it stays valid until `exp`.
- `POST /auth/register` is unauthenticated. It returns 403 if `roles` names anything but `user`, and always stores `["user"]`.

## Admin and audit
- `/admin/users` routes need `require_admin`. Roles are limited to `admin` and `user`. An admin cannot remove their own admin role or deactivate themselves. Deactivating revokes the user's refresh tokens.
- `admin_delete_user` refuses self, a protected account, and an admin target while at most one active admin exists (the target's own active status is not checked), then revokes tokens and hard-deletes. `POST /admin/users/batch-delete` takes 1 to 50 ids and runs each through it.
- The admin router also holds snapshot and source-refresh routes; they are not covered here. See [[system-admin-and-stats]].
