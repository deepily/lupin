# Cost Model — Bounded ClaudeCodeJob vs Firewalled Anthropic SDK

**Audience**: developers designing or modifying LLM-driven agents in Lupin.
**Last verified**: 2026-05-12.
**Empirical record**: [`src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md`](../rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md).
**Canonical mandate**: [`CLAUDE.md` § "COST MODEL — BOUNDED CC vs FIREWALLED SDK"](../../CLAUDE.md).

---

## The two LLM-cost paths

Lupin runs LLM-driven work on one of two paths. The choice is a design-time decision that determines whether the workload contributes to per-token API spend or rides Rick's fixed Max-plan subscription.

### Path A — Bounded `ClaudeCodeJob`

| Aspect | Detail |
|---|---|
| Code | `src/cosa/agents/claude_code/job.py` (`AgenticJobBase` subclass) |
| Routing | CJ Flow `RunningFifoQueue._process_job` → `_submit_agentic_job` → agentic pool |
| Submission endpoint | `POST /api/claude-code/submit` with `task_type=BOUNDED` |
| Underlying invocation | Claude Code CLI / Claude Agent SDK subprocess |
| Auth | OAuth token tied to the Max 200 subscription |
| **Billing** | **Covered by Max plan — zero per-token cost** |
| Reported `cost_usd` in job record | Telemetry-only; NOT an actual charge |
| Spawn overhead per call | ~1-3s (subprocess startup) |
| Tool surface available | Read, Write, Bash, Grep, Glob, WebSearch, WebFetch, plus whatever else the CC CLI ships with |
| Streaming UX to caller | None — bounded jobs return a single result on completion |

### Path B — Direct Anthropic SDK

| Aspect | Detail |
|---|---|
| Code | `AsyncAnthropic( api_key=… )` directly in the agent module |
| Submission | Whatever queue/flow that agent uses (no shared shape) |
| Auth | `ANTHROPIC_API_KEY_FIREWALLED` env var (read via `get_anthropic_api_key()` at `src/cosa/agents/utils/proxy_agents/base_config.py:88`) |
| **Billing** | **Per token against the firewalled Anthropic account** |
| Spawn overhead | None — in-process SDK call |
| Tool surface | Whatever the agent implements; not Claude Code's |
| Streaming UX | Supports token-by-token streaming |

The `ANTHROPIC_API_KEY_FIREWALLED` env var naming is deliberate. The Anthropic SDK's default key-discovery looks for the bare `ANTHROPIC_API_KEY`. Lupin reserves the bare name for the Claude Code CLI (which uses OAuth, not the API key) and uses the suffixed name for SDK consumers. This means a process that inherits the shell env doesn't accidentally pick up the SDK key — only code that explicitly reads `ANTHROPIC_API_KEY_FIREWALLED` gets it. Defense-in-depth.

Per the load-bearing docstring at `src/cosa/agents/deep_research/__init__.py:27`:

> **IMPORTANT: NEVER use ANTHROPIC_API_KEY - that is reserved for Claude Code CLI.**

---

## How we know — the empirical confirmation

On 2026-05-12, a throwaway 10-job probe (5 in-repo prompts + 5 web-search prompts) was submitted via `/api/claude-code/submit` with `task_type=BOUNDED`. The probe ran sequentially with 60s spacing so the Anthropic console UI had time to settle between each.

**Result**:

| | Value |
|---|---|
| Jobs submitted | 10 |
| Jobs completed successfully | 9 (1 failed on an unrelated streaming-parse bug) |
| Total `cost_usd` telemetry (SDK-reported) | **$2.0514** |
| Anthropic console credit balance movement | **$0.00** (confirmed 10 min post-run) |

The `cost_usd` field is SDK-side accounting (the SDK knows what API charges *would* have been for the equivalent direct call), but the actual billing path uses the Max-plan OAuth, so the firewalled account is never charged. The console balance is the only ground truth for "did Anthropic bill me?" and it says no.

Full experimental record in the R&D doc linked at the top.

---

## Decision framework — which path to choose for a new (or migrated) agent

Use this flowchart at design time. Document the answer in the R&D / design doc for the agent.

