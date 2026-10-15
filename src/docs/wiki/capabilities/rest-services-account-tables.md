---
capability: rest-services-account-tables
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.postgres_models.User@00f55ae964
  - cosa.rest.postgres_models.RefreshToken@1f89810270
  - cosa.rest.postgres_models.ApiKey@0473583c6a
  - cosa.rest.postgres_models.EmailVerificationToken@650b1be3b3
  - cosa.rest.postgres_models.PasswordResetToken@623d3f5123
  - cosa.rest.postgres_models.FailedLoginAttempt@4ef7278ac2
  - cosa.rest.postgres_models.AuthAuditLog@c6be145cfc
  - cosa.rest.postgres_models.FcmToken@879b90fd12
---
# Account and device tables

The SQLAlchemy models in `cosa.rest.postgres_models` for the `lupin_auth` database that hold accounts, tokens and security events. Use these classes through the session helpers in [[db-session-and-schema]] and [[db-repositories]]; the login flow that reads them is in [[auth-and-accounts]].

## What it does
- `User` is the `users` table. The id is a generated UUID, `roles` defaults to `["user"]`, and deleting a user cascades to its tokens and keys.
- `RefreshToken` (`refresh_tokens`) stores the SHA-256 hash of a refresh token, its `jti` and `expires_at`; `revoked` defaults to `False`.
- `ApiKey` (`api_keys`) holds a bcrypt hash at cost 12, not a SHA-256 digest. The `String(64)` column width says nothing about the algorithm.
- `EmailVerificationToken` and `PasswordResetToken` each hold a unique token string, `expires_at` and a `used` flag defaulting to `False`.
- `FailedLoginAttempt` records email and IP with a BIGSERIAL id and no foreign key, so attempts against accounts that do not exist are tracked too.
- `AuthAuditLog` requires an `event_type`. Its `user_id` is optional so events for users who are not logged in can be kept, and `success` defaults to `True`.
- `FcmToken` is one row per mobile device token for the silent wake channel. The token is the upsert key, `user_id` is indexed, and the wake service reads a user's tokens from this table when it needs them.

## Don't
- Don't store a plaintext password: `User.password_hash` takes a hash only.
- Don't assume an ApiKey hash is SHA-256. Verify it with bcrypt, as `middleware/api_key_auth.py` does.
- Don't add a foreign key to `FailedLoginAttempt`; it would drop the attempts that matter most.

## Invariants
- `FcmToken` timestamps are timezone-aware UTC. `AuthAuditLog` stamps `event_time` and `FailedLoginAttempt` stamps `attempt_time`; neither has a `created_at`.
