---
name: agentic-voice-workflow
description: Building Claude Agent SDK background jobs with voice I/O. Use when creating new agents, building background jobs, implementing agentic services, adding voice notifications to agents, or integrating with RunningFifoQueue.
metadata:
  author: lupin-team
  version: "2.0"
  last-updated: "2026-08-25"
---

# Agentic Voice Workflow

Repeatable process for creating agentic background jobs with voice I/O and queue integration.

## When to Use

Use this workflow when building agents that:
- Run as background jobs via `RunningFifoQueue`
- Send progress notifications via `cosa-voice` MCP tools
- Support human-in-the-loop decision points
- Generate artifacts (reports, audio, etc.)
- Follow the `AgenticJobBase` interface contract

## Quick Start

**Slash Command**: `/lupin-new-claude-agent-sdk-voice-workflow`

**Reference Agents**:
- `src/cosa/agents/deep_research/` - Research agent pattern
- `src/cosa/agents/podcast_generator/` - Audio generation pattern

## Workflow Phases

| Phase | Purpose | Output |
|-------|---------|--------|
| Phase 0 | Interactive Discovery | Agent characteristics |
| Phase 1-2 | Skeletal Foundation | Basic agent structure |
| Phase 3 | Voice Notifications | cosa-voice integration |
| Phase 4 | Queue Integration | RunningFifoQueue hooks |
| Phase 5 | Testing | Validation and debugging |
| Phase 5b | Q&A Script | Notification Proxy profile for automated testing |
| Phase 5c | UI E2E Testing | Playwright browser tests (planned v0.1.6) |

## Phase 0: Discovery Questions

Before creating files, answer:

1. **Agent Name** (snake_case): e.g., `pdf_summarizer`
2. **Job Prefix** (2-3 letters): e.g., `ps` → job IDs like `ps-a1b2c3d4`
3. **Input Type**: User query, file path, URL, structured data
4. **Output Type**: Text report, audio file, JSON, multiple artifacts
5. **External Dependencies**: Web search, LLM API, TTS, database
6. **Human-in-the-Loop**: None, input clarification, plan approval, draft review
7. **Execution Time**: Seconds, minutes, long-running

## State Machine Pattern

```python
class OrchestratorState( Enum ):
    # Active states
    INITIALIZING = "initializing"
    PROCESSING   = "processing"
    GENERATING   = "generating"

    # Waiting states (human-in-the-loop)
    WAITING_APPROVAL = "waiting_approval"

    # Terminal states
    COMPLETED = "completed"
    FAILED    = "failed"
```

## Voice Notification Integration

```python
# Job lifecycle: set_job_id at start, clear in finally
voice_io.set_job_id( self.id_hash )
try:
    # Progress update (MUST include queue_name="run")
    await voice_io.notify( "Starting research phase", priority="low", queue_name="run" )

    # Human-in-the-loop
    response = ask_yes_no( "Approve this plan?", default="yes" )

    # Completion
    await voice_io.notify( "Agent completed successfully", priority="medium", queue_name="run" )

    # Progressive breadcrumbs (inside loops or long phases)
    for i, item in enumerate( items ):
        await voice_io.notify( f"Processing {i + 1} of {len( items )}", priority="low", queue_name="run" )
finally:
    voice_io.clear_job_id()
```

**CRITICAL**: Every `notify()` call MUST include `queue_name="run"` for proper queue routing.
`set_job_id()` / `clear_job_id()` enables job card activity log routing in the UI.

**Breadcrumb notifications** are required for loops, long phases (>10s), and
dry-run mode. See "Progressive Breadcrumb Notifications" in the full workflow doc.

## Key Interfaces

### AgenticJobBase Contract
- `run()` - Main entry point
- `get_state()` - Current orchestrator state
- `get_progress()` - Completion percentage
- `get_result()` - Final output

### Queue Integration
- Job ID format: `{prefix}-{uuid4[:8]}`
- Status updates via WebSocket events
- Progress tracking for UI display

## AgenticJobBase Compliance Checklist

**MANDATE**: Every new agentic job MUST satisfy ALL items before merge.
This checklist was created after a Session 381 audit found consistency gaps
across 6 existing job implementations (see `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/`).

### Config
- [ ] Config class has `from_config( config_mgr, debug )` classmethod
- [ ] INI keys added to `lupin-app.ini` under agent-specific prefix
- [ ] Matching explanations added to `lupin-app-splainer.ini`

