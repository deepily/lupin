---
capability: heartbeat-arbiter-plumbing
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.arbiter_gateway.LupinArbiterGateway@6eb9cacf70
  - cosa.agents.heartbeat_arbiter.arbiter_job.ArbiterGateway@1a80108b53
  - cosa.agents.heartbeat_arbiter.arbiter_job.owed_class_suppresses@359d8e594d
  - cosa.agents.heartbeat_arbiter.arbiter_journal.format_ts_local@c57a944303
  - cosa.agents.heartbeat_arbiter.arbiter_journal.make_log_fn@b2119361f0
  - cosa.agents.heartbeat_arbiter.arbiter_state.FleetEventAccumulator@b962a7eb44
  - cosa.agents.heartbeat_arbiter.arbiter_state.PingLedger@46765982a6
  - cosa.agents.heartbeat_arbiter.events_tail.load_offsets@10d03b41c8
  - cosa.agents.heartbeat_arbiter.events_tail.save_offsets@6570084c15
  - cosa.agents.heartbeat_arbiter.events_tail.tail_fleet_events@9f216552b2
  - cosa.agents.heartbeat_arbiter.events_tail.tail_session_file@d6895d3c87
  - cosa.agents.heartbeat_arbiter.lineage_carry.read_carry@d99b7e63de
  - cosa.agents.heartbeat_arbiter.lineage_carry.write_carry@841a588169
---
# Heartbeat arbiter plumbing

The small parts under [[heartbeat-arbiter]]: the commons seam, the journal line and per-edge memory. Also the file readers and writers that let state survive a restart.

## What it does
- `ArbiterGateway` is the protocol the arbiter talks to the commons through. It has four verbs: `who`, `send_to`, `post` and `read`. Tests inject a fake.
- `LupinArbiterGateway` is the production version over a `CommonsStore`. `send_to` posts to the recipient's DM topic with a `kind` of `arbiter-ping`. Caller metadata is merged over that.
- `post` stamps `arbiter-surface`. `read` only observes. `dm_topic_for` builds `dm-` plus the accent-stripped persona slug, so "María" and "Maria" share one topic.
- `owed_class_suppresses` is true only for the blocked-on-user and done classes. Anything else, including unknown, does not suppress an escalation.
- `make_log_fn` returns a logger that prints one JSON object per event with `ts`, `ts_local`, `service`, optional `loop` and the fields. `format_ts_local` renders the local stamp.
- A bad time zone name journals one `journal_tz_invalid` line and falls back to UTC.
- `FleetEventAccumulator` keeps a bounded tail of event records per session across polls. `PingLedger` remembers the last ping per edge and drops edges that are no longer active.
- `tail_session_file` reads only new complete lines from a byte offset. A shrunk file restarts at zero. `tail_fleet_events` does that for every session file.
- `save_offsets` and `load_offsets` keep those offsets in a JSON file, so a restart does not replay old events. Both return a safe empty or false result on error.
- `read_carry` and `write_carry` persist the map from session to last known manager. `write_carry` writes through `write_json_atomic` ([[utils-atomic-json]]). A reaped worker's row then stays under its manager after a restart.

## Don't
- Do not expect `write_carry` to merge. The caller passes the already pruned map and the file is replaced.
- Do not expect `write_carry` to swallow errors. It raises `OSError` on an unwritable path, and the caller journals that.
