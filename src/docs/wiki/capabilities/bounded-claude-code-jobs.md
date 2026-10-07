---
capability: bounded-claude-code-jobs
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.claude_code.job.ClaudeCodeJob@1b092e0e63
  - cosa.agents.claude_code.job.ClaudeCodeJob.do_all@24cbb970c0
  - cosa.orchestration.claude_code.dispatcher.TaskType@516e546e49
  - cosa.orchestration.claude_code.dispatcher.ClaudeCodeDispatcher@4917d3e67e
  - cosa.orchestration.claude_code.dispatcher.ClaudeCodeDispatcher.dispatch@06780c00bc
  - cosa.agents.utils.proxy_agents.base_config.get_anthropic_api_key@4d25966729
---
# Bounded Claude Code jobs

A `ClaudeCodeJob` runs one Claude Code task as a queue job. It rides the CJ Flow agentic pool, so it never blocks the inline fast lane. [[cj-flow-queue]] owns the queue.

## What it does
- `ClaudeCodeJob` is an `AgenticJobBase` subclass; `do_all` runs the task and returns the conversational answer.
- `ClaudeCodeDispatcher.dispatch` routes on `TaskType`. `BOUNDED` runs to completion; `INTERACTIVE` is bidirectional and needs `claude-agent-sdk`.
- Submit through `POST /api/v2/submit`, command `agent router go to claude code`, `args.task_type=BOUNDED`. A missing SDK fails only interactive tasks.

## Why it costs differently
- A bounded job authenticates to the Claude Code CLI with subscription OAuth, so it adds no per-token charge. It is covered by the fixed plan.
- The `cost_usd` in a job record is the SDK's estimate of a direct call's cost: telemetry, not a charge.
- A direct SDK call reads `ANTHROPIC_API_KEY_FIREWALLED` through `get_anthropic_api_key` and is billed per token.
- The suffixed name keeps the bare `ANTHROPIC_API_KEY` reserved for the CLI, so `get_anthropic_api_key` callers never pick it up. The generic `llm_client_factory` "anthropic" vendor still reads the bare name.

## Which path to choose
Choose a bounded job only when all of these hold; otherwise use the direct SDK and say which failed.
- An Anthropic model is enough, and the work fits one self-contained prompt with a bounded turn count.
- The Claude Code tool surface covers what the task needs.
- One to three seconds of start-up per call is acceptable: at most about 10 calls per second, and latency budgets over 2 seconds.
- The caller needs no token streaming; a bounded job returns once, on completion.
- Reference agents on the same subscription path, through in-process `sdk_query` rather than `ClaudeCodeJob`: `bug_fix_expediter`, `test_fix_expediter`, `podcast_generator`, `presentation_generator`, `deep_research`. `notification_proxy` and `decision_proxy` stay on the direct SDK.

## When to run it
- Rolling plan limits make batch work compete with interactive sessions, so set `scheduled_at` on any non-interactive bounded job.
- `scheduled_at` is top-level in the submit request, because `args` is checked against the command's own argument contract.
- Pick a window when the host is up: 10 a.m. to 1 p.m. Eastern is optimal. Avoid 9 to 11 p.m., the owner's interactive peak.
- The host is usually off from about 11 PM to 10 in the morning, so a job scheduled then waits for the next boot.
- A user-clicked job omits `scheduled_at` and runs when the queue reaches it.
