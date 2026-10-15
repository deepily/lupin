---
capability: rest-core-dm-experiment
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.dm_experiment.ExperimentPolicy@5eb9747bee
  - cosa.rest.dm_experiment.make_policy@7fafab9d7c
  - cosa.rest.dm_experiment.make_inactive_policy@60244f9908
  - cosa.rest.dm_experiment.load_default_policy@6fa7839f22
  - cosa.rest.dm_experiment.get_policy@a3c7c6788e
  - cosa.rest.dm_experiment.set_policy@2924e39051
  - cosa.rest.dm_experiment.reset_policy@34315d0c77
  - cosa.rest.dm_experiment.assignment_at@bc8bebbee6
---
# DM verbosity pilot policy

The runtime object for the two-arm direct-message verbosity pilot. It loads the committed schedule and the INI values once, so a send does not rebuild configuration. Direct messages are on [[commons-and-dm]].

## Policy
- `ExperimentPolicy` is an immutable snapshot of the slot table plus the override arm and reason, the reject threshold and the exempt senders.
- `ExperimentPolicy.assignment_at( arrival_utc )` returns a copy of the slot covering the instant (`slot_id`, `arm`, `local_hour`, `start_utc`), or `None` outside every slot. The instant must be timezone-aware, or `ValueError` is raised.
- `assignment_at( arrival_utc )` is the same lookup through the process singleton. Neither reads the clock; the caller resolves the arrival once, so one send scores against one arm.

## Building and holding it
- `load_default_policy` returns the no-slot policy when `is_suspended` is true, which is the default, and reads nothing then. Otherwise it reads the schedule JSON and the INI once. A missing or malformed schedule file also assigns nothing. A slot missing a required key raises `KeyError`.
- `get_policy` loads it on first use and returns the singleton. `reset_policy` drops it so the next call reloads; use it after editing the schedule or config and bouncing.
- `set_policy` replaces the singleton, as a test or operator seam.
- `make_policy( slots=..., override_arm=..., reject_threshold=... )` builds one from raw slots, for tests. An override arm outside the valid arms, `blind` and `rejecting`, becomes `None`.
- `make_inactive_policy` has no slots, so `assignment_at` is always `None`. Baseline send tests use it to stay independent of the wall clock.

## Don't
- Don't expect the pilot to run by default. `is_suspended` reads `dm experiment suspended` and answers true when unset or unreadable.
