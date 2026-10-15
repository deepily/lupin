---
capability: rest-core-admin-accounts
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.admin_service.list_users@64aba9ecb6
  - cosa.rest.admin_service.get_user_details@01daf12be7
  - cosa.rest.admin_service.update_user_roles@7798ad9dd3
  - cosa.rest.admin_service.toggle_user_status@2852a51d4d
  - cosa.rest.admin_service.admin_reset_password@e196bfd823
  - cosa.rest.admin_service.admin_create_user@16a8c3c889
  - cosa.rest.password_service.hash_password@d4c9ca9760
  - cosa.rest.password_service.verify_password@b869bfc018
  - cosa.rest.password_service.validate_password_strength@e87b077b6b
  - cosa.rest.jwt_service.create_refresh_token@1891e88863
---
# Admin account actions and password rules

Administrator operations on user accounts, and the password helpers they use. Token signing and verification are on [[auth-and-accounts]]. Each admin function returns a tuple and never raises: `(success, message, data)`. Every change writes an audit row through [[rest-core-auth-audit-and-models]].

## Admin actions
- `list_users` takes `limit` (capped at 1000), `offset`, an email `search` and `role_filter` and `status_filter`. It returns `(users, total)` newest first, and the total follows the filters.
- `get_user_details` returns the user with an audit-log count and a failed-login count, and no password hash. It returns `None` for an unknown id.
- `update_user_roles` accepts only `admin` and `user`. An administrator cannot drop their own `admin` role.
- `toggle_user_status` stops an administrator deactivating themselves. Deactivating also revokes every refresh token of the target.
- `admin_create_user` creates the account through `create_user` and marks the email verified, then writes an `admin_user_create` event.
- `admin_reset_password` makes a 16-character temporary password from letters, digits and `!@#$%^&*`. If it fails the strength check it tries once with 20 characters. The password comes back once and only its hash is stored.

## Password helpers
- `hash_password` returns a bcrypt hash with a random salt, and raises `ValueError` on an empty password.
- `verify_password` returns `False` on a mismatch or on any error. It never raises.
- `validate_password_strength` returns `(True, "")` or `(False, reason)`. It wants 8 characters, 3 of the 4 character classes, and a password not on the common-password list.

## Refresh tokens
- `create_refresh_token( user_id, email )` signs a token with `token_type` `refresh`, and raises `ValueError` on an empty id or email.

## Don't
- Don't show or log the temporary password after the first return.
- Don't expect an exception from an admin function. Read `success`.
