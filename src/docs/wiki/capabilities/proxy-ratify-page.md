---
capability: proxy-ratify-page
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.loadPending@fda0e72517
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.ratifyDecision@3eac608d8a
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.deleteDecision@72b3fec381
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.renderSummaryCards@53a9e5e526
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.computeApprovedToday@107fe389c2
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.computeRejectedToday@c8d1e068da
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.renderTable@4122694e31
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.showEmptyState@3013bc5af0
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.applyFilters@c5e0fa8ddd
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.clearFilters@2d800deb72
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.updatePagination@687229e64f
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.previousPage@d9d7427514
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.nextPage@90b889e090
---
# Proxy ratification page

`proxy-ratify.js` lists the decisions the proxy has made so a person can ratify them. It needs `auth.js` ([[auth-token-handling]]) and `admin-time.js` ([[admin-time-formatter]]). Row actions are on [[proxy-ratify-actions]], and the detail view, badges and live refresh on [[proxy-ratify-detail-and-live]].

## Loading
- The script calls `requireAuth` when it loads. After `DOMContentLoaded` it reads the user's email and calls `loadPending`.
- `loadPending` gets `/api/proxy/pending/<email>`, keeps the decisions, draws the summary cards and applies the filters. A 404 draws empty cards and the empty state, and any other error shows a message.
- `ratifyDecision( id, approved, feedback )` POSTs to `/api/proxy/ratify/<id>` with `approved` and `user_email` in the query, and `feedback` only when given. `deleteDecision` sends DELETE to `/api/proxy/decision/<id>`.

## Summary and table
- `renderSummaryCards` shows the server's pending total and the age of the oldest. The approved and rejected counts come from `computeApprovedToday` and `computeRejectedToday`, which count loaded rows ratified on today's UTC date.
- `renderTable` draws one page of 25 rows with a checkbox, origin, category, question (cut to 80 characters), action, trust level, confidence, age and three buttons. A click on the row, but not on the checkbox or buttons, opens the detail view.
- `showEmptyState` shows the empty panel and hides the table and the pager.

## Filters and paging
- `applyFilters` keeps rows matching the four selectors: origin, category, trust level and action. It resets to page one, clears the selection and redraws.
- `clearFilters` blanks the selectors and applies. `updatePagination` hides the pager at one page or fewer. `previousPage` and `nextPage` move within the filtered list.
