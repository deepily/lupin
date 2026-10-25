---
capability: heartbeat-outreach-throttles
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.operator_gate_routing.digest_due@ce9f290dde
  - cosa.agents.heartbeat_arbiter.operator_gate_routing.partition_by_urgency@6bd1697f88
  - cosa.agents.heartbeat_arbiter.operator_gate_routing.route_operator_gates@a2a822735e
  - cosa.agents.heartbeat_arbiter.outreach_ledger.add_pending@13da3a5485
  - cosa.agents.heartbeat_arbiter.outreach_ledger.read_pending@d388fa0c00
  - cosa.agents.heartbeat_arbiter.outreach_ledger.record_attempt@0fddc36f55
  - cosa.agents.heartbeat_arbiter.outreach_ledger.remove_pending@69ad5dea3c
  - cosa.agents.heartbeat_arbiter.outreach_ledger.write_pending@b8cfa1f89a
  - cosa.agents.heartbeat_arbiter.ping_throttle.backoff_for_attempt@6111a5a436
  - cosa.agents.heartbeat_arbiter.ping_throttle.edge_key@02b176eb11
  - cosa.agents.heartbeat_arbiter.ping_throttle.in_window@5203c800fa
  - cosa.agents.heartbeat_arbiter.ping_throttle.should_ping@67cc4bd23d
  - cosa.agents.heartbeat_arbiter.ping_throttle.trailing_window_allows@ddcf8ecf09
  - cosa.agents.heartbeat_arbiter.ping_throttle.under_global_cap@56cdc5aa07
---
# Heartbeat outreach throttles

The pure rules and the small ledger that keep [[heartbeat-arbiter]] from flooding people: per-edge backoff, rate caps, operator-gate routing and a file of undelivered messages. The rule functions only decide and never raise.

## What it does
- `edge_key` joins holder, awaited peer and reason into one key, treating `None` as empty.
- `backoff_for_attempt` returns 60, 300, 900 then 3600 seconds by attempt number, clamped at the last. A negative attempt counts as zero.
- `should_ping` is true if the edge was never pinged or the backoff has passed. Unusable timestamps give false.
- `under_global_cap` is true while the recent arbiter DM count is below the cap.
- `in_window` keeps send times no older than the window. Future or unusable ones are dropped.
- `trailing_window_allows` allows one more send per recipient while fewer than `max_messages` fall in the window. A zero limit disables it and always allows.
- `partition_by_urgency` sorts open operator gates into `interrupt`, `digest` and `queue` by urgent, normal and low. A missing or unknown urgency goes to the digest.
- `digest_due` is true with no prior digest or once the cadence has passed, inclusive. A future stamp is not due.
- `route_operator_gates` combines both. The digest list is empty until the cadence has elapsed, and the queue is never pushed.
- `read_pending` returns the ledger of undelivered owner messages, or an empty dict on any error.
- `write_pending` replaces the file atomically through `write_json_atomic` ([[utils-atomic-json]]) and raises `OSError` if it cannot write.
- `add_pending` sets or refreshes one entry with one attempt. `record_attempt` bumps the attempt count and outcome, and does nothing for an unknown id. `remove_pending` deletes an entry.

## Don't
- Do not expect these functions to remember anything. The caller keeps the last-ping times and send history.
