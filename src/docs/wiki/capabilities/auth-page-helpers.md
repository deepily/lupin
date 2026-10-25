---
capability: auth-page-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.js.auth.showError@4fa3f660ea
  - src.lupin_app.static.html.auth.js.auth.hideError@a529e64e19
  - src.lupin_app.static.html.auth.js.auth.showSuccess@9aa7f5d18d
  - src.lupin_app.static.html.auth.js.auth.hideSuccess@ac05b08680
  - src.lupin_app.static.html.auth.js.auth.showLoading@a4bc0d76af
  - src.lupin_app.static.html.auth.js.auth.hideLoading@62b28067d3
  - src.lupin_app.static.html.auth.js.auth.requireAuth@1f8874e55d
  - src.lupin_app.static.html.auth.js.auth.requireAdmin@c62aed2f1d
---
# Auth page helpers

The last two groups in `auth.js`: message helpers and page guards. [[auth-token-handling]] and [[auth-page-state-and-actions]] cover the rest.

## Message helpers
- `showError` and `showSuccess` take an element id and a message. They set the text and show the element.
- `hideError` and `hideSuccess` clear the text and hide it.
- `showLoading` and `hideLoading` only change the display of the element. All six do nothing when the element is absent.

## Page guards
- `requireAuth` sends a visitor with no access token to `/app/auth/login`.
- `requireAdmin` calls `requireAuth`, then shows an alert and sends a non-admin to `/app/auth/profile`.

## Don't
- Don't count on a guard for security. It runs in the browser, and the server must enforce roles. `requireAdmin` does not wait for `requireAuth`'s redirect to finish.
