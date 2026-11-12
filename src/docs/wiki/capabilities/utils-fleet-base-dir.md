---
capability: utils-fleet-base-dir
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.fleet_base_dir.fleet_base_dir@c65943676e
---
# Fleet base directory resolver

One function the arbiter and self-respin code share to pick the folder their markers, receipts and samples live under. The hook library keeps its own `_resolve_base_dir` in `heartbeat_hold.py`, because a hook must not import `cosa`; that one returns a Path and creates the folder.

## What it does
- `fleet_base_dir( base_dir, repo_root )` returns `base_dir` unchanged when it is not None.
- Otherwise it returns the fleet data folder of `repo_root` as a string. With no `repo_root` it uses the ambient project root.
- `respin_wake_check`, `self_respin_observer` and `self_respin_core` keep the name `_resolve_base_dir` as a one-line call to it.

## Don't
- Don't use it for the events folder; `heartbeat_events` keeps its own, which is not under the fleet data root.

## Invariants
- It imports the hook library lazily, so it stays a leaf.
