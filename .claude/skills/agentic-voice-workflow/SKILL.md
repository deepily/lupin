---
name: agentic-voice-workflow
description: Building Claude Agent SDK background jobs with voice I/O. Use when creating new agents, building background jobs, implementing agentic services, adding voice notifications to agents, or integrating with RunningFifoQueue.
metadata:
  author: lupin-team
  version: "1.1"
  last-updated: "2026-02-11"
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
# Progress update
notify( "Starting research phase", priority="low" )

# Human-in-the-loop
response = ask_yes_no( "Approve this plan?", default="yes" )

# Completion
notify( "Agent completed successfully", priority="medium" )
```

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

## Detailed Reference

**Full Workflow Document**: `src/workflow/agentic-voice-workflow.md`

Contains:
- Complete phase breakdowns
- File templates
- Testing procedures
- Integration patterns

## Anti-Patterns

- **Don't** skip Phase 0 discovery - design before coding
- **Don't** forget voice notifications - user needs progress updates
- **Don't** ignore state machine - enables proper job tracking
- **Don't** hardcode job IDs - use the prefix pattern
- **Don't** skip Q&A scripts - smoke tests stall without them

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

**For agents with interactive questions**: Also create a Notification Proxy Q&A script so
expediter questions are auto-answered during automated testing. See "Notification Proxy" section below.

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
