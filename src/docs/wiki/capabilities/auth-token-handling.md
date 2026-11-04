---
capability: auth-token-handling
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.js.auth.getAccessToken@5f9fd8ec2a
  - src.lupin_app.static.html.auth.js.auth.getRefreshToken@10fd7e178a
  - src.lupin_app.static.html.auth.js.auth.setTokens@32aafff4ce
  - src.lupin_app.static.html.auth.js.auth.clearTokens@e5036cf075
  - src.lupin_app.static.html.auth.js.auth.setUserData@f6935ad595
  - src.lupin_app.static.html.auth.js.auth.getUserData@8477c7963c
  - src.lupin_app.static.html.auth.js.auth.isTokenExpired@a6653cdc54
  - src.lupin_app.static.html.auth.js.auth.ensureValidToken@0f01cb178e
  - src.lupin_app.static.html.auth.js.auth.apiCall@81d5adb562
  - src.lupin_app.static.html.auth.js.auth.refreshAccessToken@480234e0ed
---
# Auth page token handling

`auth.js` is a plain script, not a module: every function is a global. The login, profile and admin pages load it. This page covers tokens and authenticated calls. State, actions and page guards are on [[auth-page-state-and-actions]] and [[auth-page-helpers]].

## Tokens and user data
- `getAccessToken`, `getRefreshToken`, `setTokens` and `clearTokens` use the `localStorage` keys `lupin_access_token` and `lupin_refresh_token`. `clearTokens` also removes `user_data`.
- `setUserData` and `getUserData` keep the user object as JSON under `user_data`. `getUserData` returns null when nothing is stored.

## Expiry and refresh
- `isTokenExpired` decodes the token payload and compares `exp` with the clock, less a 30 second buffer. A missing, malformed or exp-less token counts as expired.
- `ensureValidToken` returns false with no token, true for a live one, and otherwise calls `refreshAccessToken`. It never throws.
- `refreshAccessToken` posts the refresh token to `/auth/refresh` with no Authorization header and stores both returned tokens. It returns false on any failure.

## apiCall
- `apiCall( endpoint, method, data, includeAuth, retryCount )` builds the URL from the page origin. A page served by the test container therefore posts back to it.
- With `includeAuth`, the first attempt calls `ensureValidToken` and then sends the `Bearer` header. A body goes out only for POST, PUT and DELETE.
- A 401 triggers a refresh and a retry. After two retries, or when the refresh fails, it clears the tokens, goes to `/app/auth/login` and throws.
- Any other failed response throws with the server's `detail` or `message`.
