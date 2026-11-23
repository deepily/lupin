# Capture fields: the trace (23 Nov 2026)

Plan: "The capture fields" in the answer-signal pipeline plan (commit d569aba91). Traced in the seat tree at f3111d4cd.

## Verdict: no new column, no migration

| Field | Where it already lives | New storage |
|---|---|---|
| `recommendation` | `notifications.response_options.questions[].options[]`: a `recommended` flag or a "(Recommended)" label suffix. Read by `episode_view._is_recommended` | none, derived on read |
| displayed highlight | `notifications.response_default`, or a question's own `default_value` (`episode_view.fields_of` already resolves it to an option id) | none |
| option order | the order of `response_options.questions[].options[]`; `present_choices( … response_options_extra … )` only merges extra keys beside `questions`, so it keeps that order | none |
| `input_route` | not stored anywhere today | one key, `input_route`, inside `notifications.response_value` (JSONB, already free-form) |

## How an answer is stored today

1. The web client (`ActionRequiredStore.respondAndAwait`) POSTs `{ notification_id, response_value }`, and `response_value` is always a string. Yes/no and open-ended send the bare answer. Multiple choice and batch send `JSON.stringify( { answers: { header: value } } )`.
2. `_stored_response_dict` wraps a string as `{ value, source: "ui" }` and adds `answered_by`. A dict is stored as sent.
3. `NotificationRepository.update_response` writes it to `response_value`. A timeout writes `{ value: response_default, source: "timeout_default" }` in `notification_repository` instead, and never passes the answer door.

## Findings

- **The route cannot ride only beside `answers`.** Yes/no and open-ended answers are bare strings with no map. The route therefore travels as a top-level request key, `input_route`, stored beside `value`. It is a string for a single-question card. It is `{ header: route }` for a multi-question card.
- **`parse_field_selections` tolerates a sibling key** beside `answers`, in the JSON string and in the stored wrapper. Test added (`test_parse_field_selections.py`).
- **There is no WebSocket answer path.** `routers/websocket.py` has no answer message. Voice is the card's microphone filling a text field, then an ordinary POST. The voice route is therefore a client-side tag on that POST. The plan's "WebSocket answer path with a voice route tag" cannot be tested as written; the test posts a `voice` route to the answer door.
- **Proxy answers use the same door** (`rest_submitter.submit_notification_response`, a Bearer login). The server cannot tell a proxy from a person by credentials, so "never set for a proxy" holds because the proxy never sends `input_route`. The door stores the key only when the switch is on and the value is valid.
- **Actor on a card with no `prediction_decisions` row.** A timeout is readable from `notifications.response_value.source`. A proxy answer is marked only by `prediction_decisions.answer_source = "proxy"` (`decision_proxy/responder.py`); on `notifications` alone it reads `source: "ui"`. So a proxy answer on a card with no decision row cannot be told from a human answer. This is a gap, named, not bridged.
