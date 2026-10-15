---
capability: claude-process-memory-watch
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.cc_memory_watch.AlertTracker@5387cbd10b
  - cosa.utils.cc_memory_watch.Sample@8794f22739
  - cosa.utils.cc_memory_watch.collect_samples@afa00510f4
  - cosa.utils.cc_memory_watch.format_alert_line@c985e5bfb5
  - cosa.utils.cc_memory_watch.is_claude_process@c401f7e660
  - cosa.utils.cc_memory_watch.is_listener_process@0b2fb615ef
  - cosa.utils.cc_memory_watch.iter_pids@7fd843988f
  - cosa.utils.cc_memory_watch.main@b77a909d80
  - cosa.utils.cc_memory_watch.parse_cgroup_path@f71f109951
  - cosa.utils.cc_memory_watch.parse_listener_owner_map@20573c3048
  - cosa.utils.cc_memory_watch.parse_scope_unit@ba45b57588
  - cosa.utils.cc_memory_watch.parse_tmux_pane@d0fd4e8630
  - cosa.utils.cc_memory_watch.parse_vm_rss_kb@0a5691b540
  - cosa.utils.cc_memory_watch.read_scope_anon_kb@52b5055a13
  - cosa.utils.cc_memory_watch.resolve_tmux_session@dd0a7c5494
---
# Claude process memory watch

`cosa.utils.cc_memory_watch` writes one line for each live Claude Code process over a memory threshold, so a kernel kill can be tied to a session. It kills nothing and notifies nobody. The wrapper `src/scripts/watch-cc-memory.sh` and the unit `lupin-cc-memory-watch.service` run it. `run_once` is in [[shared-utilities]].

## What it does
- `collect_samples` makes one pass over `/proc` and returns a `Sample` per Claude Code process. A process that exits mid-scan or has no `VmRSS` line is skipped, never reported at 0. `iter_pids` yields the numeric `/proc` entries.
- `is_claude_process` accepts a process only when its `comm` is exactly `claude` and the basename of `argv[0]` is `claude`. `is_listener_process` matches any argv token containing `cc_notification_listener`.
- `parse_vm_rss_kb` reads `VmRSS` from status text, or None. `parse_cgroup_path` returns the cgroup-v2 path after `0::`.
- Three resolvers name the session. `parse_listener_owner_map` maps `--owner-pid` to `--session-id` from listener argv, and skips a listener missing either flag.
- `parse_scope_unit` returns `( unit, session )` or `( None, None )` from cgroup text. It knows the old `lupin-cc-<name>-<pid>.scope` shape and the `ccworker-<name>.slice` shape, where `_` becomes `-`. `parse_tmux_pane` and `resolve_tmux_session` map `TMUX_PANE` to a tmux session name, or None when tmux cannot answer.
- `read_scope_anon_kb` returns the scope's `anon` KB from `memory.stat`, or None.
- `AlertTracker( threshold_kb, restep_kb )` decides when to alert. `should_alert` is True on the first crossing, then after another `restep_kb` of growth, and re-arms below the threshold. `forget_absent` drops state for gone pids.
- `format_alert_line` renders one `[CC-MEM]` line with pid, `rss_gb`, threshold, session, tmux and scope. An unresolved field prints `unresolved` (scope prints `none`).
- `main` takes `--threshold-gb` (16.0), `--restep-gb` (8.0), `--interval` (15.0 s), `--log`, `--once` and `--report`. It exits 0 on a clean pass or Ctrl-C. A `--threshold-gb` of 0 or less is a parser error.

## Don't
- Don't read `scope_anon_kb` as zero when it is None. None means unknown: an uncapped seat, or an unreadable cgroup. The alert does not use the cap figure; it uses process RSS (`Sample.rss_gb`); `scope_anon_kb` is only in `--report` lines. Nothing here stops a runaway.

## Invariants
- The parsers take text and return values, so they need no live process table. Reads of `/proc` return None on any `OSError`. A process that answers to no resolver is still reported, with `unresolved` fields. Alert and `--report` lines share one timestamp per pass.
