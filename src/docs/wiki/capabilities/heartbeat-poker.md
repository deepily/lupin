---
capability: heartbeat-poker
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_poker_job.HeartbeatPokerJob@0b6e68006b
  - cosa.agents.heartbeat_poker_job.RecipientSpec@0ff47d7734
  - cosa.agents.heartbeat_poker_job.Clock@b12bb6b742
  - cosa.agents.heartbeat_poker_job.SystemClock@dd6dc72e64
  - cosa.agents.heartbeat_poker_job.CommonsGateway@629f30a94e
  - cosa.agents.heartbeat_poker_commons_gateway.LupinCommonsGateway@941cf4bc45
---
# Heartbeat poker

A queue job that pokes a set of sessions on a fixed cadence until a termination signal, a cancel or a time cap. It is generic and never branches on a recipient's role. [[heartbeat-arbiter]] is the fleet-wide watcher; this one serves one workstream.

## What it does
- `RecipientSpec` is a frozen record of identifier, identifier type (`persona` or `session_id`) and role (`manager`, `observer` or `watcher`). A bad value raises `ValueError`.
- `HeartbeatPokerJob` is an agentic job. Its constructor rejects empty recipients, non-positive cadence or cap, a dead-man count under one, no signal kinds and no topic.
- Each pass checks cancel, then the 12-hour default hard cap, then a termination kind posted on the topic after start. Each exit returns normally, so the job ends `done`.
- Then it scores the last tick and sends `{kind: heartbeat, workstream, role}` to every recipient. It sleeps one cadence.
- A recipient is answered when its last commons post is later than the tick. Otherwise its silent streak grows.
- At the dead-man count the job notifies once per streak and keeps poking. A later answer resets the streak.
- `Clock` is the time seam: `monotonic`, `now_iso` and `sleep`. `SystemClock` is the real one.
- `CommonsGateway` is the commons seam: `send_to`, `last_post_ts` and `read_since`.
- `LupinCommonsGateway` is the production gateway. `send_to` posts to `dm-<persona slug>` first, then pushes to `/api/dm/send`. The disk post is the record.
- A failed push is logged as `HEARTBEAT_POKE_SEND_FAILED` on stderr and does not lose the poke.
- `last_post_ts` matches a session id exactly, or a persona by canonical key, so "María" matches "Maria".
- `from_environment` reads the API key file and raises `FileNotFoundError` when it is absent.

## Don't
- Do not treat the dead-man escalation as an exit. It never stops the loop.