### Job Lifecycle (`_execute` method)
- [ ] `voice_io.set_job_id( self.id_hash )` called at start of `_execute()`
- [ ] `voice_io.clear_job_id()` called in `finally` block
- [ ] ALL `notify()` calls include `queue_name="run"` (live AND dry-run)
- [ ] `self.answer_conversational` set before job completes
- [ ] `self.error` set on failure with descriptive message

### Dry-Run Mode
- [ ] `_execute_dry_run()` is a separate method (not flag check in `_execute()`)
- [ ] Breadcrumb notifications include `job_id=self.id_hash` and `queue_name="run"`
- [ ] Completion notification includes `abstract` with mock cost summary
- [ ] Cost summary stored in `self.artifacts[ "cost_summary" ]`

### Registration & Routing — ONE entry, and never an `if`/`elif`

🔴 **This section was rewritten 2026-08-25. If you are reading a copy that tells you
to add a factory branch to `agentic_job_factory.py`, that copy is stale** — the
`if`/`elif` it points at is the defect that was removed, and adding a new one
recreates it.

**Registration is ONE contract entry.** Add your command to `JOB_ARG_CONTRACTS`
(`src/cosa/agents/runtime_argument_expeditor/agent_registry.py`) and the v2 registry
builds its `AgentSpec` for you — the agentic set is a comprehension over that table
(`_AGENTIC = tuple( _agentic_spec( command, entry ) for command, entry in JOB_ARG_CONTRACTS.items() )`
in `src/cosa/rest/v2/registry.py`), not a second hand-maintained list. Display name,
CLI module and CLI style are all read off the same entry, so there is nothing to keep
in sync.

- [ ] **The contract entry** in `JOB_ARG_CONTRACTS` — command → `job_prefix`,
      `cli_module`, `job_class_path`, `display_name`, `required_user_args`,
      `system_provided`, `arg_mapping`, `fallback_questions`.
- [ ] **Two ratified opt-ins**, each one line. These are deliberately NOT derived
      from the contract, and the registry says so in comments with reasons:
      - `_SPEAKABLE_AGENTIC` — "belongs in the voice router prompt".
      - `_USER_INITIABLE_AGENTIC` — "a person may start this by typing into the
        Q&A card". Held out on purpose for commands whose only argument is a job id
        produced by a job that already failed — nobody types one of those; you press
        a button on the failed job's card.
      They answer different questions. Deriving either from the other works today by
      coincidence and breaks on the first command that is typeable but not sayable.
- [ ] **One description line** in `_AGENTIC_DESCRIPTIONS` — the dropdown's help text.

- [ ] **The job-construction branch** in `create_agentic_job()`
      (`src/cosa/rest/agentic_job_factory.py`) — ⚠️ **still required today, and this
      is the one place an `elif` is still correct.** The registry carries a
      `job_factory` field for exactly this, but it is `None` in phase 1 and phase 5
      (dispatch by lookup) is not wired yet. Verified in the tree 2026-08-25: the
      chain is live with eleven branches. **Add yours, and expect to delete it when
      phase 5 lands.**

**What you do NOT add:** a *routing* branch. The v2 registry replaced the three v1
routing mechanisms that had drifted apart — the LLM-routing `if`/`elif` reached from
`push_job()` / `get_routing_command()`, the `MODE_TO_AGENT` map, and the command
`if`/`elif` that used to decide routing. Resolution is `resolve()` / `resolve_agentic()`
and nothing else; no caller picks a factory out by name.
`src/tests/unit/test_v2_registry_drift_guard.py` exists to stop them coming back.

🔴 **Know which `elif` is which.** "No `if`/`elif`" is about **ROUTING** — deciding
*which* command this is. Job **construction** — turning a resolved command plus its
arguments into a Job object — still dispatches by branch until phase 5. Reading the
rule as "no branches anywhere" leaves a new agent unbuildable; reading it as "branches
are fine" recreates the defect.

### Routing and argument resolution go through the BRAIN

The single door is `AskFlow` (`src/cosa/rest/v2/flow.py`), reached from
`POST /api/v2/ask` and `POST /api/v2/submit`. It resolves the command against the
registry, runs the Runtime Argument Expeditor to fill arguments, asks the user when
one is missing, and hands the built job to the queue.

