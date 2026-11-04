---
capability: rest-routers-dm-send-get-and-list
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.dm.DmSendRequest@fe90a26355
  - cosa.rest.routers.dm.post_dm_send@1f50a12d3f
  - cosa.rest.routers.dm.DmRespondRequest@8b037ad530
  - cosa.rest.routers.dm.post_dm_respond@8d2b716f91
  - cosa.rest.routers.dm.execute_dm_get@d0c435e5f8
  - cosa.rest.routers.dm.get_dm@e32e059549
  - cosa.rest.routers.dm.resolve_dm_list_scope@d759ae6e51
  - cosa.rest.routers.dm.list_dms@ae8fa330c2
---
# DM send, reply, get and list

The peer-DM doors of `routers/dm.py` under `/api/dm`. Each takes an API key or a JWT, and every read is scoped to the caller's user. See [[commons-and-dm]].

## What it does
- `DmSendRequest` is the body of `POST /api/dm/send`: `sender_session_id`, `body`, and the recipient by `recipient_persona` or `recipient_session_id`. Optional fields are `sender_persona`, `sender_icon`, `reply_to` and `thread_id`. `sender_project` is optional in the model, but a send without it is refused with 422.
- `post_dm_send` resolves the recipient, saves an `ai_to_ai` notification with the body inline, and pushes it. It answers 201 with `message_id` and `thread_id`. It answers 422 when the recipient is not found or `sender_project` is missing. It answers 413 when a rejecting length-gate window refuses a body as too long.
- `DmRespondRequest` is the same body with `reply_to` and `thread_id` required. `post_dm_respond` runs the same send path for `POST /api/dm/respond`.
- `execute_dm_get` is the logic behind `GET /api/dm/get?message_id=`. It is 400 for a non-UUID, and 404 for a missing row, another user's row, or a row that is not a peer DM. `get_dm` is the route.
- `resolve_dm_list_scope` turns `session_id` and `scope` into a recipient filter. A session id is cut to 8 characters. `scope=account`, or no session id, reads the whole account. A session id under 8 characters is a 400.
- `list_dms` answers `GET /api/dm/list`. With `thread_id` it returns that thread oldest first, otherwise the inbox newest first. `since` must be ISO 8601, else 400. `limit` is held to 1 to 200, a `scope` other than `session` or `account` is 422, and the reply echoes the scope applied.

## Don't
- Don't call `list_dms` without `session_id` and expect only your own mail. It then returns every DM on the account.
- Don't feed `get_dm` anything but the `message_id` from a send receipt, which is the stored row's id.

## Invariants
- A reply always names the message it answers and its thread.
