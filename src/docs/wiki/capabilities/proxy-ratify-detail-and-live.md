---
capability: proxy-ratify-detail-and-live
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.getActionBadge@0e8339c155
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.getDataOriginBadge@e5eecc1f3a
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.getTrustBadge@59869765f6
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.getRatificationBadge@2ae4588233
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.showDecisionDetail@cb78cabbd2
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.closeDetailModal@715cf09c10
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.modalApprove@ee3d711b5c
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.modalReject@4233876a5d
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.escapeHtml@3fad4cae5b
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.formatDataOrigin@d5540bd0ac
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.truncate@d3c031c48b
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.showElement@375c61ffcd
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.hideElement@eca04984fe
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.connectProxyWebSocket@7389fa075d
---
# Proxy ratification detail and live refresh

The detail view, badges and refresh triggers of [[proxy-ratify-page]]. Row actions are on [[proxy-ratify-actions]].

## Detail view
- `showDecisionDetail( id )` finds the loaded decision and remembers its id. It fills the modal with category, domain, source, action, trust level, confidence, sender, time, reason, question and decision value. It clears the feedback box and opens the modal. An unknown id does nothing.
- `modalApprove` and `modalReject` ratify the remembered id with the trimmed feedback text, close the modal, show a message and reload. `closeDetailModal` hides it and forgets the id.
- A click outside any modal hides it and forgets the detail id.

## Badges and text
- `getActionBadge`, `getDataOriginBadge`, `getTrustBadge` and `getRatificationBadge` return badge markup, with a default class for an unknown value. `formatDataOrigin` gives the long label, such as "Organic (Live)".
- `escapeHtml` returns an empty string for null. `truncate` adds three dots when it cuts. `showElement` and `hideElement` set display by id.

## Live refresh
- The page reloads the list when the tab regains focus.
- `connectProxyWebSocket` opens `/ws/queue/proxy ratify`, sends an auth request with the access token and subscribes to `proxy_decision_new` only. Each such event calls `loadPending`. It reconnects five seconds after a close.
