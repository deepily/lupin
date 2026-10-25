---
capability: heartbeat-self-respin-markers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.self_respin_observer.SelfRespinVerdict@1780b0a196
  - cosa.agents.heartbeat_arbiter.self_respin_observer.SelfRespinAssessment@24a3b7429a
  - cosa.agents.heartbeat_arbiter.self_respin_observer.effective_deadline@0be75b507b
  - cosa.agents.heartbeat_arbiter.self_respin_observer.missing_marker_fields@f82862c275
  - cosa.agents.heartbeat_arbiter.self_respin_observer.build_marker_dict@f75a1f93d7
  - cosa.agents.heartbeat_arbiter.self_respin_observer.classify_marker@ce2aeb0869
  - cosa.agents.heartbeat_arbiter.self_respin_observer.wake_proof_path@a6e40e65a7
  - cosa.agents.heartbeat_arbiter.self_respin_observer.read_wake_proof@0cb75967a1
  - cosa.agents.heartbeat_arbiter.self_respin_observer.keys_sent_path@3ada1f8bc6
  - cosa.agents.heartbeat_arbiter.self_respin_observer.read_keys_sent_at@1b23ae585c
  - cosa.agents.heartbeat_arbiter.self_respin_observer.with_keys_sent@386f6cacd0
  - cosa.agents.heartbeat_arbiter.self_respin_observer.read_markers@e5ae276b8d
  - cosa.agents.heartbeat_arbiter.self_respin_observer.observe_fleet_self_respin@28ca2ecba6
---
# Heartbeat self-respin markers

A manager that clears itself cannot report whether it came back. Before it clears, it writes a marker. An outside observer judges the marker against the live context pressure. The loop that acts on it is in [[heartbeat-self-respin-loop]].

## What it does
- `build_marker_dict` builds the marker the verb writes before the clear: identity, fire time, pre-clear status and percent, memento and wake nonce. `expected_return_by` is fire time plus delay plus grace.
- `missing_marker_fields` lists contracted keys absent from a marker read back. It tests presence, not truthiness, so a `None` nonce is fine.
- `read_markers` reads every marker under the fleet data roots and skips unreadable ones.
- `wake_proof_path` and `read_wake_proof` find the proof the reborn seat writes. The proof echoes the marker's nonce, which a peer's DM cannot forge.
- `keys_sent_path`, `read_keys_sent_at` and `with_keys_sent` read the send stamp from an empty sidecar file's mtime. An explicit `keys_sent_at` in the marker wins.
- `effective_deadline` re-anchors the deadline on the send stamp when it is usable and later than the fire time. Otherwise it uses the fire anchor plus any idle wait.
- `classify_marker` is pure and returns a `SelfRespinAssessment` with one `SelfRespinVerdict`.
- `MALFORMED_MARKER` alarms for an unusable fire or return time, and is checked first. `IDENTITY_MISMATCH` alarms when another seat answers under the same session id.
- `RETURNED` needs the over-budget to within-budget move, a fresh turn after the fire, and a proof with the marker's nonce.
- `DEAD_NO_RETURN` alarms at the deadline. `PENDING` is the rest.
- `RETURNED` also records latency and a late flag. Lateness does not turn it into an alarm.
- `observe_fleet_self_respin` classifies every marker on disk. An unreachable pressure fetch leaves each marker with no record.

## Don't
- Do not take the verdict as proof of aliveness alone. A seat that never cleared is also alive.
