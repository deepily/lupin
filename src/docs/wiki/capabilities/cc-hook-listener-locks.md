---
capability: cc-hook-listener-locks
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.listener_processes.find_live_listener_pids@4858c9fe89
  - lupin_cli.claude_code.hooks.lib.listener_processes.exclusive_flock@26ab3ac7aa
  - lupin_cli.claude_code.hooks.lib.listener_processes.listener_spawn_lock@73a67e50a2
  - lupin_cli.claude_code.hooks.lib.listener_processes.tmux_injection_lock@cec7ac813b
---
# Hook listener locks

Two SessionStart hooks once fired for one session and spawned two notification listeners. This capability finds the live ones and serialises the steps that raced.

## What it does
- `find_live_listener_pids( session_hash )` lists the pids of live listeners for a session. It matches command lines with `pgrep -f`, so it does not depend on a bridge file.
- It leaves out the calling process and returns an empty list when `pgrep` is missing, times out or fails.
- `exclusive_flock( lock_path )` holds a blocking flock for a with-block and yields whether it was held.
- `listener_spawn_lock( session_hash )` is the lock around the check-then-spawn step of one session.
- `tmux_injection_lock( tmux_session )` makes the text-then-Enter send-keys pair atomic for one tmux session. Two injectors then cannot interleave keystrokes in a pane.

## Don't
- Don't take the lock as proof you are alone. It fails open, so check the yielded flag when that matters.
- Don't trust a bridge file for the listener's pid. The bridge remembered only the last one.

## Invariants
- A lock that cannot be created or taken lets the block run anyway.
- No function here raises on a lock or a process-lookup problem.
