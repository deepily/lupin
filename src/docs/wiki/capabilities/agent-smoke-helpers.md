---
capability: agent-smoke-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.agent_base.run_agent_smoke@90c17fe850
  - cosa.agents.utils.smoke_suite.run_import_smoke_suite@b4c8e60f89
---
# Agent smoke helpers

Two helpers the agents' own `quick_smoke_test` functions share. Neither makes a test assertion.

## What it does
- `run_agent_smoke( agent_cls, question, label, error_context )` builds the agent with `debug` on and runs its prompt, code and formatter steps. It prints one line per step, then the final answer.
- It catches any exception, prints it as `Error during <error_context>` and still prints the closing line.
- `run_import_smoke_suite( title, modules, error_chars=80 )` takes pairs of display name and module path. It imports each, calls its `quick_smoke_test` and prints a summary table.
- It returns `True` when no module failed. The podcast and presentation generators' `__main__` modules use it.

## Don't
- Don't read a clean run of `run_agent_smoke` as a pass. It never raises, so only the printed lines show a failure.

## Invariants
- `run_import_smoke_suite` runs every module even after an earlier one fails.
- An error text is cut to `error_chars` characters in the table.
