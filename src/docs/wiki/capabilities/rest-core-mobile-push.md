---
capability: rest-core-mobile-push
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.fcm_push_pause.PushPauseController@fcc21accc2
  - cosa.rest.fcm_push_pause.init_controller@c1f94e208c
  - cosa.rest.fcm_push_pause.get_controller@3f5d1c394f
  - cosa.rest.fcm_wake_service.FcmWakeService@ad1f0bf8da
  - cosa.rest.fcm_wake_service.build_wake_payload@68dcf04468
---
# Mobile wake push and its pause

A content-free push that wakes the mobile app when notifications are waiting, and an in-memory switch that turns it off. Delivery of the notifications themselves is on [[notification-delivery]].

## Wake service
- `build_wake_payload( reason )` returns `{type, reason, ts}`, all strings, with `type` equal to `ws_wake`. The reason must be `undelivered` or `reconnect-hint`, else `ValueError`.
- `FcmWakeService.maybe_send_wake( user_id, reason )` returns the outcome: `disabled`, `paused`, `mobile_ws_live`, `deferred`, `debounced`, `no_tokens` or `submitted`.
- A notify inside a debounce window schedules one trailing wake and later ones collapse onto it. The trailing wake re-runs the whole policy, so a device that reconnected is not woken.
- It never raises and never blocks on the network; the send runs on an executor. `shutdown` cancels pending wakes and stops the executor.

## Pause
- `PushPauseController.pause( minutes, user, loop )` sets `fcm wake push enabled` false in memory. `minutes` is 1 to 1440 and arms a timer, or `None` for no timer. A new pause replaces the old.
- `resume( user )` restores the value the key had at startup, not a fixed true, and cancels the timer. `status` returns `paused`, `resumes_at`, `set_by`, `set_at` and the live `push_enabled`.
- Nothing reaches the INI file, so a restart ends a pause. `shutdown` logs a pause that was still active.
- `init_controller( config_mgr )` builds the singleton at startup. `get_controller` returns it, and builds one lazily if startup did not.

## Don't
- Don't call `get_controller` first and trust the resume value. Only startup init guarantees it is the boot value.
