---
capability: rest-data-repos-notifications
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.repositories.notification_repository.NotificationRepository@3fd00bac37
  - cosa.rest.db.repositories.fcm_token_repository.FcmTokenRepository@396b382c23
  - cosa.rest.db.repositories.podcast_proxy_spent_repository.PodcastProxySpentRepository@85541c6c22
---
# Notification repositories

Three repositories hold what a notification needs after it is sent: the notification rows and the phone push tokens. The third is a record that a podcast card has already started its job. Delivery and routing are in [[notification-delivery]].

## What it does
- `NotificationRepository.create_notification` writes a row in state `created`. Reads cover a recipient's list, the peer-DM inbox and one DM thread, pending asks, and conversation windows by sender or by date.
- The "missed while away" family is `get_undelivered_for_recipient` (state `created` or `queued`, oldest first, not hidden), `count_undelivered_for_recipient` and `dismiss_undelivered_for_recipient`. Dismiss sets `is_hidden` and leaves the state alone.
- `get_answers_owed_for_persona` returns answered asks not yet handed back, oldest answer first. `mark_answer_delivered` stamps the hand-back.
- `update_state`, `update_response` and `mark_expired` change one row. `get_expired_notifications` lists delivered rows past their expiry.
- `find_live_unpark_card` and `find_live_podcast_card` find the newest card still waiting for an answer.
- `FcmTokenRepository.upsert_token` is one `INSERT .. ON CONFLICT (token) DO UPDATE`, so a re-registration refreshes the row. `get_tokens_for_user` returns every device of a user.
- `PodcastProxySpentRepository.claim` adds a row for a card id and returns `False` when one exists. `release` takes it back.

## Don't
- Don't pass `expected_state=None` to `mark_expired` where a human answer may be arriving. With a state it refuses to overwrite a row that moved on, and returns `None`.
- Don't use `apply_default=True` on the orphan-sweeper path. Nobody waited, so no default answer should be stamped.
- Don't let two callers claim a card without a commit between the claim and the queueing. The second start must see the first.

## Invariants
- Writes flush and never commit.
- `claim` runs in a nested transaction, so a clash is raised at the claim and not at the caller's commit.
- `claim_after_window` removes only a claim older than its cutoff, then claims; the primary key picks one winner.
