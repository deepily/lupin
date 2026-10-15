---
capability: swe-team-tool-hooks
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.swe_team.hooks.build_can_use_tool@5a365b9fd6
  - cosa.agents.swe_team.hooks.notification_hook@69b8c7a3f2
  - cosa.agents.swe_team.hooks.post_tool_hook@b6c2a58ec5
  - cosa.agents.swe_team.hooks.pre_tool_hook@611f6ca227
  - cosa.agents.swe_team.hooks.wrap_prompt_for_streaming@cac3fcd55c
  - cosa.agents.swe_team.safety_limits.SafetyLimitError@bb11d66a4a
  - cosa.agents.swe_team.safety_limits.is_dangerous_command@ce8ff0e568
---
# SWE team tool hooks and command guard

These hooks sit between the agent SDK and the tools an agent runs. They ask the user before a risky shell command, count file edits, and mirror SDK notices as progress. The guard that counts is in [[swe-team-orchestrator]].

## What it does
- `is_dangerous_command` is a case-insensitive substring match against a fixed set. The set covers `rm`, `git push`, `git reset --hard`, `docker rm` and `rmi`, and the SQL words `DROP TABLE`, `DELETE FROM` and `TRUNCATE`.
- It also covers `kill -9`, `pkill`, `shutdown`, `reboot`, `chmod 777` and `chown`.
- `pre_tool_hook` allows every tool except `Bash`, and allows a `Bash` command that is not dangerous.
- For a dangerous command it asks for confirmation, with a 60 second wait and a default of `no`. A rejection, or a failure to ask, returns a deny.
- `post_tool_hook` calls `guard.record_file_change` for `Edit` and `Write`, and ignores other tools.
- `build_can_use_tool` returns the async callback the SDK expects, bound to one role and guard. It calls `pre_tool_hook`.
- `notification_hook` sends the SDK's message as a low-priority progress notice, prefixed with the role. It skips an empty message and logs a warning instead of raising.
- `wrap_prompt_for_streaming` yields one SDK user message. The SDK needs a streamed prompt whenever `can_use_tool` is set.
- `SafetyLimitError` is the exception the guard raises when a limit is passed.

## Don't
- Don't treat the match as a parser. The pattern is `rm` plus a trailing space, so any word that ends in `rm` and is followed by a space also matches.
- Don't expect a denied command to stop the run. The deny carries `interrupt` false, so the agent continues.
