---
capability: cc-hold-file-lookup
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.fleet_data_root@f42b2cc795
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.hold_correct_zone@13e3360384
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.hold_is_misplaced@36b358b8f1
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.resolve_hold_base_dir@a93af0e6ea
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.hold_path@a15e94224b
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.read_hold@56bc0e7a8d
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.read_hold_exact@8795f13fcb
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.hold_search_dirs@4745cd29b7
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.read_hold_resilient@d3243cab11
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.read_hold_via_bridge@32dfd3d724
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.clear_hold@40c5ce25e7
---
# Hold file location and lookup
Where a session's hold file lives and how the Stop hook and the arbiter find it. The hold itself is described in [[cc-hooks-heartbeat]].
## What it does
- `fleet_data_root` returns the runtime-data folder for a repo: `<DEEPILY_DATA_DIR>/<repo-name>`. A worktree resolves to its parent checkout.
- When the env var is unset, it derives the same place from the `projects` folder instead of using the repo root.
- `resolve_hold_base_dir` returns the Stop-hook `cwd` when given, else the project root. `hold_path` builds the per-session file path.
- `read_hold` reads one hold and stamps it with the file mtime. `read_hold_exact` reads only that session id's own file, never a prefix match.
- `hold_search_dirs` lists the folders to search: the `cwd` first, then the fleet data folder of the `cwd` repo, then the hook's own.
- `read_hold_resilient` returns the first hold found across those folders. A worker in a worktree is then not poked forever.
- `read_hold_via_bridge` is for callers with no `cwd`, such as the arbiter. It takes the `cwd` from the session bridge.
- If the bridge is missing, it falls back to no `cwd` and logs `arbiter_hold_reader_cwd_fallback` through the `log_fn` it was given.
- `hold_correct_zone` returns the parent of the fleet data root, or None when it cannot judge. `hold_is_misplaced` is true for a hold outside that zone.
- `clear_hold` deletes a session's hold and is safe when none exists.
## Don't
- Don't hand-write a hold file; use [[cc-hold-verb-and-acked-ledger]].
## Invariants
- The readers and `clear_hold` swallow IO errors instead of raising into the hook.
- An unresolvable zone means no hold is flagged as misplaced.
