---
capability: web-client-render-items-notification-item
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.notificationItem.renderNotificationItem@aa77b42126
  - src.lupin_app.static.js.multiplexer.render.templates.notificationItem.expiredBadge@fd988874c8
  - src.lupin_app.static.js.multiplexer.render.templates.notificationItem.cornerPauseButton@35b3ce7da1
  - src.lupin_app.static.js.multiplexer.render.templates.notificationItem.cornerStopButton@62f089c470
  - src.lupin_app.static.js.multiplexer.render.templates.notificationItem.proxyRatifyLink@09db34d6d9
  - src.lupin_app.static.js.multiplexer.render.templates.notificationItem.abstractIndicator@d2d8155c26
  - src.lupin_app.static.js.multiplexer.render.templates.predictionVoteControls.renderPredictionVoteControls@54c28368e7
---
# Notification item and vote controls

Builds one chat-bubble row for a notification, plus the thumbs vote buttons a prediction hint can carry.

## Item
- `renderNotificationItem( notification, opts )` returns a `.sender-message` div with `data-id-hash` set. `opts` takes `appTimezone` and `predictionVote`. `dateAccordion.ts` calls it; `senderCard.ts` only forwards the options.
- The class adds `incoming` or `outgoing` from `direction` (default incoming), and `expired-response` when `was_expired` is true.
- It shows `time_display` or the formatted `ts`, and the message as inline markdown. A progress group wraps this in a head with a toggle and an empty history block.
- `expiredBadge()` returns the "EXPIRED" span nested after the message text.
- `abstractIndicator( abstract )` returns a clipboard span whose `data-abstract` holds the text. The template attaches no listener; `ReadingPaneRenderer.ts` and `abstractTooltip.ts` read it on click.
- `cornerPauseButton( idHash )` and `cornerStopButton( idHash )` return buttons carrying `data-notification-id`. They are added to incoming bubbles only and carry no listener.
- `proxyRatifyLink( groupId )` returns an "Open Ratification →" anchor with `data-batch-id`. It is added only when the progress group id starts with `pr-`.

## Votes
- `renderPredictionVoteControls( opts, handlers )` returns null when `notificationId` is empty or `confidencePct` is under `PREDICTION_VOTE_MIN_PCT`.
- Otherwise it returns a `.prediction-hint-vote` div with up and down buttons. A click marks that button `selected`, adds `voted`, and calls `handlers.onVote( dir )`.
- A `castVote` in `opts` pre-selects the matching button. `actionRequiredChrome.ts` and the item both call it.

The item decides which controls exist, and the list renderer's delegated handler gives the corner buttons and ratify link their behaviour. With a `prediction_hint`, the item calls the vote template with `notificationId`, `confidencePct` and `castVote` (from its optional `predictionVote` option). The handler is `onVote`. The template can return nothing.
