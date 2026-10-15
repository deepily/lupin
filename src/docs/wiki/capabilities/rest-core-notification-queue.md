---
capability: rest-core-notification-queue
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.notification_fifo_queue.NotificationFifoQueue@0506eb4e82
  - cosa.rest.notification_fifo_queue.NotificationItem@d457b88c99
  - cosa.rest.notify_rate_limiter.NotifyRateLimiter@27cc2b948d
  - cosa.rest.notification_expiry_sweeper.find_sweepable_ids@81e2e07cbd
---
# Notification queue, send limit and expiry dry run

The queue that holds notifications, the per-sender limit on sending them, and the read-only half of the expiry sweeper. Routing and delivery are on [[notification-delivery]].

## Queue
- `NotificationItem` is the light record kept in the queue; `to_dict` makes it JSON.
- `NotificationFifoQueue` extends `FifoQueue`. `push_notification` builds an item, inserts it by priority, logs it to the input-and-output table and emits one WebSocket event. `urgent` and `high` go to the front.
- `mark_played( notification_id )` records the play and its count. `get_next_unplayed( user_id )` returns the first unplayed one, for all users when the id is `None`.
- `get_user_notifications( user_id, include_played, priorities, oldest_first )` returns queue order by default, which is not time order. `oldest_first` sorts by creation time.

## Send limit
- `NotifyRateLimiter.check_and_record( source, max_per_window, window_seconds )` returns `(True, None)` and records the hit, or `(False, retry_after)` and records nothing.
- Hits older than the window are dropped first. `reset( source )` clears one source, or all when it is `None`.

## Expiry dry run
- `find_sweepable_ids( repo, grace_seconds )` returns the ids the sweeper may close, and writes nothing. A row counts only when `expires_at` is at least `grace_seconds` in the past.
- A naive `expires_at` raises `TypeError`. Nothing in production calls it; it shows what arming the sweeper would close.