🔴 **Do not add an `if`/`elif` anywhere for routing.** That is the defect being
removed, and a new one recreates it. If your command needs behaviour the registry
cannot express, the fix is a new *field* on the entry — the way `crud_factory`,
`label`, `dings` and `user_initiable` were each added — not a branch that reads the
command name and decides.

- [ ] Command resolves through `resolve_agentic()`; no caller reaches your factory
      by picking it out itself.
- [ ] No new `if command == ...` / `elif` in the routing path.

### Arguments and their questions live in the SAME entry

A command declares what it needs AND what to ask when it is missing, side by side,
so the two cannot drift:

```python
"agent router go to deep research" : {
    "required_user_args" : [ "query" ],
    "fallback_questions" : {
        "query"  : "What topic would you like me to research?",
        "budget" : "Would you like to set a budget limit in dollars? Say a dollar amount, or 'no limit'.",
    },
    "fallback_defaults"  : { "budget" : "no limit" },
}
```

- [ ] Every name in `required_user_args` has a `fallback_questions` entry.
- [ ] `arg_mapping` maps what the router actually emits to your CLI's names.
      ⚠️ Map only what genuinely means the same thing. Aliasing `topic` → `research`
      once delivered a spoken subject phrase where a file path was expected, and the
      job failed on a file nobody had named (row 9d89afe2). Leaving it unmapped lets
      the argument stay MISSING and the question fire, which is the correct outcome.

### Voice Reachability — REQUIRED, or the agent cannot be reached by voice
🔴 **The three items above register an agent; they do not make it reachable.**
The router only emits commands it has been *told about*. An agent that satisfies
every other item in this checklist and skips these two is callable by API and
**mute by voice** — the exact failure this section was added to stop
(2026-08-15; see `src/rnd/v0.2.0/2026.08.15-agent-registration-single-source.md` §3).

#### The retrain asymmetry — measured, not asserted

**Listing the command in the prompt makes it reachable immediately. The retrain only
makes it dependable.** The two are not interchangeable and they land at different
times.

Live A/B on the production adapter, same model, same training set, only the prompt
differing (`src/rnd/v0.2.0/2026.08.15-router-emission-probe.md`):

| arm | prompt-listed? | trained? | emitted correctly |
|---|---|---|---|
| `test fix expediter resume` | **no** | yes | **0/5** — routed to `swe team` every time |
| `test fix expediter resume` | **yes** | yes | **5/5** |
| `bug fix expediter` | no | no | **0/5** — routed to `claude code` every time |

⚠️ **Read the middle column before quoting these.** Both arms of the A/B were
*trained*, so this shows prompt-listing is sufficient **given** training. It does
**not** isolate prompt-listing without training — no command in the tree is
prompt-listed and never trained, so that arm could not be run.

⚠️ **One earlier claim in this skill did NOT reproduce and has been removed.** It
said an unlisted command "still fires 6/10", i.e. that a missing entry causes
*intermittent* failure. On this adapter the unlisted arms emitted the target **0/5**
— the model did not invent, it confidently substituted the nearest listed command.
A missing prompt line is a clean, total, silent misroute, not a flaky one. Treat the
old number as retired.

- [ ] `<command>` line added to the router prompt template
      `src/conf/prompts/agent-router-template-completion.txt`
      — **this is what makes the command reachable at all**, today, with no retrain
      and no server bounce.
- [ ] Command key added to the training corpus, `src/conf/training/agent-router-*.json`
      — ⚠️ **scope matters**: `agent-router-*.json` only. The same folder holds
      `vox-cmd-*.json`, a separate browser-command namespace that shares nothing
      with this registry except the key `none`.
      — ⏱️ **Consumed at TRAIN time, baked into the LoRA weights.** Adding the key
      does not make the command live today; it makes it *dependable* after the next
      retrain.
      — 🔒 The training artifact now carries a fingerprint of the corpus it was built
      from, and a training run REFUSES if the two disagree (row 11390b57). Edit the
      corpus and the next run stops and names which side is stale, instead of quietly
      training on the previous corpus.

**Verify, don't assume**: after adding both, confirm the command actually routes
before calling the work done.

