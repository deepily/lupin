# Autonomous Multi-Agent Engineering Team — Implementation Plan

## Context

The Lupin project needs a multi-agent engineering team powered by the Claude Agent SDK (v0.1.35). The architecture design is complete (`agent-team-architecture-design.md`). This plan implements the full system: 6-role SWE team, CJ Flow queue integration, CLI entry point, and graduated-trust decision proxy — following the agentic-voice-workflow lifecycle (`src/workflow/agentic-voice-workflow.md`).

**Pattern**: 6 (Research-Driven Implementation) — Phase 0 research is DONE.

---

## Agent Identity

| Field | Value |
|-------|-------|
| Directory | `src/cosa/agents/swe_team/` |
| JOB_TYPE | `swe_team` |
| JOB_PREFIX | `st` (IDs: `st-a1b2c3d4`) |
| Routing command | `agent router go to swe team` |
| Sender IDs | `swe.{role}@lupin.deepily.ai#{session_id}` |
| Models | Lead/Architect: Opus 4.6, Workers: Sonnet 4.5 |

---

## Phase Status

| Phase | Description | Status | Started | Completed |
|-------|-------------|--------|---------|-----------|
| 0 | Research + Architecture Design | DONE | 2026-02-13 | 2026-02-13 |
| 1 | Single Agent + Lupin Notification Integration | PENDING | — | — |
| 2 | Lead + Coder Delegation Loop | PENDING | — | — |
| 3 | Add Tester to Loop | PENDING | — | — |
| 4 | Trust-Aware Proxy Expansion | PENDING | — | — |
| 5 | Reviewer + Debugger + CJ Flow Integration | PENDING | — | — |

---

## Phase 1: Single Agent + Lupin Notification Integration (1-2 days, ~12 tasks)

**Goal**: Wire one claude-agent-sdk session into Lupin via cosa_interface. Verify notifications flow.

### 1.1 Pre-Flight

**Config keys** — `src/conf/lupin-app.ini` + `src/conf/lupin-app-splainer.ini`:
```
swe team enabled, swe team lead model, swe team worker model,
swe team max iterations per task, swe team max tokens per session,
swe team wall clock timeout seconds, swe team max consecutive failures,
swe team max file changes per task, swe team budget usd
```

**Dependency check**: `claude-agent-sdk` (v0.1.35), `anthropic` SDK

### 1.2 Foundation Files

| File to Create | Pattern Source | Purpose |
|---|---|---|
| `swe_team/__init__.py` | `deep_research/__init__.py` | Package exports |
| `swe_team/config.py` | `deep_research/config.py` | `SweTeamConfig` dataclass |
| `swe_team/state.py` | `deep_research/state.py` | `OrchestratorState` enum + `TaskSpec` Pydantic model |
| `swe_team/agent_definitions.py` | Research doc Section 3.1 | All 6 role declarations (only `lead` active in Phase 1) |
| `swe_team/safety_limits.py` | Research doc Section 7.2 | `SAFETY_LIMITS` dict, iteration/token/timeout guards |
| `swe_team/orchestrator.py` | `deep_research/orchestrator.py` | Core orchestrator — single `query()` call, hooks -> Lupin |
| `swe_team/mock_clients.py` | Workflow template | `MockAgentSDKSession` for dry-run mode |
| `swe_team/__main__.py` | Workflow template | CLI: `python -m cosa.agents.swe_team "task description"` |

### 1.3 Notification Integration

| File to Create | Pattern Source | Purpose |
|---|---|---|
| `swe_team/cosa_interface.py` | `deep_research/cosa_interface.py` | Role-aware sender IDs, `notify_progress()`, `ask_confirmation()`, `request_decision()`, `get_feedback()` |
| `swe_team/voice_io.py` | `deep_research/voice_io.py` | Thin wrapper around cosa_interface |

SDK hooks wire into cosa_interface:
- `Notification` hook -> `notify_progress( role=event.agent_name )`
- `PreToolUse` hook -> gate dangerous commands via `ask_confirmation()`

### 1.4 Testing

- `quick_smoke_test()` in every module
- `src/tests/unit/test_swe_team_config.py` — config defaults, safety limits, sender_id regex
- Dry-run: verify fire-and-forget + blocking notifications flow correctly

---

## Phase 2: Lead + Coder Delegation Loop (2-3 days, ~10 tasks)