```
                      ┌─────────────────────────────────────┐
                      │ Need LLM reasoning in a new agent / │
                      │ refactoring an existing one         │
                      └─────────────────┬───────────────────┘
                                        ▼
                  ┌──────────────────────────────────────────────┐
                  │ Q1. Anthropic-backed model is sufficient?    │
                  │ (No need for OpenAI / Groq / Mistral / etc.) │
                  └─────────────┬────────────────────────────────┘
                                ▼
                      No ─────────────────► Path B (direct SDK)
                                │
                                ▼ Yes
                  ┌──────────────────────────────────────────────┐
                  │ Q2. Can the work be expressed as a            │
                  │ self-contained prompt with bounded turns?    │
                  │ (Not multi-day stateful conversation.)       │
                  └─────────────┬────────────────────────────────┘
                                ▼
                      No ─────────────────► Path B (direct SDK)
                                │
                                ▼ Yes
                  ┌──────────────────────────────────────────────┐
                  │ Q3. CC's tool surface (Read/Write/Bash/Grep/ │
                  │ WebSearch/WebFetch/etc.) is enough?          │
                  └─────────────┬────────────────────────────────┘
                                ▼
                      No ─────────────────► Path B (direct SDK)
                                │
                                ▼ Yes
                  ┌──────────────────────────────────────────────┐
                  │ Q4. Tolerates ~1-3s SDK-subprocess spawn     │
                  │ overhead per invocation?                     │
                  │ (i.e., not >10 QPS, latency budget > ~2s)    │
                  └─────────────┬────────────────────────────────┘
                                ▼
                      No ─────────────────► Path B (direct SDK)
                                │
                                ▼ Yes
                  ┌──────────────────────────────────────────────┐
                  │ Q5. Caller doesn't need token-by-token       │
                  │ progressive streaming?                       │
                  └─────────────┬────────────────────────────────┘
                                ▼
                      No ─────────────────► Path B (direct SDK)
                                │
                                ▼ Yes
                          Path A (bounded CC)
```

If you land on **Path B**, the design doc must justify which guardrail forced it (Q1–Q5 answer + why). This is so future reviewers don't silently re-implement direct-SDK agents that should have been bounded CC.

---

## Off-peak scheduling — operational complement

Even though Path A is "free" in marginal-cost terms, the Max plan is NOT infinite throughput — it has rolling-window usage limits. Bounded jobs that run during Rick's interactive Claude Code peak (9 PM – 12 AM EDT) **compete** with his real work and can cause it to throttle.

### Rick's daily usage profile

| Window | State | Bounded-job-friendliness |
|---|---|---|
| 9 PM – 12 AM EDT | Peak interactive Claude Code work | ❌ Avoid scheduled batch here |
| 9 AM – 9 PM EDT | Light-to-moderate interactive use | 🟡 OK for short jobs; avoid heavy batch |
| 12 AM – 9 AM EDT | Rick asleep, zero interactive use | 🟢 **Ideal for batch / long-running** |

### Rule

For any bounded CC job that does NOT need to complete synchronously (batch generation, scheduled regression sweeps, podcast/presentation/deep-research work), **set `scheduled_at` to a post-midnight time** via the existing field on `ClaudeCodeQueueRequest` (`src/cosa/rest/routers/claude_code_queue.py:49`).

```json
POST /api/claude-code/submit
{
  "prompt"       : "…",
  "project"      : "lupin",
  "task_type"    : "BOUNDED",
  "scheduled_at" : "2026-05-13T02:30:00-04:00",
  "max_turns"    : 15
}
```

User-interactive bounded jobs (a user clicks a button and expects a result) are **exempt** — they fire immediately.

---

## Migration playbook

When migrating an existing direct-SDK agent to bounded CC, follow this order:

