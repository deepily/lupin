---
capability: rest-routers-admin-users
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.admin.get_users@c605ca0c49
  - cosa.rest.routers.admin.get_user@160ff81e6a
  - cosa.rest.routers.admin.update_roles@f998c6f0d9
  - cosa.rest.routers.admin.update_status@b40c9eef13
  - cosa.rest.routers.admin.reset_user_password@2b0e813d5f
  - cosa.rest.routers.admin.create_user_endpoint@5b5b6b6d0c
  - cosa.rest.routers.admin.delete_user_endpoint@af6011b059
  - cosa.rest.routers.admin.batch_delete_users_endpoint@843f32acc7
---
# Admin user management routes

The `/admin/users` routes in `cosa.rest.routers.admin`. Every one depends on `require_admin`, so a caller without the admin role is turned away before the handler runs. The bodies and replies are in [[rest-routers-admin-user-models]].

## What it does
- `get_users` lists users, `GET /admin/users`, with `limit`, `offset`, `search`, `role` and `status_filter`. It returns the page plus a `total`.
- `get_user` returns one user's details with audit counts, `GET /admin/users/{user_id}`. An unknown id is 404.
- `update_roles` sets a user's roles, `PUT /admin/users/{user_id}/roles`. The service refuses an admin removing their own admin role.
- `update_status` activates or deactivates an account, `PUT /admin/users/{user_id}/status`. The service refuses self-deactivation.
- `reset_user_password` makes a temporary password, `POST /admin/users/{user_id}/reset-password`, and returns it once.
- `create_user_endpoint` makes an account, `POST /admin/users`, with 201. The service marks the email verified; if that step fails it only prints a warning.
- `delete_user_endpoint` hard-deletes an account, `DELETE /admin/users/{user_id}`. A body with a `reason` is optional.
- `batch_delete_users_endpoint` deletes up to 50 accounts in one `POST /admin/users/batch-delete`.

## Don't
- Don't expect a typed status code from a service refusal. The handlers pick 404, 400 or 500 by matching words in the service's message.
- Don't treat a batch delete as all-or-nothing. Each id runs alone, and the reply lists a success flag per id.

## Invariants
- Each write passes the admin's id, email and client address to the service, which writes the audit record.
