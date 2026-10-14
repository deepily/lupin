---
capability: runtime-argument-expeditor
pin_algorithm: py3.13.x60338d/ts5.9.3
pins:
  - cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor@6ee027fcbd
  - cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor.expedite@279a626853
  - cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor.extract@4afef45b10
  - cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor.collect@442434cc10
  - cosa.agents.runtime_argument_expeditor.expeditor.ExtractionResult@311c8452e3
  - cosa.agents.runtime_argument_expeditor.expeditor.ExpediteContext@963c56f4e4
  - cosa.agents.runtime_argument_expeditor.expeditor.ArgSpec@de57c6212f
  - cosa.agents.runtime_argument_expeditor.expeditor.user_message_for_expedite_reason@d817448d3f
  - cosa.agents.runtime_argument_expeditor.agent_registry.get_cli_help@3908f37524
  - cosa.agents.runtime_argument_expeditor.agent_registry.get_user_visible_args@93968228cb
  - cosa.agents.runtime_argument_expeditor.cli_help.run_help_for_module@36057eb386
  - cosa.rest.v2.flow.AskFlow.ask@57c5527ac0
---
# Runtime argument expeditor

Sits between routing and job creation. A voice command names an agent but may leave out arguments it needs. The expeditor finds the gaps, asks the user for them, and returns a complete args dict.

## What it does
- `extract` is the half with no prompt. It runs the agent's `--help` text, the voice command and the router's arguments through an LLM gap analysis. Arguments the router already supplied win over the LLM's.
- If the reply does not parse, every required argument counts as missing. The missing set is the user-visible arguments not yet known.
- `collect` is the interactive half. More than one missing argument goes out as one batch question; one goes out alone. A `fuzzy_file_match` or `tfe_checkpoint_match` handler resolves a file or checkpoint by choice card.
- `_confirm_and_iterate` shows a summary for up to five rounds. `yes` approves and `no` cancels. After the fifth it proceeds with the current arguments.
- System arguments (`user_email`, `session_id`, `user_id`, `no_confirm`) are injected last and never overwrite a user value.

## Invariants
- The registry is `JOB_ARG_CONTRACTS`: 12 commands, though the module docstring still says three. Each entry carries the CLI module, required and system-provided arguments, questions and defaults.
- `ArgSpec.from_entry` copies `fallback_defaults`, so one user's seeded default does not leak to the next.
- A call's job id, token and failure reason live on its own `ExpediteContext`, never on the shared instance. Only `BATCH_DECLINED` is a user decision; an unknown command is `BATCH_INTERNAL`.
- An answer of `no limit`, `none`, `skip`, `no` or `default` for `budget`, `languages` or `timeout` drops that argument.

## How it is used
- `AskFlow.ask` calls `extract` only. It returns the first missing question and parks the request when the caller is interactive.
- `TodoFifoQueue` calls `expedite` (`extract` then `collect`, returning the args dict or `None`). It refuses when `runtime argument expeditor enabled` is false.
- `get_cli_help` runs `python -m <cli_module> --help` with a 10 second timeout and caches the result, including a failure. `get_user_visible_args` asks the same module for `--user-visible-args`.
- A package with no runnable CLI answers `--help` through `run_help_for_module`, as `claude_code`, the bug-fix expediter and the test-fix expediter do.
- To add an agent, add its `JOB_ARG_CONTRACTS` entry. See [[v2-ask-flow]].