1. **Confirm fit**: Walk the agent through the Q1–Q5 framework above. Document the answers in the agent's R&D / design doc.
2. **Identify the migration boundary**: Often only part of an agent is LLM-driven. E.g., podcast generation has a script-generation phase (LLM) and an audio-synthesis phase (TTS). Migrate the LLM phase only; leave non-LLM parts alone.
3. **Refactor invocation**: Replace `AsyncAnthropic( api_key=… ).messages.create(...)` with a `ClaudeCodeJob` submission. The prompt becomes the bounded job prompt; the parsed response becomes the job's terminal output.
4. **Drop the firewalled key dependency** for the migrated phase. If the agent's other phases still need it, leave the import alone; just remove unused references.
5. **Add `scheduled_at` defaulting**: For batch / non-interactive callers of the migrated phase, default `scheduled_at` to the next post-midnight slot. Synchronous callers omit it.
6. **Update or write the agent's user-facing doc** under `src/docs/agents/` if applicable.
7. **Update the agent's `__init__.py` banner** (the "API Key Configuration" pattern paragraph if present): note the migration date and link this doc + the R&D doc.
8. **Verify the migration**: Submit a representative payload through the new path, confirm the job lands in CJ Flow's agentic pool, confirm the result is functionally equivalent to the old SDK output, confirm Anthropic console balance does not move.

### Precedent — already migrated

- **BFE** (Bug Fix Expediter) — `src/cosa/agents/bug_fix_expediter/`. Autonomous bug-fix workflow.
- **TFE** (Test Fix Expediter) — `src/cosa/agents/test_fix_expediter/`. Autonomous test-fix workflow.

Both ride the CJ Flow agentic pool with `task_type=BOUNDED` and have been in production for some weeks at the time of writing without consuming firewalled-key budget. Use them as code-shape references when migrating new agents.

### Candidates (tracked in `TODO.md`)

| Agent | Current state | Notes |
|---|---|---|
| **Deep Research** (`src/cosa/agents/deep_research/`) | Path B — uses firewalled key for multi-turn research + synthesis | Largest current firewalled-account line-item. WebSearch + WebFetch are core to its work, both available in CC tool surface. Good fit. |
| **Podcast script generation** (`src/cosa/agents/podcast_generator/`) | Path B — direct SDK for script-generation phase | Script generation is pure text synthesis; perfect fit. Audio TTS phase stays on whatever path it currently uses. |
| **Presentation generation** (`src/cosa/agents/presentation_generator/`) | Path B — direct SDK for content phase | Same shape as podcast — text synthesis with structured output. pptx-assembly phase stays as-is. |

### NOT candidates

| Agent | Current state | Why stays |
|---|---|---|
| `notification_proxy/strategies/llm_fallback.py` LLM classifier | Path B | High-frequency per-message classification; subprocess spawn overhead would dominate. |
| `decision_proxy/` | Path B | Latency-sensitive; subprocess spawn would break the budget. |

---

## Common confusions

### "But the job record reports `cost_usd: 0.23`! That's billing, right?"

No. The `cost_usd` field is the Claude Agent SDK's own telemetry — it knows what a direct API call with the same token count *would* have cost, and reports that for observability. The actual billing on the bounded path goes through OAuth Max-subscription auth, which is fixed-rate. The console balance is the ground truth.

### "Doesn't migration to bounded CC just make things free?"

No — it shifts cost. Rick still pays the Max 200 plan monthly. The migration converts metered per-token spend into already-paid fixed spend. Describe migrations as "covered by existing fixed cost", not as "free".

### "If bounded CC is cheaper, why do we still have direct-SDK agents at all?"

Because the constraints (Q1–Q5 in the decision framework) eliminate direct-SDK paths where bounded CC isn't a fit — high-frequency classification, hard latency budgets, non-Anthropic models, streaming UX. Direct SDK has legitimate use cases. The mandate is to PREFER bounded CC, not to eliminate direct SDK.

### "Can I just slap the migration on without checking the constraints?"

No. Walk the Q1–Q5 framework, document the answers, get the migration plan reviewed. The wrong migration creates latency regressions or breaks streaming UX in ways that are hard to undo.

---

## See also

- `CLAUDE.md` § "COST MODEL — BOUNDED CC vs FIREWALLED SDK" — the canonical mandate.
- `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md` — full experiment record.
- `src/cosa/agents/bug_fix_expediter/` + `src/cosa/agents/test_fix_expediter/` — already-migrated reference implementations.
- `src/rnd/v0.1.4/2026.02.12-cj-flow-bounded-job-packaging-guide.md` — how to package a bounded job (CJ Flow integration).
- `src/cosa/rest/routers/claude_code_queue.py` — `/api/claude-code/submit` route definition (including `scheduled_at` field).
