---
name: agentic-voice-workflow
description: Building Claude Agent SDK background jobs with voice I/O. Use when creating new agents, building background jobs, implementing agentic services, adding voice notifications to agents, or integrating with RunningFifoQueue.
metadata:
  author: lupin-team
  version: "1.3"
  last-updated: "2026-03-27"
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

### Registration & Routing
- [ ] Entry added to `agent_registry.py` with `required_params` and `fallback_questions`
- [ ] Factory branch added to `agentic_job_factory.py`
- [ ] Dedicated REST router in `src/cosa/rest/routers/`

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

**Runtime arg extraction**: In `_handle_agentic_command()`, `scheduled_at` and `monopolize`
are popped from `args_dict` before the factory creates the job, then set directly on the
job object. The factory never sees these — they're infrastructure, not agent params.

### Queue Consumer Behavior

- `scheduled_at = None` → immediate execution (default)
- `scheduled_at = "2026-03-31T02:00:00"` → consumer sleeps until that time
- `monopolize = True` → no-op in serial mode; when Hybrid Fast Lane is added, blocks
  all concurrent jobs until this one completes

### What You Do NOT Need to Do

- Add `scheduled_at` / `monopolize` to your agent's registry entry
- Handle scheduling in your agent's `_execute()` method
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
