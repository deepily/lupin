---
capability: web-client-render-action-required-draft
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredDraft.draftAtReveal@434946fa7f
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredDraft.visibleChoice@c258da4562
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredDraft.batchAnswers@6c50135715
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredDraft.routeLength@f1a5bc1777
---
# Action-required draft at reveal

Reads the answer an action-required card's controls hold at the moment its forecast fold opens. With it the server can tell an unaided answer from one switched after the forecast showed. It reads only. Nothing is marked invalid and no control changes. The route that stores it is in [[rest-prediction-routes-and-outcome]]. The card forms are in [[web-client-render-action-required-interactive]].

## What it does
- `draftAtReveal( item, widget )` returns `{ value }`, the string the submit button would send, or null. A yes/no card returns null, because choosing is submitting. An open-ended card gives its trimmed text, or null when the box is empty.
- A multiple-choice card gives the answers saved so far plus the question on screen. A batch card gives its non-empty fields. Both are the JSON text of `{ answers: { header: pick or [picks] } }`. The result is null when no answer is held, or when the draft runs past `DRAFT_MAX_CHARS` (4096) as the route counts it.
- `visibleChoice( item, widget )` reads the question on screen as Next would save it. It returns `{ header, value }`, a list for a multi-select question and a single string otherwise. It returns null when nothing is chosen. It reads the ticks through `checkedChoices`, so a ticked Other counts through its trimmed text.
- `batchAnswers( widget )` returns `{ header: trimmed text }` for each batch field that holds text.
- `routeLength( draft )` counts a draft the way the route does, as Python's `json.dumps` writes it. A space follows the colon. Every character past `~` is a six-character escape, so a character beyond Basic Latin counts six and an emoji counts twelve.

## Don't
- Don't count a draft with `String.length`. A draft the client thinks is short enough can be over the server's limit, and the route refuses it.
- Don't call it for a card that is not on screen as an interactive widget. `ActionRequiredRenderer` guards the call and sends no draft when reading throws.

## Invariants
- It never returns an empty value. An empty answer is null, and a null draft sends the fold-open report as it was.
- The first fold-open's draft is the one kept; `PredictionVoteStore.reportSeen` sends it again on a retry ([[web-client-stores-panes]]).
- `notifications.js` has its own copy of these rules for the older page ([[web-client-notifications-script]]).
