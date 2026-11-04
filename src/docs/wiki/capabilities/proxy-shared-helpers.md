---
capability: proxy-shared-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.utils.sync_notify.build_notify_kwargs@c8ebb5f85f
  - cosa.agents.utils.proxy_agents.base_responder.print_stats_table@7a51fbcabb
---
# Proxy shared helpers

Two small helpers the proxies share: the keyword builder for `voice_io.notify()` and the stats table printer. The notify call is in [[agent-voice-io]], and the responder base is in [[proxy-agent-base]].

## What it does
- `build_notify_kwargs( message, sender_id, priority='low', host=None, port=None, target_user=None, debug=False )` returns a dict.
- The dict always holds `message`, `sender_id`, `priority` and `debug`.
- It adds `host`, `port` and `target_user` only when they are not `None`, so `notify()` keeps its own defaults.
- `print_stats_table( title, stats )` prints a rule, the title, a rule, one `Label : value` row per counter in dict order, and a closing rule. A key such as `events_received` becomes the label `Events Received`.

## Don't
- Don't pass an empty string to mean unset. Only `None` leaves a key out.

## Invariants
- `build_notify_kwargs` returns a plain dict with no side effects. The notify call itself returns a bool.
- `BaseResponder.print_stats` calls the table printer with its `STATS_TITLE`, which a subclass can override.