### Confirmation Card + Test Coverage — the other two registration surfaces
🔴 **These are registration lists too**, defended by the single-source drift guard
(`src/tests/unit/test_v2_registry_drift_guard.py`). Registering and voice-reaching an
agent (the sections above) is still not the whole story: an agentic command that skips
these two is card-unreachable and/or turns the auto-proxy suite red.

- [ ] **Confirmation-card entry** — add the command → product-name mapping to
      `PRODUCT_NAMES` in `todo_fifo_queue.py`. This is what lets `_confirm_agentic_routing()`
      offer the command as a "Switch to this instead" alternative on the voice
      confirmation card. Omit it and the command is invisible on the card even when the
      router emits it. (A command deliberately NEVER card-reachable — e.g. a
      system-triggered job needing a pasted job hash — instead carries a drift-guard
      exemption that *waives* the `card` surface, with a stated reason.)
- [ ] **Auto-proxy test profile** — add each of the agent's `fallback_questions` arg
      names to the `all_agents` profile in `notification_proxy/config.py`. The proxy
      coverage test asserts that union profile can auto-answer every agent's interview;
      a new agent whose args are absent turns that test red.

### Reference Implementation
Use `src/cosa/agents/deep_research/job.py` as the gold standard — it satisfies
every item in this checklist.

## Detailed Reference

**Full Workflow Document**: `src/workflow/agentic-voice-workflow.md`

Contains:
- Complete phase breakdowns
- File templates
- Testing procedures
- Integration patterns

## Runtime Scheduling (Automatic — No Per-Agent Work Needed)

All agentic jobs automatically support timed execution and exclusive mode. These are
**runtime infrastructure concerns**, not agent-specific features. No per-agent registration,
factory changes, or `_execute()` modifications needed.

### How It Works

**UI form path**: Every job submission card includes a "Schedule for later" checkbox +
datetime picker and an "Exclusive mode" checkbox. The JS `_getSchedulingParams()` helper
adds `scheduled_at` (ISO string) and `monopolize` (bool) to the POST body when set.

**Voice path**: The Runtime Argument Expeditor's confirmation summary automatically includes:
```
---
**Scheduling**
- **run_at**: immediately
- **exclusive_mode**: no
```
Users can modify via the existing `[comment: ...]` pattern:
- *"yes, but schedule it for tomorrow at 2am"* → sets `scheduled_at`
- *"yes, but run it in exclusive mode"* → sets `monopolize = True`

**Runtime arg extraction**: `AskFlow._split_queue_directives()` (`src/cosa/rest/v2/flow.py`)
pops `scheduled_at` and `monopolize` out of the argument dict **before the brain builds
the job**, then passes them to the factory as queue directives. (`parent_id_hash` rides
the same path from the request body.)

🔴 **THEY ARE NOT AGENT ARGUMENTS, AND THIS IS EASY TO GET WRONG** — because they
arrive in the same dictionary as real arguments. The expeditor offers `scheduled_at`
and `monopolize` for *every* agentic command, so "run the deep research at ten
tomorrow" comes back as ordinary keys alongside `query`. They say WHEN and HOW the
queue should run the work, never what the agent should do with it.

The failure mode if you treat them as arguments, or forget to split them out:
`create_agentic_job` reads its arguments **by name** and does not name these, so a
left-in `scheduled_at` is **dropped in silence and the job runs immediately** — the
caller believes it is scheduled and it is not. Equally, they cannot be passed inside
`args`: `args` is validated against the command's argument contract, and no command's
contract names them.

- [ ] Do **not** add `scheduled_at` / `monopolize` to your `JOB_ARG_CONTRACTS` entry.
- [ ] Do **not** read them in `_execute()`.
- [ ] `"immediately"` / `"now"` / `"none"` normalise to no schedule — a user who says
      "immediately" must keep meaning it.

### Shadow mode — during the migration window, a new command runs shadowed first

A newly registered command is **not flipped live on its first day**. It goes through
shadow first: the path is exercised and logged, and what it would have done is
recorded rather than executed. The INI keys carry it per-agent, e.g.
`swe team trust mode = shadow`, `bug fix expediter trust mode = shadow` in
`src/conf/lupin-app.ini`, with the ladder documented in `lupin-app-splainer.ini`:

| mode | what happens |
|---|---|
| `disabled` | no proxy at all |
| **`shadow`** | **observe and log only — compute the decision, do not execute it** |
| `suggest` | surface the suggestion to the user, who still decides |
| `active` | act automatically at the trust level the agent has earned |

