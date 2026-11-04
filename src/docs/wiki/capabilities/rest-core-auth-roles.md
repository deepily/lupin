---
capability: rest-core-auth-roles
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.auth_middleware.get_current_user@079e1de175
  - cosa.rest.auth_middleware.get_current_user_optional@659250aea8
  - cosa.rest.auth_middleware.require_roles@3a9b519c97
  - cosa.rest.auth_middleware.require_all_roles@bdc6968c9b
  - cosa.rest.auth_middleware.is_admin@d8a5c23439
  - cosa.rest.auth_middleware.is_user@bfdcdc2088
  - cosa.rest.auth_middleware.has_role@35b857ae7f
  - cosa.rest.auth_middleware.has_any_role@ca623cb1c4
  - cosa.rest.auth_middleware.has_all_roles@030e9957fd
---
# Header dependencies and role checks

The dependencies in `cosa.rest.auth_middleware` read the `Authorization` header directly. The bearer-scheme set is [[rest-core-auth-bearer]]; token verification is on [[auth-and-accounts]].

## Dependencies
- `get_current_user` requires `Authorization: Bearer <token>` and answers 401 for a missing header, a bad format or a bad token.
- `get_current_user_optional` returns `None` with no header, and still answers 401 when a header is present and malformed or bad.
- `require_roles( [...] )` builds a dependency that passes a user holding any one listed role. `require_all_roles` needs every one.
- Both builders answer 403 for a user without the role and raise `ValueError` when called with an empty list.

## Manual checks
- `has_role( user, role )`, `has_any_role( user, roles )` and `has_all_roles( user, roles )` read the `roles` list of the user dict and return a bool. Under `auth mode` mock the dict has no roles, so every role check fails and `require_roles` answers 403.
- `is_admin( user )` and `is_user( user )` are `has_role` for `admin` and `user`.
- Use them inside a route when the response shape, not access, depends on the role.

## Don't
- Don't use both `get_current_user` functions in one router. They read the credentials differently.
