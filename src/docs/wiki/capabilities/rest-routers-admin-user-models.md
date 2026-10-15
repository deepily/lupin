---
capability: rest-routers-admin-user-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.admin.UserListResponse@5d78afcd03
  - cosa.rest.routers.admin.UserDetailsResponse@b5617d6a87
  - cosa.rest.routers.admin.UpdateRolesRequest@c5f160ed8d
  - cosa.rest.routers.admin.UpdateStatusRequest@b5089f64a8
  - cosa.rest.routers.admin.ResetPasswordRequest@4ede688363
  - cosa.rest.routers.admin.ResetPasswordResponse@02c226d763
  - cosa.rest.routers.admin.MessageResponse@ef56b84057
  - cosa.rest.routers.admin.CreateUserRequest@94c92eb23d
  - cosa.rest.routers.admin.CreateUserResponse@aa042b64a8
  - cosa.rest.routers.admin.DeleteUserRequest@dc730f6d06
  - cosa.rest.routers.admin.BatchDeleteUsersRequest@71ec6fb502
  - cosa.rest.routers.admin.BatchDeleteResult@d8e8ba9a4a
  - cosa.rest.routers.admin.BatchDeleteUsersResponse@2eb862f51b
---
# Admin user request and reply models

The pydantic models behind the routes in [[rest-routers-admin-users]], all in `cosa.rest.routers.admin`.

## What it does
- `UserListResponse` carries `users`, `total`, `limit` and `offset`.
- `UserDetailsResponse` carries id, email, roles, verified and active flags, created and last login times, and the audit and failed-login counts.
- `UpdateRolesRequest` holds `roles`, a list. `UpdateStatusRequest` holds `is_active`, a boolean.
- `ResetPasswordRequest` holds an optional `reason`. `ResetPasswordResponse` returns the message, the `temporary_password` and a `user` with id and email.
- `MessageResponse` is the generic reply: a `message` and an optional `user`.
- `CreateUserRequest` holds `email`, `password` and `roles`, which default to `["user"]`. `CreateUserResponse` returns `message`, `user` and `user_id`.
- `DeleteUserRequest` holds an optional `reason`.
- `BatchDeleteUsersRequest` holds `user_ids`, 1 to 50 of them, and an optional `reason`.
- `BatchDeleteResult` is one id's `user_id`, `success` and `message`. `BatchDeleteUsersResponse` lists them with `total_deleted` and `total_failed`.

## Don't
- Don't send more than 50 ids or an empty list to batch delete. The model refuses both with 422.
- Don't store the temporary password from `ResetPasswordResponse`. The route returns it once and keeps no copy.

## Invariants
- A batch delete with no `reason` is recorded as "Batch delete from admin UI".
