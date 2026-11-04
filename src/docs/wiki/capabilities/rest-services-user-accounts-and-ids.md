---
capability: rest-services-user-accounts-and-ids
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.user_service.create_user@b51c8d16a6
  - cosa.rest.user_service.authenticate_user@f8a66e6c2b
  - cosa.rest.user_service.get_user_by_id@2969b214db
  - cosa.rest.user_service.get_user_by_email@f83d08afa7
  - cosa.rest.user_service.update_user_password@ba9d67e58c
  - cosa.rest.user_service.reset_password_with_token@9630db6e11
  - cosa.rest.user_service.mark_email_verified@30d88578b2
  - cosa.rest.user_service.deactivate_user@63d9e4b254
  - cosa.rest.user_id_generator.email_to_system_id@0ec85066ea
  - cosa.rest.user_id_generator.email_to_user_uuid@ab62e5a52a
  - cosa.rest.user_id_generator.system_id_to_display_name@f0f708ffad
  - cosa.rest.user_id_generator.validate_system_id@4cabaf6ce2
  - cosa.rest.user_id_generator.get_user_info@d0e945229f
  - cosa.rest.user_id_generator.get_user_info_by_email@c402ffc7a0
---
# User account functions and user ids

The Postgres-backed account functions in `user_service` and the id helpers in `user_id_generator`. The routes that call them are in [[auth-and-accounts]]; the table is `User` on [[rest-services-account-tables]].

## What it does
- `create_user( email, password, roles )` checks that the email contains `@`, validates password strength and hashes the password. It rejects a duplicate email and returns `( success, message, user_id )`. Roles default to `["user"]`.
- `authenticate_user( email, password )` matches the email without regard to case, checks bcrypt and rejects an inactive user. On success it sets `last_login_at` and returns `( success, message, user_data )`.
- `get_user_by_id` and `get_user_by_email` return a dict without the password hash, or `None`.
- `update_user_password( user_id, old_password, new_password )` verifies the old password and the new one's strength first.
- `reset_password_with_token( user_id, new_password )` sets a new password for a user whose reset token the caller already checked.
- `mark_email_verified` sets `email_verified`. `deactivate_user` sets `is_active` to `False` and keeps the row.
- `email_to_system_id( email )` is deterministic and ends in a 4-character hash suffix. It raises `ValueError` for an empty email or one without `@`.
- `email_to_user_uuid( email )` returns the UUID that mock auth hands out. It is minted from the email alone, so it is stable across restarts and needs no database.
- `validate_system_id` matches `^[a-z0-9_]+_[a-f0-9]{4}$`. `system_id_to_display_name` capitalizes the part before the first underscore.
- `get_user_info` and `get_user_info_by_email` look up the in-file `MOCK_USER_DATABASE`.

## Don't
- Don't expect `reset_password_with_token` to check a token. Verify the token first.
- Don't rely on `get_user_info` for real accounts. It reads a fixed mock table.
