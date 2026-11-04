---
capability: auth-page-state-and-actions
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.js.auth.isAuthenticated@c399353a85
  - src.lupin_app.static.html.auth.js.auth.getCurrentUser@90aa91c6db
  - src.lupin_app.static.html.auth.js.auth.hasRole@faf8ccde0a
  - src.lupin_app.static.html.auth.js.auth.isAdmin@f1bd4f097a
  - src.lupin_app.static.html.auth.js.auth.login@09146957e8
  - src.lupin_app.static.html.auth.js.auth.logout@afbaef78d2
  - src.lupin_app.static.html.auth.js.auth.register@558bcd6233
  - src.lupin_app.static.html.auth.js.auth.changePassword@ef149ae48c
  - src.lupin_app.static.html.auth.js.auth.getSafeRedirectUrl@45d13d96fa
---
# Auth page state and actions

These `auth.js` globals answer who the user is and carry out login, logout, registration and password change. They sit on the calls of [[auth-token-handling]].

## State
- `isAuthenticated` is true when an access token exists. It does not check expiry.
- `getCurrentUser` returns the stored user, else fetches `/auth/me`, stores the result and returns it. It returns null when not authenticated or when the fetch fails.
- `hasRole` is true when that user's `roles` list holds the role. `isAdmin` is `hasRole( "admin" )`.

## Actions
- `login`, `register` and `changePassword` call `/auth/login`, `/auth/register` and `/auth/change-password`. `login` and `register` send no Authorization header; `changePassword` sends one, as a PUT.
- `login` stores both tokens, loads the user, and throws "Invalid login response" when the reply holds no tokens.
- `logout` calls `/auth/logout` with the refresh token, ignores a failure of that call, clears local state and goes to the login page.

## Redirects
- `getSafeRedirectUrl` returns the `redirect` query value only when it starts with `/app` or `/static/html/`. Otherwise it warns and returns `/app`, which stops an open redirect.

## Don't
- Don't treat `isAuthenticated` as proof the token is valid. Use `ensureValidToken` or `apiCall`.
