# Runbook: move an LLM-driven agent to a bounded Claude Code job

**Audience**: developers who design or change an LLM-driven agent.

**Rule it implements**: [`CLAUDE.md` § Cost model](../../CLAUDE.md) — prefer a bounded job over the direct SDK when the agent fits.

**Capability page**: `src/docs/wiki/capabilities/bounded-claude-code-jobs.md` says what a bounded job is. That page is pinned for merge and is not in the tree yet. This page says how to move an agent onto one.

## The two cost paths

| | Path A: bounded `ClaudeCodeJob` | Path B: direct Anthropic SDK |
|---|---|---|
| Code | `src/cosa/agents/claude_code/job.py`, an `AgenticJobBase` subclass; also in-process `claude_agent_sdk.query` (`sdk_query`) | `AsyncAnthropic( api_key=… )` in the agent module |
| Submit | `POST /api/v2/submit`, command `agent router go to claude code`, `args.task_type=BOUNDED` | whatever queue the agent uses |
| Auth | Claude Code CLI with subscription OAuth | `ANTHROPIC_API_KEY_FIREWALLED`, read by `get_anthropic_api_key` in `src/cosa/agents/utils/proxy_agents/base_config.py` |
| Billing | covered by the fixed plan; no per-token charge | per token, against the firewalled account |
| Start-up | about 1 to 3 s per call (subprocess) | none |
| Streaming | none; one result on completion | token by token |

The `cost_usd` in a bounded job's record is the SDK's estimate of what a direct call would have cost. It is telemetry, not a charge. The Anthropic console balance is the only ground truth for whether a run was billed; `cost_usd` is not.

The key name carries a suffix so a process cannot pick it up by accident. The Anthropic SDK looks for the bare `ANTHROPIC_API_KEY`, which Lupin reserves for the Claude Code CLI. Only code that names `ANTHROPIC_API_KEY_FIREWALLED` gets the key. `src/cosa/agents/deep_research/__init__.py` states the rule in its banner.

A migration shifts cost; it does not remove it. The plan is a fixed monthly bill, so describe a migration as "covered by existing fixed cost", never as "free".

## Prerequisites

The agent must pass all five questions. If any answer is no, it stays on Path B, and its design doc says which question failed. That record stops a later reviewer from re-implementing a direct-SDK agent that should have been bounded.

1. An Anthropic model is enough (no OpenAI, Groq or Mistral).
2. The work is one self-contained prompt with a bounded turn count, not a long stateful conversation.
3. Claude Code's tool surface (Read, Write, Bash, Grep, Glob, WebSearch, WebFetch) covers what the agent needs.
4. One to three seconds of start-up per call is acceptable. That means at most about 10 calls per second and a latency budget over about 2 seconds.
5. The caller needs no token-by-token streaming.

Agents that stay on Path B for these reasons: `notification_proxy/strategies/llm_fallback.py` (per-message classification, so start-up would dominate) and `decision_proxy/` (latency budget).

## Steps to follow

1. **Find the boundary.** Often only part of an agent is LLM-driven. Podcast generation has an LLM script phase and a text-to-speech phase; migrate the LLM phase only.
2. **Replace the call.** Swap `AsyncAnthropic( … ).messages.create( … )` for a `ClaudeCodeJob` submission or an in-process `sdk_query` call. With a job, the prompt becomes the job prompt and the parsed output becomes its terminal output. The in-process form that Podcast, Presentation and Deep Research use runs with `tools=[]` for pure text work. It also sets `permission_mode="plan"` (read-only). It reads `max_turns` from the INI. The keys are `podcast script max turns` (default 5), `presentation generator content max turns` (default 5) and `deep research max research turns` (default 20).
3. **Harden the parser.** A bounded job can return chatty text around the answer. Recover the JSON from it. Use a lenient parser where a missing field has a safe default (Podcast). Use a strict one where the data feeds a renderer (Presentation, Deep Research); it fails loudly on a missing, empty or malformed result.
4. **Replace web search if the agent used it.** The native `web_search_20250305` server tool has no bounded equivalent. Give research subagents `tools=[WebSearch, WebFetch]` and keep the lead agent at `tools=[]`. WebSearch fires in a non-interactive bounded job with no `allowed_tools` list or `can_use_tool` callback. That was verified live. Swapping the search tool leaves the downstream contract intact. `ResearchOrchestratorAgent` in `src/cosa/agents/deep_research/orchestrator.py` reads only `APIResponse.content`, the model's text, and never a web-search result block. The subagent writes its sources into that text, and `parse_subagent_response` reads them there. The rolling plan limit then governs, so drop any per-minute token gating that existed only for the native tool.
5. **Drop the key dependency for the migrated phase.** Remove its references to `ANTHROPIC_API_KEY_FIREWALLED`. If other phases still need the key, leave their imports alone.
6. **Schedule batch callers.** Rolling plan limits make batch work compete with interactive sessions. Any non-interactive caller sets `scheduled_at` inside a window when the host is up. The field is top-level in the submit request, because `args` is checked against the command's own argument contract. 10 a.m. to 1 p.m. Eastern is optimal, and 1 p.m. to 9 p.m. is acceptable. Avoid 9 p.m. to 11 p.m., the owner's interactive peak, because a batch job competes with their own work. The host is usually off from about 11 p.m. to 10 a.m., so a job scheduled then waits for the next boot. The window table is in [`CLAUDE.md` § Off-peak scheduling rule](../../CLAUDE.md). A user-clicked job omits `scheduled_at` and runs at once.
7. **Update the docs.** Edit the agent's page under `src/docs/agents/` if it has one. In its `__init__.py`, update the "API Key Configuration" paragraph. It should say the phase is bounded and link this page.

