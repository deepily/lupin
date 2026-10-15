---
capability: rest-routers-request-auth-guards
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.middleware.api_key_auth.validate_api_key@7a69c46a05
  - cosa.rest.middleware.api_key_auth.require_api_key_or_jwt@a10d46872a
  - cosa.rest.middleware.api_key_auth.authenticated_account_email@0d1a9194ea
  - cosa.rest.middleware.path_identity.require_path_identity_owner@03770e0b83
  - cosa.rest.middleware.path_identity.require_query_identity_owner@7c495df6ba
  - cosa.rest.dependencies.config.get_id_generator@1716d3664c
---
# Request authentication guards

The FastAPI dependencies in `cosa.rest.middleware` that decide who a caller is, and one shared id generator from `cosa.rest.dependencies.config`.

## What it does
- `validate_api_key( api_key )` checks a key against the stored hashes in a worker thread. It returns the owner's user id, or `None` for an unknown or inactive key.
- `require_api_key_or_jwt` accepts an `X-API-Key` header or an `Authorization: Bearer` token, tries the key first, and returns the user id. A key that is malformed, unknown or inactive is 401 even when a Bearer token comes with it. Anything else is 401. A key must look like `ck_live_` plus 64 or more characters.
- `authenticated_account_email` returns the verified `email` claim of a Bearer access token, or `None`. It never raises and authenticates nothing, so pair it with the guard above.
- `require_path_identity_owner` refuses, with 403, a caller who is not the user named in the path (`user_id` or `user_email`). It returns the caller's id. A route with no such parameter is 500.
- `require_query_identity_owner` checks the query string the same way, but returns the caller's account email from the user record. It has no 500 arm: a query naming no user returns the email, and the handler's own required parameter answers 422. A user record that is gone is 403.
- `get_id_generator` returns the one `TwoWordIdGenerator`, made on the first call.

## Don't
- Don't use `authenticated_account_email` alone as a gate. `None` also means an API-key caller.
- Don't expect an admin bypass in the identity guards. The owner rule is the only rule.

## Invariants
- The identity match is exact on the user id, or the account email ignoring case.
