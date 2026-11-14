---
capability: cc-hook-cron-switch-guard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.cron_switch_guard.cron_switch_deny_reason@9e59b458ba
  - lupin_cli.claude_code.hooks.lib.cron_switch_guard.build_cron_switch_deny_response@d273703a47
  - lupin_cli.claude_code.hooks.lib.cron_switch_guard.switch_lines@644739db30
  - lupin_cli.claude_code.hooks.lib.cron_switch_guard.changed_jobs@3a0672557b
  - lupin_cli.claude_code.hooks.lib.cron_switch_guard.refused_changes@6497644fdf
  - lupin_cli.claude_code.hooks.lib.cron_switch_guard.registry_jobs_beside@09a8e00c95
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.check@5d79f63bf5
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.violations_for@86426f394c
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.registry_job_ids@6784c17e3f
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.staged_ini_paths@703defb018
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.read_state@e7de00ef31
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.state_path@8e07e2a1d8
  - lupin_cli.claude_code.hooks.lib.cron_switch_commit_check.main@b47b02ae25
---
# Cron-switch guard and commit check

Two controls stop a hand edit of a `cron job <job> enabled` line in `lupin-app.ini`. Every seat runs as one Unix user, so no file permission does it. The endpoint that flips the line is in [[rest-cron-job-switches]]. The drift flag on its rows is the detective control. These two are the preventive ones.

## The PreToolUse guard
- `cron_switch_guard` runs from `pre_tool_use.py`. It denies an Edit, MultiEdit or Write on a file named `lupin-app.ini` when the result would change or remove a switch line. It applies the edit to the file's current text and compares the switch lines. An edit to another key passes, and so does one that only carries a switch line as context.
- It denies a Bash command that writes the file. That covers a redirect, `tee`, an in-place editor, a copy or move onto it, `git checkout` of it and `rm`. It also denies Python that opens the file for writing. The same goes for Python that calls a switch writer on a `cron job` key.
- A line may be added when its job is in the `job-registry.json` beside the file and has no line yet. The value must be true or false. This is how a registry job's key is first created. A single `echo '<line>' >> lupin-app.ini` follows the same rule.
- There is no escape hatch. A variable cannot be the operator's alone when every seat runs as one user. Rick flips switches through the endpoint, and the guard binds only tool calls.
- It fails closed for a call that touches `lupin-app.ini`: an unexpected error denies the call. For every other call it fails open and returns `None`.

## The pre-commit check
- `cron_switch_commit_check` is gate 4 of `src/scripts/pre-commit-chain.sh`. For each staged `lupin-app.ini` it compares HEAD with the index.
- A changed value passes only when the record holds the new value, so a seat can commit the file after Rick flips a switch. A removed line, a duplicate and a value other than true or false are refused.
- A new line passes only for a registry job, once, with no contradicting record. Exit 3 refuses the commit. An internal error prints a loud line and allows it.
- `LUPIN_CRON_SWITCH_STATE` points the check at another record, for tests. `git commit --no-verify` skips every gate and is out of scope.
