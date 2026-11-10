---
capability: job-host-snapshot
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.host_snapshot.crontab_text@02fd92b2cc
  - lupin_mcp.host_snapshot.unit_state@4d25f83c92
  - lupin_mcp.host_snapshot.registry_units@1f119237a4
  - lupin_mcp.host_snapshot.host_zone_name@a5f234462f
  - lupin_mcp.host_snapshot.zone_of@5acb830d66
  - lupin_mcp.host_snapshot.health_ok@abc616e34c
  - lupin_mcp.host_snapshot.read_snapshot@7a66fd266f
  - lupin_mcp.host_snapshot.write_snapshot@df7caf57d6
  - lupin_mcp.host_snapshot.refresh_best_effort@302df86440
  - lupin_mcp.host_snapshot.cron_line@b911e65b05
  - lupin_mcp.host_snapshot.install_mode@0bfb9509b9
  - lupin_mcp.host_snapshot.main@597d41070c
---
# Job host snapshot

The :7999 container has no crontab command and no systemctl. Host jobs write a snapshot file it can read. Callers: [[job-run-wrapper]], [[job-summary-adapters]]; the crontab it copies is written by [[job-cron-generate]].

## The snapshot
- One file, `job-host-snapshot.json`, in the reuse-review data folder, which the container mounts. Schema `host-snapshot/1`.
- It holds the crontab text, the state of the systemd units and the host time zone, each with its own time.
- `read_snapshot` returns the three parts. The crontab is trusted for 36 hours and the units for 30 minutes. A stale or missing part reads as None. A wrong schema or unreadable file gives all None. The card then says "schedule unverified" instead of using the registry's schedule.
- `write_snapshot` always rewrites the crontab. It rewrites the units only when given unit names, else keeps the old ones. The file is replaced by rename.
- `refresh_best_effort` refreshes the crontab part after a host job. It never raises and returns False on any problem.

## Probes
- `crontab_text` returns `crontab -l` text, or None on an error or when there is no crontab.
- `unit_state` returns active, inactive or not-loaded, or None when systemctl gives nothing usable.
- `registry_units` lists every unit a job or target names in its liveness block, once each.
- `host_zone_name` uses `TZ` if it is a known zone, else the zone `/etc/localtime` links to; `zone_of` returns the ZoneInfo or None.
- `health_ok` returns active for an HTTP 200, else inactive; it waits 3 seconds at most.

## The five-minute tick
- `main` with no verb writes the crontab, zone and registry units and returns 0.
- `cron_line` builds the tick's line (every 5 minutes, ending `# job-host-snapshot`). `--print-install` prints it; `--status` reports it; `--uninstall` removes it after a backup.
- `--install` is retired: it prints where the installer went and returns 1.
