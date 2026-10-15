---
capability: rest-services-login-tokens-and-lockout
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.rate_limiter.record_failed_login@0545ececb4
  - cosa.rest.rate_limiter.clear_failed_attempts@f6ae7693b2
  - cosa.rest.rate_limiter.get_failed_attempts_count@154855e850
  - cosa.rest.rate_limiter.cleanup_old_attempts@06b7267b9d
  - cosa.rest.refresh_token_service.store_refresh_token@0d789eae9a
  - cosa.rest.refresh_token_service.validate_refresh_token@35815adeaf
  - cosa.rest.refresh_token_service.revoke_refresh_token@05bd66a591
  - cosa.rest.refresh_token_service.revoke_all_user_tokens@4f0637a313
  - cosa.rest.refresh_token_service.cleanup_expired_tokens@b1c1114741
  - cosa.rest.sqlite_database.get_auth_db_connection@a02f4ced10
  - cosa.rest.sqlite_database.init_auth_database@c44ea782fd
---
# Login lockout records and refresh-token storage

The functions that store failed logins and refresh tokens. The login route and token rotation that call them are in [[auth-and-accounts]]; the tables are in [[rest-services-account-tables]].

## What it does
- `record_failed_login( email, ip_address )` writes one `failed_login_attempts` row. It catches every error and returns nothing.
- `get_failed_attempts_count( email, minutes=15 )` counts attempts in the window and returns 0 on error.
- `clear_failed_attempts( email )` deletes every attempt for the email, after a successful login.
- `cleanup_old_attempts( hours )` converts hours to whole days, at least 1, and deletes attempts older than that many days. It returns the number deleted, or 0 on error.
- `store_refresh_token( user_id, token, jti, user_agent, ip_address )` stores the SHA-256 hash of the token and its expiry, never the token. It returns `( success, message )`.
- `validate_refresh_token( token )` checks signature, expiry, the revoked flag and the stored hash, and updates `last_used_at`. It returns `( success, message, token_data )`, and `token_data` holds `jti`, `user_id`, `created_at` and `expires_at`.
- `revoke_refresh_token( jti )` sets `revoked`; revoking twice is fine. `revoke_all_user_tokens( user_id )` forces a new login.
- `cleanup_expired_tokens` deletes rows past `expires_at` and every revoked row, and returns `( success, message, deleted_count )`; run it periodically.
- `get_auth_db_connection` opens the SQLite auth database with `sqlite3.Row` and foreign keys on. `init_auth_database` creates its tables and is safe to call again.

## Don't
- Don't expect these functions to raise: the token and rate-limit functions return an error in a tuple or log it.
- Don't call `rotate_refresh_token` as a transaction; storing the new token and revoking the old one are separate commits.

## Invariants
- The token string itself is never stored.
