---
capability: deep-research-cli
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research.cli.check_prerequisites@2d40de3f5f
  - cosa.agents.deep_research.cli.main@edd62ebf2e
  - cosa.agents.deep_research.cli.parse_args@63469df063
  - cosa.agents.deep_research.cli.print_header@0418ab18e9
---
# Deep research command line

`python -m cosa.agents.deep_research.cli` runs the research from a terminal, outside the queue. It shares `run_research` with [[deep-research]], so the report, cache and cost tracking are the same.

## What it does
- `parse_args` reads the query, user email, budget, model overrides and the CLI-mode and dry-run switches. `--user-visible-args` is answered early by `main`, before argparse enforces required arguments.
- `main` resolves the user email from the argument, then from the INI key `deep research default user email`. It exits with an error when the email is missing or has no `@`.
- With the `gcs` storage backend, `main` checks the bucket first. If the SDK or bucket is unreachable it prints a warning and falls back to local storage.
- `main` names the session from the query through the `Gister`, then builds a `ResearchConfig` from the INI. Model and subagent flags override it.
- `check_prerequisites` only checks that `claude_agent_sdk` imports. No API key is needed; the bounded Claude Code path authenticates through the Max-plan session.
- `print_header` prints the query, both model names, the subagent cap and the budget (or "unlimited").

## Don't
- Don't look for an API-key check here. It was retired when the agent moved to bounded Claude Code.
- Don't rely on `--cli-mode` for the queue job. It only switches voice I/O off for this entry point.
