---
capability: rest-core-email-tokens
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.email_service.send_verification_email@e9e929e1c5
  - cosa.rest.email_service.send_password_reset_email@bf983803c1
  - cosa.rest.email_service.test_email_configuration@c98951b49f
  - cosa.rest.email_token_service.generate_verification_token@d62ca3518c
  - cosa.rest.email_token_service.validate_verification_token@92fdccfac1
  - cosa.rest.email_token_service.generate_password_reset_token@afc96e825f
  - cosa.rest.email_token_service.validate_password_reset_token@c6922d5c9d
  - cosa.rest.email_token_service.cleanup_expired_tokens@0846437e91
---
# Email tokens and mail

One-use tokens for verifying an email address or resetting a password, and the SMTP mail that carries them. Login and registration flows are on [[auth-and-accounts]].

## Tokens
- `generate_verification_token( user_id )` and `generate_password_reset_token( user_id )` return `(success, message, token)`. The token is 32 random bytes. A verification token lasts 24 hours and a reset token lasts 1 hour.
- `validate_verification_token( token )` and `validate_password_reset_token( token )` return `(success, message, user_id)`. A good token is marked used at once, so a second call with it fails. An expired, unknown or used token gives `(False, message, None)`. So does any database error.
- `cleanup_expired_tokens` deletes expired or used rows from both tables and returns `(verification_deleted, reset_deleted)`. It returns `(0, 0)` on any error.

## Mail
- `send_verification_email( email, token, user_name )` and `send_password_reset_email( email, token, user_name )` use the SMTP settings in config. They return `True` when the mail went out and `False` when sending failed. With `send email enabled` false, the default, they return `True` and send nothing.
- `test_email_configuration` tries to reach the SMTP server and returns `True` or `False`, printing the error. A bad port or malformed setting raises `ValueError` or `TypeError`.

## Don't
- Don't validate a token to peek at it. Validation spends it.
- Don't treat a `False` from a send as an error to raise; the caller decides what to tell the user.
