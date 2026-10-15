---
capability: rest-core-auth-audit-and-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.auth_audit.log_auth_event@6d91da1c80
  - cosa.rest.auth_audit.get_user_audit_log@c8a9f7de6e
  - cosa.rest.auth_audit.get_failed_logins@53fbdb8b87
  - cosa.rest.auth_audit.get_suspicious_activity@a3a0513dc3
  - cosa.rest.auth_models.RegisterRequest@56f68edc97
  - cosa.rest.auth_models.LoginRequest@62dc372a8a
  - cosa.rest.auth_models.RefreshRequest@3a754a02e1
  - cosa.rest.auth_models.LogoutRequest@a64175c4c5
  - cosa.rest.auth_models.TokenResponse@c5ff73bf56
  - cosa.rest.auth_models.UserResponse@1bc40e06a5
  - cosa.rest.auth_models.RegisterResponse@7db97a8895
  - cosa.rest.auth_models.LoginResponse@a70c52933b
  - cosa.rest.auth_models.RefreshResponse@d847a74368
  - cosa.rest.auth_models.LogoutResponse@42518762d3
  - cosa.rest.auth_models.ErrorResponse@595aac5443
  - cosa.rest.auth_models.RequestVerificationRequest@5d345a364a
  - cosa.rest.auth_models.VerifyEmailRequest@4ccbb2616c
  - cosa.rest.auth_models.RequestPasswordResetRequest@b1a2c4d83c
  - cosa.rest.auth_models.ResetPasswordRequest@97ee0131d7
  - cosa.rest.auth_models.ChangePasswordRequest@22fa9f8ae9
  - cosa.rest.auth_models.MessageResponse@5dbcf38f76
---
# Auth audit log and request models

Audit rows for authentication events and the bodies of the `/auth` routes, which are on [[auth-and-accounts]].
- `log_auth_event( event_type, user_id, email, ip_address, details, success )` stores one timestamped row and catches every exception, so a failed audit write never breaks a request.
- `get_user_audit_log( user_id, limit=50 )` and `get_failed_logins( email, limit=50 )` return entries newest first; the email may be omitted.
- `get_suspicious_activity( hours=24, threshold=5 )` returns `(email, failures)` pairs at or above the threshold.
- Requests: `RegisterRequest` (email, password, roles), `LoginRequest` (email, password), `RefreshRequest` and `LogoutRequest` (refresh_token).
- More requests: `VerifyEmailRequest` (token), `RequestPasswordResetRequest` (email), `ResetPasswordRequest` (token, new_password), `ChangePasswordRequest` (current_password, new_password), `RequestVerificationRequest` (no fields).
- `TokenResponse`: access_token, refresh_token, token_type, expires_in.
- `UserResponse`: id, email, roles, email_verified, is_active, created_at, last_login_at.
- `RegisterResponse` and `LoginResponse`: message, user, tokens. `RefreshResponse`: message, tokens.
- `LogoutResponse` and `MessageResponse`: message. `ErrorResponse`: detail, error_code.
