---
capability: rest-routers-notification-sender-conversations
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.notifications.get_senders_with_activity@40749619a5
  - cosa.rest.routers.notifications.get_visible_senders@aa352ff76d
  - cosa.rest.routers.notifications.get_sender_conversation@838be26b31
  - cosa.rest.routers.notifications.delete_sender_conversation@932f8418da
  - cosa.rest.routers.notifications.get_sender_conversation_by_date@77ad3d6c13
  - cosa.rest.routers.notifications.get_sender_date_summaries@a368c5c612
  - cosa.rest.routers.notifications.soft_delete_by_date@3503e51410
  - cosa.rest.routers.notifications.get_active_conversation@33a12fa49e
  - cosa.rest.routers.notifications.get_project_sessions@ddc95465c6
  - cosa.rest.routers.notifications.generate_session_gist@8d19a7a2a1
---
# Notification sender conversations

The per-sender conversation doors of `routers/notifications.py`, under `/api/notifications`. All need an API key or a JWT. Those with `{user_email}` also need the caller to be that user, and an unknown email is 404. See [[rest-routers-notification-user-inbox]].

## What it does
- `get_senders_with_activity` answers `GET /senders/{user_email}` with `sender_id`, `last_activity` and `count`, newest first. `hours` narrows it.
- `get_visible_senders` answers `GET /senders-visible/{user_email}`. It adds `new_count`, drops senders whose rows are all hidden unless `include_hidden`, and runs off the event loop.
- `get_sender_conversation` answers `GET /conversation/{sender_id}/{user_email}`: oldest first, within `hours` (default 24) of `anchor` or the sender's last activity.
- `delete_sender_conversation` answers `DELETE` on the same path and removes every row for that sender.
- `get_sender_conversation_by_date` answers `GET /conversation-by-date/...` with a map of `YYYY-MM-DD` to rows over `hours` (default 168). Hidden rows need `include_hidden`.
- `get_sender_date_summaries` answers `GET /sender-dates/...` with `date`, `count` and `new_count`, newest date first.
- `soft_delete_by_date` answers `DELETE /date/{sender_id}/{user_email}/{date_string}`. It hides the rows and keeps them. A bad date is 400.
- `get_active_conversation` answers `GET /active-conversation/{user_email}` with the newest sender id, or null.
- `get_project_sessions` answers `GET /project-sessions/{project}/{user_email}` with a row per session and `is_active` on the newest.
- `generate_session_gist` answers `POST /generate-gist` with a 3 to 4 word title from up to 5 abstracts then 5 messages. Empty input gives `Empty session`.

## Don't
- Don't use `delete_sender_conversation` to hide rows. It is permanent.

## Invariants
- Dates use the `app timezone` zone, so rows near midnight land on the local day.