**Goal**: Task decomposition -> structured delegation -> coder implements -> lead verifies.

### Files

| File | Action | Purpose |
|---|---|---|
| `swe_team/hooks.py` | **Create** | Extract SDK hooks: `notification_hook()`, `pre_tool_hook()` with `DANGEROUS_COMMANDS` gating |
| `swe_team/state_files.py` | **Create** | `feature_list.json` + `claude-progress.txt` management for cross-session state |
| `swe_team/orchestrator.py` | **Modify** | Implement `_decompose_task()` -> `TaskSpec[]`, `_delegate_task()` with `coder` subagent |
| `swe_team/agent_definitions.py` | **Modify** | Activate `coder` (tools: Read, Edit, Bash) |

**Critical rule** (Research doc Section 7.1): Every delegation MUST include objective, expected output format, tool guidance, scope boundaries.

### Testing
- `src/tests/unit/test_swe_team_delegation.py` — decomposition, mock SDK delegation
- Manual E2E: simple task like "add a health check endpoint"

---

## Phase 3: Add Tester to Loop (1-2 days, ~8 tasks)

**Goal**: Coder -> Tester -> Verify cycle with iteration cap on failure.

### Files

| File | Action | Purpose |
|---|---|---|
| `swe_team/mcp_tools.py` | **Create** | Custom MCP tool: `run_tests` (pytest wrapper with timeout + output truncation) |
| `swe_team/agent_definitions.py` | **Modify** | Activate `tester` (tools: Read, Edit, Bash) |
| `swe_team/orchestrator.py` | **Modify** | Implement `_verify_result()`, coder->tester iteration loop (max `max_consecutive_failures`) |
| `swe_team/safety_limits.py` | **Modify** | Add `require_test_pass = True` enforcement |

**Flow**: Lead -> Coder implements -> Tester writes/runs tests -> If fail, iterate (max 3) -> If pass, report complete.

### Testing
- `src/tests/unit/test_swe_team_verification.py` — loop termination, failure escalation

---

## Phase 4: Trust-Aware Proxy Expansion (3-5 days, ~15 tasks)

**Goal**: Extend Notification Proxy into graduated-trust decision proxy for off-hours autonomy.

> **Note**: Independent of Phases 2-3. Can be developed in parallel after Phase 1.

### New Files

| File | Purpose |
|---|---|
| `notification_proxy/strategies/engineering_decisions.py` | **Tier 0 strategy**: `EngineeringDecisionStrategy` — classifies decisions (deployment, testing, deps, architecture, destructive, general), trust-level gating (L1=shadow, L2=suggest, L3+=act), LLM fallback |
| `notification_proxy/trust_tracker.py` | `CategoryTrust` (rolling window, time-weighted decay) + `TrustTracker` — L1->L5 graduation with hard counts (50->200->500->1000), per-category isolation |
| `notification_proxy/circuit_breaker.py` | `CircuitBreaker` — error rate spike, confidence collapse, OOD detection -> automatic trust demotion + urgent notification |
| `notification_proxy/decision_store.py` | PostgreSQL-backed: `log_shadow()`, `log_decision()`, `find_similar()`, `get_pending()`, `ratify()` |
| `swe_team/smart_router.py` | Availability-aware: schedule check + WebSocket connectivity -> route to human or proxy |
| `src/cosa/rest/routers/proxy_decisions.py` | Morning ratification: `GET /api/proxy/pending/{email}`, `POST /api/proxy/ratify/{id}` |

### Modified Files

| File | Change |
|---|---|
| `notification_proxy/responder.py` | Insert Tier 0 `EngineeringDecisionStrategy` before Phi-4 script matcher |
| `notification_proxy/config.py` | Add `SWE_TEAM_SENDERS` set + trust defaults |
| `notification_proxy/__main__.py` | Add `--trust-mode` CLI flag |

### Config Keys (trust proxy)
```
trust proxy enabled, trust proxy initial level, trust proxy graduation window,
trust proxy decay factor, trust proxy destructive cap level,
trust proxy deployment cap level, trust proxy circuit breaker error threshold,
trust proxy circuit breaker confidence floor
```

**Key constraints**: `destructive` and `deployment` categories CAPPED at L3 regardless of score.