**Default is `shadow` for a reason**: observability first. You get a real trace of
what the command would have done, on real traffic, before it can do it.

- [ ] New command's trust mode starts at `shadow` in `lupin-app.ini`.
- [ ] Flip to `suggest`/`active` only after the shadow trace shows the decisions were
      the ones you wanted — that trace is the evidence, and without it the flip is a
      guess.

### Queue Consumer Behavior

- `scheduled_at = None` → immediate execution (default)
- `scheduled_at = "2026-03-31T02:00:00"` → consumer sleeps until that time
- `monopolize = True` → no-op in serial mode; when Hybrid Fast Lane is added, blocks
  all concurrent jobs until this one completes

### What You Do NOT Need to Do

- Add `scheduled_at` / `monopolize` to your agent's contract entry (they are in no
  command's argument contract — see the runtime-arg note above)
- Handle scheduling in your agent's `_execute()` method
- Add a routing branch anywhere — the registry resolves it
- Add UI controls for scheduling (already present on all forms)
- Modify the confirmation prompt template

## Anti-Patterns

- **Don't** skip Phase 0 discovery - design before coding
- **Don't** forget voice notifications - user needs progress updates
- **Don't** ignore state machine - enables proper job tracking
- **Don't** hardcode job IDs - use the prefix pattern
- **Don't** skip Q&A scripts - smoke tests stall without them
- **Don't** omit `queue_name="run"` from `notify()` calls - breaks queue routing
- **Don't** skip `set_job_id()` / `clear_job_id()` - breaks job card activity log
- **Don't** construct config directly - use `from_config()` classmethod
- **Don't** use a different notification API than `voice_io` without strong justification

## CRITICAL: Automated Testing Is Mandatory

Every new agent **MUST** have an automated live pipeline test before merge. Do not rely on manual curl or UI-click testing for pipeline validation. The automated infrastructure exists — use it.

## Testing Best Practice: Automated Pipeline Tests

**Prefer automated smoke test scripts over manual curl submissions.**

| Approach | Effort | Repeatability | Example |
|----------|--------|---------------|---------|
| Manual curl POST to `/api/push` | High (copy-paste, edit JSON, poll manually) | Low | Ad-hoc debugging only |
| Automated smoke test script | Low (single command) | High | `src/tests/smoke/test_calculator_live_pipeline.py` |

**Pattern**: `test_calculator_live_pipeline.py` demonstrates the preferred approach:
- Login via `/auth/login`, get JWT
- Set agent mode via `/api/mode/current`
- Submit queries via `/api/push`, extract `job_id` from response
- Poll `/api/get-queue/done` by `job_id` until completion
- Validate answers contain expected keywords
- Print summary table

When building new agents, create an automated smoke test following this pattern rather than relying on manual curl commands.

### Non-Interactive Agent Template (`LivePipelineTestBase`)

Copy and adapt this template for agents that do **not** ask interactive questions:

```python
#!/usr/bin/env python3
"""
Smoke test for {AgentName} agent via live pipeline.

Usage:
    python src/tests/smoke/test_{agent_name}_live_pipeline.py
    python src/tests/smoke/test_{agent_name}_live_pipeline.py -q 0,2

Requires:
    - Server running on localhost:7999
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
"""

import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


{AGENT_NAME_UPPER}_QUERIES = [
    {
        "id"               : "SCENARIO_1",
        "query"            : "Your test query here",
        "expected_keywords" : [ "expected", "words" ],
    },
    # Add more scenarios...
]


class {AgentName}PipelineTest( LivePipelineTestBase ):

    TEST_NAME       = "{Agent Name} Live Pipeline"
    SCENARIOS       = {AGENT_NAME_UPPER}_QUERIES
    DEFAULT_TIMEOUT = 120

    def build_argparser( self ):
        parser = super().build_argparser()
        parser.add_argument( "--queries", "-q", type=str, default=None,
            help="Comma-separated query indices (e.g., '0,1,3'). Default: all." )
        return parser

    def get_scenario_indices( self, args ):
        if hasattr( args, "queries" ) and args.queries:
            return [ int( x.strip() ) for x in args.queries.split( "," )
                     if int( x.strip() ) < len( self.SCENARIOS ) ]
        return list( range( len( self.SCENARIOS ) ) )

    def get_mode_for_scenario( self, scenario ):
        return "{agent_name}"  # Or None for auto-route testing


def quick_smoke_test():
    import argparse
    test = {AgentName}PipelineTest()
    args = argparse.Namespace( queries=None, debug=False, verbose=False )
    return test.run_scenarios( args )


def test_{agent_name}_live_pipeline():
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = {AgentName}PipelineTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
```

