---
capability: rest-core-managed-bounce
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.managed_bounce_broadcast.format_dirty_clause@e8cd016e27
  - cosa.rest.managed_bounce_broadcast.boot_counter_path@ede01fca03
  - cosa.rest.managed_bounce_broadcast.emit_bounce_broadcast_in_process@248b396dac
  - cosa.rest.managed_bounce_broadcast.count_acked_sessions@1c944b76a8
  - cosa.rest.managed_bounce_broadcast.resolve_ack_timing@ca06cca794
  - cosa.rest.managed_bounce_broadcast.socket_match_key@a45dad265d
  - cosa.rest.managed_bounce_broadcast.missed_sessions@96d671b2dd
  - cosa.rest.managed_bounce_broadcast.wait_for_roster_coverage@6276124e1a
---
# Managed bounce broadcasts

The warning before a `:7999` bounce and the all-clear after it, as injectable logic. The scripts and lifecycle are on [[dev-server-lifecycle]].

## Warning
- `build_bounce_message( kind, ... )` builds the broadcast text for `warning` or `all-clear`. `poll_acks_until_satisfied` polls the acks until every recipient answered or the deadline.
- `format_dirty_clause( dirty_files )` folds `git status --short` output into one single-line clause, at most a cap of paths and then `; …(+N more)`. A clean tree gives `""`.
- `count_acked_sessions( entries, broadcast_id )` counts distinct sender sessions whose ack has the given `status`, `completed` by default. One recipient can write the same ack several times.
- `resolve_ack_timing( config_mgr, ... )` returns the ack deadline and poll interval, each falling back to the default passed in.

## All-clear
- `next_boot_id( counter_path )` adds one to the stored boot number and starts again at 1 when the file is bad.
- `boot_counter_path( project_root, server_label )` is the counter file under `io/managed-bounce/`. Each character outside letters and digits becomes `-`, and the ends are trimmed, so `:7999` and `:8000` use different files and `dev:7999` gives `boot-counter-dev-7999.txt`.
- `socket_match_key( session_id )` strips the `cc-listener-` prefix and keeps the short id, so roster ids and live-socket keys can be compared.
- `missed_sessions( expected_ids, present_ids )` returns the sorted full ids with no live socket.
- `wait_for_roster_coverage( roster_fn, present_fn, deadline_seconds, ... )` returns once every roster id has a socket, or at the deadline. The result has `reason` (`coverage` or `deadline`), `count`, `missing` and `curve`.
- `emit_bounce_broadcast_in_process( kind, message, ... )` sends through the commons and never raises. It returns `None` when commons is not wired and `{"error": ...}` when it throws. A refused or rate-limited send returns the normal result dict.

## Don't
- Don't compare roster ids with socket keys directly. They never match.
- Don't expect a fire after a straggler rejoins. The entry list is fixed at the firing moment.
