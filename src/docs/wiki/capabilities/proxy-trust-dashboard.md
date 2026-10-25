---
capability: proxy-trust-dashboard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.loadTrustStates@bd20f13bc2
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.loadRecentDecisions@a9ae90fe48
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.renderModeBar@c91100707f
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.updateModeStatusDot@93d0728bb4
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.onModeChange@a275ce754c
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.renderTrustCards@b69153a7e6
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.createTrustCard@36bd998f30
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.renderRecentDecisions@1bde947f80
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.getActionBadge@0e8339c155
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.getTrustBadge@59869765f6
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.getRatificationBadge@a0ce406c35
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.updatePagination@687229e64f
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.previousPage@d557288dca
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.nextPage@cd2a5adbd0
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.escapeHtml@3fad4cae5b
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.truncate@d3c031c48b
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.showElement@375c61ffcd
  - src.lupin_app.static.html.auth.admin.js.proxy-dashboard.hideElement@eca04984fe
---
# Proxy trust dashboard

`proxy-dashboard.js` draws the trust page of the decision proxy for the `swe` domain. It needs `auth.js` ([[auth-token-handling]]) and `admin-time.js` ([[admin-time-formatter]]). It keeps its state in script-level variables.

## Loading
- The script calls `requireAuth` when it loads. On `DOMContentLoaded` it reads the user's email and then calls `loadTrustStates` and `loadRecentDecisions`.
- `loadTrustStates` gets `/api/proxy/trust/<email>?domain=swe`, then draws the mode bar and the cards. A 404 draws empty default cards. Any other error shows a message.
- `loadRecentDecisions` with a category asks `/api/proxy/decisions/swe/<category>` for up to the page limit (50). With none it asks each of the six categories for 10, merges them, sorts newest first and keeps 50. A failed category counts as empty.

## Mode bar
- `renderModeBar` reads `/api/proxy/mode`, sets the dropdown to the effective mode and calls `updateModeStatusDot` with `has_running_job`. On failure it leaves `shadow`.
- `onModeChange` PUTs the new mode. `status: updated` says the running job changed, and any other status says the change is queued for the next job. The message clears after four seconds.

## Cards and table
- `renderTrustCards` draws one card per category through `createTrustCard`: level, label, success rate bar, totals and circuit breaker state (ok, tripped or cooldown). With no decisions it shows "No data".
- `renderRecentDecisions` draws the table of time, question (cut to 60 characters), action, trust level, confidence and ratification, then calls `updatePagination`.
- `getActionBadge`, `getTrustBadge` and `getRatificationBadge` make badge markup. `previousPage` and `nextPage` page the loaded list without fetching. `escapeHtml`, `truncate`, `showElement` and `hideElement` are local helpers.
