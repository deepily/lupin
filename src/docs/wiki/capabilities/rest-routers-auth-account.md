---
capability: rest-routers-auth-account
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.auth.register@40778b116c
  - cosa.rest.routers.auth.refresh@35fa448227
  - cosa.rest.routers.auth.logout@86d6f4374b
  - cosa.rest.routers.auth.get_current_user@442b396f62
  - cosa.rest.routers.auth.change_password@0b4d7ac47e
  - cosa.rest.routers.auth.request_verification@9644ed1380
  - cosa.rest.routers.auth.verify_email@fab222c595
  - cosa.rest.routers.auth.request_password_reset@aa3c6fe5b3
  - cosa.rest.routers.auth.reset_password@db605aeecc
---
# Account routes: register, tokens, password and email

The `/auth` router: sign-up, token rotation, logout, the signed-in user, password change and reset, and email verification. The services behind it are in [[auth-and-accounts]].

## What it does
- `register` (`POST /auth/register`) creates an account with the role `user` only and returns 201 with user info and a token pair. A request naming any other role is refused with 403 and an audit event.
- `refresh` (`POST /auth/refresh`) swaps a refresh token for a new pair and revokes the old one. An invalid, expired or revoked token answers 401.
- `logout` (`POST /auth/logout`) revokes the refresh token and answers 400 for a token it cannot read. It does nothing to the access token.
- `get_current_user` serves `GET /auth/me` from a Bearer access token. A missing or bad header answers 401, and an unknown user 404.
- `change_password` (`PUT /auth/change-password`) checks the current password and the strength of the new one, then writes an audit event.
- `request_verification` (`POST /auth/request-verification`) sends a new verification email to a signed-in user, and answers 400 when the email is already verified.
- `verify_email` (`POST /auth/verify-email`) marks the email verified with a one-use token.
- `request_password_reset` (`POST /auth/request-password-reset`) answers 200 whether or not the email exists. The token expires in one hour.
- `reset_password` (`POST /auth/reset-password`) checks strength before it spends the token, so a weak password leaves the link usable.

## Don't
- Don't send `roles` on `register` expecting an admin. An admin is made through `/admin/users`.

## Invariants
- Reset and verification tokens work once.
