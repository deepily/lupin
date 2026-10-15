---
capability: web-client-auth-and-api
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.api.ApiClient.ApiError@6437b0ad51
  - src.lupin_app.static.js.multiplexer.api.ApiClient.ApiClientImpl@11b9397a58
  - src.lupin_app.static.js.multiplexer.api.ApiClient.createApiClient@4f1f7bc1d9
  - src.lupin_app.static.js.multiplexer.auth.AuthManager.NavigatorLockManager@bd5768cc4b
  - src.lupin_app.static.js.multiplexer.auth.AuthManager.ChainMutexLockManager@afbbea57f7
  - src.lupin_app.static.js.multiplexer.auth.AuthManager.AuthManagerImpl@b77bd08789
  - src.lupin_app.static.js.multiplexer.auth.AuthManager.createAuthManager@749069b081
  - src.lupin_app.static.js.multiplexer.auth.authGuard.redirectToLoginIfUnauthenticated@1ddc391b9e
  - src.lupin_app.static.js.multiplexer.auth.authGuard.logout@8f764b7039
  - src.lupin_app.static.js.multiplexer.auth.jwt.decodeSegment@b78f940cc2
  - src.lupin_app.static.js.multiplexer.auth.jwt.decodeJwtClaims@adca17e1ea
  - src.lupin_app.static.js.multiplexer.auth.jwt.jwtExpiryMs@28e52b0efd
  - src.lupin_app.static.js.multiplexer.auth.jwt.jwtEmail@396a0b4882
  - src.lupin_app.static.js.multiplexer.auth.jwt.jwtRoles@ca1e63045d
  - src.lupin_app.static.js.multiplexer.auth.jwt.jwtSub@d560516623
---
# Web client auth and API client

Token handling, the sign-in guard and the API client of the multiplexer page. [[web-client-transport-and-auth]] describes how they work together. `ApiClient.ts` imports `AuthManager.ts`. `AuthManager.ts` imports `jwt.ts`. `authGuard.ts` imports `AuthManager.ts`.

## What it does
- `ApiClient.ts`. `ApiError`: The error thrown when the server answers with a non-2xx status. `ApiClientImpl`: Sends authenticated JSON requests to the server's API with a timeout. `createApiClient`: Build the API client for one base URL and auth manager.
- `AuthManager.ts`. `NavigatorLockManager`: Lock manager backed by the browser's navigator.locks, shared across tabs. `ChainMutexLockManager`: A lock manager for places without `navigator.locks`, such as tests. `AuthManagerImpl`: The `AuthManager` behind `createAuthManager`. `createAuthManager`: Build an auth manager.
- `authGuard.ts`. `redirectToLoginIfUnauthenticated`: Send a visitor with no stored access token to the login page, then report whether it did. `logout`: Clear the stored tokens and go to the login page, with no `?redirect=`.
- `jwt.ts`. `decodeSegment`: Decodes one base64url segment to a UTF-8 string. `decodeJwtClaims`: Read the claims object from a JWT's payload segment, or return null if it is malformed. `jwtExpiryMs`: The token's `exp` claim in milliseconds since the epoch. `jwtEmail`: The token's `email` claim, or null when it is missing, empty or the token is malformed. `jwtRoles`: The string entries of the token's `roles` claim. `jwtSub`: The token's `sub` claim, which holds the user id.