A scheduled submit:

```json
POST /api/v2/submit
{
  "command"      : "agent router go to claude code",
  "args"         : {
    "prompt"    : "…",
    "project"   : "lupin",
    "task_type" : "BOUNDED",
    "max_turns" : 15
  },
  "scheduled_at" : "2026-08-22T11:00:00-04:00"
}
```

## Verify

- Submit a representative payload through the new path and confirm the job lands in the CJ Flow agentic pool (`GET /api/queue/pool-status`, `inflight_agentic_jobs`).
- Compare the result with the old SDK output for the same payload; it must be functionally equivalent.
- Confirm the Anthropic console balance does not move.
- Run the agent's unit tests and its `quick_smoke_test()`, and keep coverage at 100% lines, branches and functions.

## Rollback

- Revert the migration commit. The Path B call returns, and so does its use of `ANTHROPIC_API_KEY_FIREWALLED`, so confirm the key is still set in the environment first.
- If only the parser misbehaves, loosen or tighten it rather than reverting; the call path is not the cause.
- If a scheduled job missed its window, resubmit it with a new `scheduled_at`. A job that lands in the dead window drains late and `job_persistence.py` logs `[CJ-CATCHUP-LATE]` with the hours late.

## Reference implementations

| Agent | Where | Shape |
|---|---|---|
| BFE (bug fix) | `src/cosa/agents/bug_fix_expediter/` | bounded CC job |
| TFE (test fix) | `src/cosa/agents/test_fix_expediter/` | bounded CC job |
| Podcast script | `src/cosa/agents/podcast_generator/` | `sdk_query`, `tools=[]`, lenient parsers; text-to-speech unchanged |
| Presentation content | `src/cosa/agents/presentation_generator/` | `sdk_query` in seven content methods, strict parsers; the Gemini image and video path is non-Anthropic and stays as it is. The pptx and Marp assembly is unchanged. The diagram renderers in `renderers/` still render from source text, and they now get that source from the migrated `call_for_mermaid`, `call_for_matplotlib` and `call_for_d2` |
| Deep Research | `src/cosa/agents/deep_research/` | lead `tools=[]`, subagents `tools=[WebSearch, WebFetch]`, strict parsers |

`src/rnd/v0.1.4/2026.02.12-cj-flow-bounded-job-packaging-guide.md` explains how to package a bounded job for CJ Flow. `/api/v2/submit` is defined in `src/cosa/rest/routers/v2_ask.py`; the retired `/api/claude-code/*` doors answer 410 from `src/cosa/rest/routers/claude_code_queue.py`.

## Common confusions

- **"`cost_usd` is 0.23, so this was billed."** No. It is the SDK's estimate; billing on this path is the fixed plan.
- **"Migration makes things free."** No; see the cost-shift note above.
- **"Direct SDK agents should all move."** No. The rule is to prefer bounded jobs, and the five questions exclude agents that need high call rates, hard latency, non-Anthropic models or streaming.
- **"I can skip the questions."** A wrong migration adds latency or breaks streaming in ways that are hard to undo. Answer them in the design doc and have the plan reviewed.