### Testing
- `src/tests/unit/test_trust_tracker.py` — graduation, rollback, per-category isolation
- `src/tests/unit/test_circuit_breaker.py` — demotion triggers
- `src/tests/unit/test_engineering_decisions.py` — classification, trust gating, shadow mode
- Integration test for ratification endpoint

---

## Phase 5: Reviewer + Debugger + CJ Flow Integration (2-3 days, ~13 tasks)

**Goal**: Full SWE team + queue integration + voice routing.

### 5a: Remaining Roles

| File | Action | Purpose |
|---|---|---|
| `swe_team/agent_definitions.py` | **Modify** | Activate `reviewer` (Read, Grep, Glob — NO write) + `debugger` (Read, Grep, Bash) |
| `swe_team/orchestrator.py` | **Modify** | Add review step after coder+tester pass; debugger on failure paths |
| `swe_team/circuit_breaker_agent.py` | **Create** | Per-agent circuit breaker: 3 consecutive failures -> stop + notify urgent |

**Full flow**: Lead -> Coder -> Tester -> Reviewer -> (if issues) -> Coder fixes -> retry | Debugger on failures

### 5b: CJ Flow Job Wrapper

| File | Pattern Source | Purpose |
|---|---|---|
| `swe_team/job.py` | `deep_research/job.py` | `SweTeamJob(AgenticJobBase)` — `do_all()` -> `asyncio.run(orchestrator.run())` |

### 5c: FastAPI Router

| File | Pattern Source | Purpose |
|---|---|---|
| `src/cosa/rest/routers/swe_team.py` | `routers/deep_research.py` | `POST /api/swe-team/submit`, `GET /api/swe-team/status/{job_id}` |

### 5d: Registry + Factory + LORA

| File | Action |
|---|---|
| `src/cosa/rest/agentic_job_factory.py` | Add `agent router go to swe team` branch |
| `agent_registry.py` | Add entry: required_user_args=["task_description"] |
| `agent-router-agentic-commands.json` | Add LORA training path |
| `synthetic-data-agent-routing-swe-team.txt` | Create 65+ voice routing templates |
| `src/fastapi_app/main.py` | Register `swe_team` + `proxy_decisions` routers |

### Testing (All 5 surfaces)
- Surface 1: Smoke tests for job.py, router
- Surface 2: `src/tests/unit/test_swe_team_job.py` — job creation, mock do_all()
- Surface 3: Mock endpoint via `/api/swe-team/submit` with dry_run=True
- Surface 4: LORA training data generation
- Surface 5: Voice routing: "start an swe team task to implement X"

---

## Cross-Phase Dependencies

```
Phase 1 (Foundation + Notifications)
    |
    +---> Phase 2 (Lead + Coder)
    |         |
    |         +---> Phase 3 (Add Tester)
    |                    |
    +---> Phase 4 (Trust Proxy) [INDEPENDENT — parallel after Phase 1]
    |                    |
    +--------------------+---> Phase 5 (Full Team + CJ Flow)
```

---

## File Inventory Summary

**28 new files** + **9 modified files** across 5 phases.

| Phase | New | Modified | Unit Tests |
|-------|-----|----------|------------|
| 1 | 10 | 2 | 1 |
| 2 | 2 | 2 | 1 |
| 3 | 1 | 3 | 1 |
| 4 | 6 | 3 | 3 |
| 5 | 4 + router + LORA | 4 | 1 |

**Total**: ~58 tasks across all phases.

---

## Verification Plan

### Per-Phase Gates
1. **Phase 1**: `python -m cosa.agents.swe_team "test" --dry-run` -> notifications fire, no errors
2. **Phase 2**: Simple task E2E -> coder produces code, lead verifies
3. **Phase 3**: Task requiring tests -> coder+tester loop terminates correctly
4. **Phase 4**: Proxy in L1 shadow mode -> predictions logged, no autonomous action
5. **Phase 5**: `POST /api/swe-team/submit` -> job queued -> runs -> done

### Regression Check
- `pytest src/tests/unit/ -v` — all existing tests still pass after each phase
- WebSocket smoke tests: `src/scripts/run-websocket-smoke-tests.sh`
- No changes to existing agent behavior (Deep Research, Podcast, CRUD)

### Final Validation
- Full SWE team task: "Implement a health check endpoint at /healthz with tests"
- All 5 testing surfaces pass
- Morning ratification endpoint functional (Phase 4)
- Voice routing: spoken "start an swe team task" -> correct classification
