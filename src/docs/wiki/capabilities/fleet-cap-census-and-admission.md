---
capability: fleet-cap-census-and-admission
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.fleet_size_cap.census@5b4dc5d3dc
  - lupin_mcp.fleet_size_cap.config_file_path@1cb72e1ceb
  - lupin_mcp.fleet_size_cap.counted_as_manager@d701eecb54
  - lupin_mcp.fleet_size_cap.counting_classifier_for@08282d279a
  - lupin_mcp.fleet_size_cap.default_counting_classifier@39278acff0
  - lupin_mcp.fleet_size_cap.default_disk_cap_reader@3a409acbfe
  - lupin_mcp.fleet_size_cap.main_checkout_ini_path@12dd354226
  - lupin_mcp.fleet_size_cap.pool_size@aa9123b9d7
  - lupin_mcp.fleet_size_cap.read_counting_fields@d5da947036
  - lupin_mcp.fleet_size_cap.resolve_fleet_cap@3222e46161
  - lupin_mcp.fleet_size_cap.resolve_fleet_ceiling@282414120a
  - lupin_mcp.fleet_cap_admission.admit_under_lock@b787a3631c
  - lupin_mcp.fleet_cap_admission.main@5d33f13700
  - lupin_mcp.fleet_cap_admission.prune@4fa47a062f
  - lupin_mcp.fleet_cap_admission.read_reservations@a0891cf037
  - lupin_mcp.fleet_cap_admission.release@78db64b191
  - lupin_mcp.fleet_cap_admission.reservation_dir@2339ffe5ac
  - lupin_mcp.fleet_cap_admission.unmaterialised_reservations@f1813bceab
---
# Fleet cap census and launch admission

How many seats the fleet may hold, who counts as a manager, and the launch-time reservation that keeps two launches from taking the last seat. The page [[seat-lifecycle]] covers the whole path.

- `config_file_path` and `main_checkout_ini_path` name the one configuration file the cap is read from and written to, in the container and on the host alike.
- `default_disk_cap_reader` reads `cc session fleet size cap` fresh from that file, because the configuration manager is a long-lived singleton. `resolve_fleet_cap` clamps the result into 1 to the ceiling, with `disk_fn` winning over the manager.
- `resolve_fleet_ceiling` reads `cc session fleet size cap maximum`, never below 1. `pool_size` counts the personas that carry a voice id. The pool is not a ceiling on seats.
- `counted_as_manager( role, spawned_by )` is true for role `manager`, or for a session that declares neither a role nor a lineage. `read_counting_fields` returns None when a bridge cannot be read, not a pair of Nones.
- `default_counting_classifier` labels a session manager, worker or unknown. `counting_classifier_for( sessions )` reads each session's own bridge file once.
- `census( sessions, is_manager_fn, unreadable )` returns `total`, `managers`, `workers` and `unknown`. A session whose classification raises counts as unknown.
- `refusal_for_spawn( requested, counts, cap )` is None when the spawn fits. Otherwise the message names the cap, the total, the split and what would fit.
- `reservation_dir` is `fleet-admissions` beside the session bridges. `read_reservations` lists the files and skips any it cannot parse.
- `unmaterialised_reservations` drops a reservation whose bridge now exists or that is older than the TTL. `prune` deletes the files not kept, and `release` drops one for a launch that failed.
- `admit` decides one launch: it is admitted when live seats plus reservations plus one fit the cap. `admit_under_lock` serialises that across launchers and still decides if the lock fails.
- `main` is the command line `start-cc-with-tmux.sh` runs. It exits 0 admitted, with a warning when over the cap without `--headless`. It exits 3 when over the cap with it, or when skeleton crew is on and the launch is not a person at a terminal. It fails open.
