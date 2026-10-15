---
capability: rest-core-auth-bearer
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.auth.HTTPBearerWith401@d23afa58b9
  - cosa.rest.auth.TokenExpiredException@b1744385ae
  - cosa.rest.auth.init_firebase@6399056aa3
  - cosa.rest.auth.verify_jwt_token@0538d6d110
  - cosa.rest.auth.verify_mock_token@b8c5a99374
  - cosa.rest.auth.verify_firebase_token@06c57a83a7
  - cosa.rest.auth.get_current_user@e7e898b502
  - cosa.rest.auth.get_current_user_id@c1afe18548
  - cosa.rest.auth.get_optional_user@5b22537b4d
  - cosa.rest.auth.identity_or_401@d26673e7c7
---
# Bearer-token dependencies

The bearer-scheme dependencies in `cosa.rest.auth`. `verify_token` and the overview of protecting a route are on [[auth-and-accounts]]; role checks are on [[rest-core-auth-roles]].

## Dependencies
- `get_current_user` takes the bearer credentials, runs `verify_token` and returns the user dict. `get_current_user_id` returns only its `uid`.
- `get_optional_user` returns `None` for no credentials and for a bad token. It never raises.
- `identity_or_401( current_user )` returns `( uid, email )` or raises 401 naming the missing one. It checks the id first. The v2 doors use it.
- `HTTPBearerWith401` answers 401 with `WWW-Authenticate: Bearer` when credentials are missing.

## Verifiers
- `verify_jwt_token` checks an access token, loads the user, and answers 401 if the user is gone.
- `verify_mock_token` accepts `mock_token_*` strings. It is for development.
- `verify_firebase_token` is a legacy name for `verify_token`. `init_firebase` only sets a flag and contacts no service.
- `TokenExpiredException` is an `HTTPException` subclass for an expired access token.

## Don't
- Don't call `verify_firebase_token` or `init_firebase` in new code.
