---
capability: heartbeat-turn-age-watchdog
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.turn_age_watchdog.TurnAgeWatchdog@d52d820eb4
  - cosa.agents.heartbeat_arbiter.turn_age_watchdog.age_seconds@5b15a96db6
  - cosa.agents.heartbeat_arbiter.turn_age_watchdog.find_dangling_tool_use@8ffa9082f8
---
# Heartbeat turn-age watchdog

A standalone daemon beside [[heartbeat-arbiter]] that spots a held turn. That is a tool call with no result in the transcript, in a pane that has stopped streaming. It tells the operator once per call.

## What it does
- `find_dangling_tool_use` scans transcript entries and returns the id and timestamp of the final `tool_use` whose id never appears as a `tool_result`. It returns nothing if there is no tool call or the last one got a result.
- Only the final call counts, so an earlier unanswered call does not flag a turn that moved on. Malformed entries are skipped.
- `age_seconds` returns the age of an ISO-8601 stamp, treating a trailing `Z` as UTC. A missing or unparseable stamp gives `None`, so it is never a candidate.
- `TurnAgeWatchdog` is off unless `arbiter turn age watchdog enabled` is true. `start` spawns a daemon thread that sweeps once per arbiter poll.
- `sweep_once` checks each live session's transcript. A dangling call older than the threshold, 600 seconds by default, is a candidate unless the pane is streaming.
- Each candidate sends one advisory per session and tool call. The one-shot key is cleared when the call resolves.
- A failure on one session is skipped and the sweep continues. `stop` is safe if never started.

## Don't
- Do not expect it to act on a held turn. It only advises.