### Interactive Agent Template (`InteractiveSmokeTest`)

For agents that ask interactive questions via the Runtime Argument Expediter, use `InteractiveSmokeTest` instead:

```python
from tests.smoke.utilities.interactive_smoke_test import InteractiveSmokeTest

class {AgentName}InteractiveTest( InteractiveSmokeTest ):

    TEST_NAME      = "{Agent Name} Interactive"
    SCENARIOS      = {AGENT_NAME_UPPER}_SCENARIOS
    PROXY_PROFILE  = "{agent_name}"
    DEFAULT_TIMEOUT = 180
```

Run with: `python src/tests/smoke/test_{agent_name}_live_pipeline.py --auto-proxy --no-confirm`

### Key Test Infrastructure Files

| File | Purpose |
|------|---------|
| `src/tests/smoke/utilities/live_pipeline_base.py` | Base class: auth, submit-and-poll, validation, reporting |
| `src/tests/smoke/utilities/interactive_smoke_test.py` | Adds proxy auto-launch for interactive agents |
| `src/tests/smoke/test_calculator_live_pipeline.py` | Reference: non-interactive (6 scenarios) |
| `src/tests/smoke/test_proxy_integration.py` | Reference: interactive (12 scenarios, 3 agent groups) |
| `src/docs/automated-interactive-testing.md` | Comprehensive proxy testing guide |

**For agents with interactive questions**: Also create a Notification Proxy Q&A script so
expediter questions are auto-answered during automated testing. See "Notification Proxy" section below.

> **Planned (v0.1.6)**: Playwright-based UI E2E tests will add browser-level validation
> (submit via UI, verify job cards, check notification rendering). When implemented, update
> this SKILL.md with the Playwright test template and add a Phase 5c section.

## Notification Proxy: Automated Q&A Scripts

When agents ask interactive questions (via Runtime Argument Expediter), smoke tests stall
without human input. The Notification Proxy solves this by loading a JSON Q&A script at
startup and using Phi-4 local LLM to semantically match incoming questions to scripted answers.

### Creating a Q&A Script for Your Agent

1. **Find your agent's questions** — look up `fallback_questions` in `agent_registry.py`
2. **Copy the template** — `cp _template.json your-agent.json` in `src/conf/notification-proxy-scripts/`
3. **Add one entry per question** — fill in `question_pattern`, `answer`, `arg_name`, `response_types`
4. **Include a yes/no confirmation entry** — always answer "yes" for automated testing
5. **Register the profile** — add to `__main__.py` choices and `config.py` `TEST_PROFILES`

### JSON Entry Anatomy

Each entry in the `entries` array follows this format:

```json
{
    "question_pattern" : "What topic would you like me to research?",
    "answer"           : "quantum computing breakthroughs 2026",
    "arg_name"         : "query",
    "response_types"   : [ "open_ended", "open_ended_batch" ]
}
```

### Multi-Agent Scripts

For `all-agents.json`, scope entries to specific agents with the `agents` tag:

```json
{
    "question_pattern" : "What topic?",
    "answer"           : "quantum computing",
    "agents"           : [ "deep_research", "research_to_podcast" ]
}
```

Entries without an `agents` tag are universal and apply to any agent.

### Quick Usage (Two-Terminal Pattern)

```bash
# Terminal 1: Start proxy with your agent's profile
python -m cosa.agents.notification_proxy --profile your_agent --debug

# Terminal 2: Run the smoke test
python src/tests/smoke/test_your_agent_live_pipeline.py
```

### Key Files

| File | Purpose |
|------|---------|
| `src/conf/notification-proxy-scripts/README.md` | Full guide for creating Q&A scripts |
| `src/conf/notification-proxy-scripts/_template.json` | Copy-and-modify starter template |
| `src/cosa/agents/notification_proxy/config.py` | Profile registration (backward compat) |
| `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` | Defines questions per agent |

**Reference**: `src/conf/notification-proxy-scripts/README.md`
