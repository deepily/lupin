---
capability: cc-hook-guards-and-identity
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials@a5bb126f2f
  - lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials@b747d06683
  - lupin_cli.claude_code.hooks.lib.kill_guard.build_kill_deny_response@2292ba1570
  - lupin_cli.claude_code.hooks.lib.merge_head_guard.build_merge_head_deny_response@9c5ad372ef
  - lupin_cli.claude_code.hooks.lib.listener_processes.find_live_listener_pids@4858c9fe89
  - lupin_cli.claude_code.hooks.lib.listener_processes.exclusive_flock@26ab3ac7aa
  - lupin_cli.claude_code.hooks.lib.listener_processes.listener_spawn_lock@73a67e50a2
  - lupin_cli.claude_code.hooks.lib.listener_processes.tmux_injection_lock@cec7ac813b
  - lupin_cli.claude_code.hooks.lib.main_tree.main_tree_root@1928a26aa8
  - lupin_cli.claude_code.hooks.lib.manager_figure.resolve_implicit_manager_figure@5d723e0a20
  - lupin_cli.claude_code.hooks.lib.manager_figure.is_manager_figure@947efc9c91
  - lupin_cli.claude_code.hooks.lib.manager_figure.classify_manager_figure_denial@9e283f3878
  - lupin_cli.claude_code.hooks.lib.memento_verify_tick.fleet_repo_roots@dfc5e1bc5b
  - lupin_cli.claude_code.hooks.lib.memento_verify_tick.verify_tick_line@8c80060c89
  - lupin_cli.claude_code.hooks.lib.process_identity.process_runs@d968732f75
  - lupin_cli.claude_code.hooks.lib.roster_consistency.find_roster_disagreements@3fbd858354
  - lupin_cli.claude_code.hooks.lib.roster_consistency.format_roster_drift_block@e2e3fd1619
---
# Hook guards, credentials, roster and process identity
Small helpers around the Claude Code hooks: deny envelopes, credentials, listener locks, manager checks and process identity.
## What it does
- `get_hook_credentials` resolves a project's credentials from the INI file. `get_owner_credentials` reads the `[owner]` section of `~/.lupin/config`.
- `build_kill_deny_response` and `build_merge_head_deny_response` build PreToolUse deny envelopes for process sweeps and for a commit during a staged merge.
- `find_live_listener_pids` finds live notification listeners for a session hash.
- `exclusive_flock` holds a blocking flock for a with-block. `listener_spawn_lock` and `tmux_injection_lock` build on it.
- `main_tree_root` returns the main working tree for a path, unless the path sits inside a worktree lane.
- `is_manager_figure` applies the two-source manager test. `resolve_implicit_manager_figure` computes the implicit source from the persona name.
- `classify_manager_figure_denial` says why manager-hood was not established.
- `fleet_repo_roots` reads the repos live session bridges sit in. `verify_tick_line` runs `memento_io.py verify` at most once a day.
- `process_runs` is true only if a pid was started as the named program.
- `find_roster_disagreements` finds projects whose two manager declarations differ. `format_roster_drift_block` renders them for SessionStart.
## Don't
- Do not trust a recorded pid alone. Check it with `process_runs`.
## Invariants
- The deny builders mirror `build_stash_deny_response`.
