---
capability: rest-data-repos-auth
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.repositories.api_key_repository.ApiKeyRepository@772a91a512
  - cosa.rest.db.repositories.auth_audit_log_repository.AuthAuditLogRepository@c23e1ce986
  - cosa.rest.db.repositories.email_verification_token_repository.EmailVerificationTokenRepository@ef5e38bb47
  - cosa.rest.db.repositories.failed_login_attempt_repository.FailedLoginAttemptRepository@c718adece0
  - cosa.rest.db.repositories.password_reset_token_repository.PasswordResetTokenRepository@f6f4cc0190
  - cosa.rest.db.repositories.refresh_token_repository.RefreshTokenRepository@cb1fa43c4a
  - cosa.rest.db.repositories.user_repository.UserRepository@80e146dd7c
---
# Account repositories

Seven repositories hold the account tables: users, API keys, refresh tokens, the two one-time tokens, failed logins and the audit log. Each subclasses `BaseRepository` and takes an open session. What the auth flows do with them is in [[auth-and-accounts]]; the base class and commit rules are in [[db-repositories]].

## What it does
- `UserRepository` looks users up by email, creates them (roles default to `["user"]`, active, email unverified) and flips password, roles, active and verified flags. It also lists active users, filters by role and counts.
- `ApiKeyRepository` stores a key hash per user. It finds by hash, and by user with inactive keys left out unless asked for. It activates and deactivates, stamps last use, and lists every active key for the middleware.
- `RefreshTokenRepository` is keyed by `jti`. `revoke` marks one token, `revoke_all_for_user` marks every unrevoked one and returns the count, and `delete` removes one row. `cleanup_expired` deletes rows that are expired or revoked.
- `EmailVerificationTokenRepository` and `PasswordResetTokenRepository` create a token with an expiry (24 hours and 1 hour by default) and `mark_used` it. `cleanup_expired` deletes rows that are expired or used.
- `FailedLoginAttemptRepository` records an attempt and counts the ones in the last N minutes (15 by default) by email or by IP. `delete_by_email` deletes every attempt for an address and returns the count.
- `AuthAuditLogRepository.log_event` writes one row. Its reads filter by user, event type, IP or the failed ones, newest first. The user and event-type reads page with `limit` 100 and `offset` 0. `get_by_ip`, `get_failed_events` and `count_by_event_type` look back 24 hours unless told otherwise.

## Don't
- Don't store a SHA-256 digest as an API key hash. Keys are checked with bcrypt, so such a key never authenticates.
- Don't expect `ApiKeyRepository.is_valid` to check an expiry. It checks only that the key exists and is active.
- Don't treat a `False` or `None` return as an error. An unknown id or token returns that quietly.

## Invariants
- Email is lower-cased on write and on lookup in the user and failed-login repositories. The audit log lower-cases it on write only, and none of its reads takes an email.
- Every write flushes and none commits. The caller's session decides when it lands.
- A token is valid only if it exists, is not used or revoked, and has not expired.
- `cleanup_old` on the audit log (90 days) and failed logins (30 days) delete by age and return the row count.
