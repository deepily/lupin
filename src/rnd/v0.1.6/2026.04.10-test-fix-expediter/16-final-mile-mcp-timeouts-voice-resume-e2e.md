# Final Mile — MCP Timeouts + Voice Resume + Live E2E

## Context

Session 9056c113 landed the full checkpoint-resume stack across TFE + BFE + Podcast, plus the smart file-path resume endpoint for TFE. Two pieces are still deferred, and one validation step remains:

1. **MCP timeout detection** (task #14) — checkpoint infrastructure exists but no real trigger. Both TFE's `_aggregate_voice_gate()` and BFE's two voice gates catch all exceptions generically and auto-approve/auto-select. No stall ever actually happens in production.

2. **Voice expeditor integration for TFE resume** (task #13) — the REST endpoint + UI card are wired, but spoken `"resume the TFE plan from April 12"` doesn't yet flow through the LORA classifier → expeditor → auto-resolve.

3. **Live TFE resume E2E validation** (task #11) — requires tasks #14 and ideally #13 landed so the validation actually exercises the full stall-and-resume cycle.

Exploration uncovered a critical finding: the cosa-voice MCP server **already signals timeouts via `NotificationResponse.exit_code == 2`**. The bug is that `AgentNotificationDispatcher` (at `src/cosa/agents/utils/agent_notification_dispatcher.py`) silently returns the default without preserving the timeout signal. Fixing this one file fires the existing checkpoint-resume path for **both TFE and BFE** — the cleanest possible intervention point.

---

## Sequencing (with rationale)

```
Phase 1 (Task #14) — MCP timeout detection      ┐
                                                 │ Enables real stalls
                                                 │
Phase 2 (Task #13) — Voice expeditor integration ┤
                                                 │ Enables voice-driven resume
                                                 │
Phase 3 (Task #11) — Live TFE resume E2E         ┘ Validates the whole loop
```

**Why this order**:
- Phase 1 is a prerequisite for Phase 3 (no stalls = nothing to resume from = E2E test is meaningless)
- Phase 2 expands Phase 3's validation surface (tests voice routing too, not just UI)
- Phase 3 requires CoSA submodule commit + server restart anyway, so landing Phase 1 and 2 together minimizes restart cycles

---

## Phase 1: MCP Timeout Detection → VoiceGateTimeoutError

**Goal**: Modify `AgentNotificationDispatcher` so a real user timeout (MCP `exit_code == 2`) raises `VoiceGateTimeoutError` instead of silently returning the default. Both TFE and BFE voice gates get this for free.

### Files to modify (CoSA submodule)

- `src/cosa/agents/utils/agent_notification_dispatcher.py` — core fix
- `src/cosa/agents/bug_fix_expediter/orchestrator.py` — wrap existing voice gate calls to catch VoiceGateTimeoutError and raise StalledException
- `src/cosa/agents/test_fix_expediter/orchestrator.py` — verify existing `_aggregate_voice_gate` catch is sufficient (likely already works)

### Step 1.1: Dispatcher raises VoiceGateTimeoutError on exit_code==2

In `agent_notification_dispatcher.py`:

**`ask_confirmation()` (lines ~181-227)** — change from:
```python
if response.exit_code == 0 and response.response_value:
    return response.response_value.lower().strip().startswith("yes")
return default == "yes"   # ← swallows timeout
```
to:
```python
if response.exit_code == 0 and response.response_value:
    return response.response_value.lower().strip().startswith("yes")
if response.exit_code == 2:
    # Import lazily to avoid circular import (dispatcher is in utils/, TFE state imports from utils)
    from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError
    raise VoiceGateTimeoutError( phase="confirmation", message=f"ask_confirmation timeout ({timeout}s)" )
return default == "yes"   # other errors still fall back
```

**`present_choices()` (lines ~271-323)** — same pattern, raise on `exit_code == 2`.

### Step 1.2: BFE orchestrator catches VoiceGateTimeoutError

BFE's voice gates currently have `try/except Exception → auto-approve`. Update both `_voice_gate_diagnosis()` and `_voice_gate_proposal()` to:

```python
try:
    # existing ask_confirmation / present_choices call
    ...
except VoiceGateTimeoutError:
    raise   # propagate up to run_diagnosis/run_proposal
except Exception as e:
    # existing auto-approve fallback unchanged
    ...
```

Then in the calling phase methods (`run_diagnosis`, `run_proposal`), add the stall trap:

```python
try:
    confirmed = await self._voice_gate_diagnosis( ... )
except VoiceGateTimeoutError:
    checkpoint = self.save_checkpoint()
    raise StalledException(
        checkpoint = checkpoint,
        phase      = BFEPhase.DIAGNOSING.value,
        message    = "Voice gate timeout at diagnosis",
    )
```

### Step 1.3: TFE verification

TFE's `_aggregate_voice_gate` already has `except VoiceGateTimeoutError: raise` in place (session 9056c113 Phase C). Once the dispatcher raises it, TFE's existing path works. **No code change needed**; just verify with a test.

### Step 1.4: Unit tests

New file `src/tests/unit/test_mcp_timeout_detection.py`:
- `test_ask_confirmation_raises_voice_gate_timeout_on_exit_code_2` — mock NotificationResponse with exit_code=2, verify raise
- `test_ask_confirmation_returns_default_on_other_errors` — exit_code=1 still falls back
- `test_present_choices_raises_voice_gate_timeout_on_exit_code_2`
- `test_bfe_diagnosis_gate_raises_stalled_on_timeout` — end-to-end with mocked dispatcher
- `test_tfe_aggregate_gate_raises_stalled_on_timeout` — same for TFE

### Verification

```bash
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/utils/agent_notification_dispatcher.py', doraise=True )"
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_mcp_timeout_detection.py src/tests/unit/test_bfe_*.py src/tests/unit/test_tfe_*.py -v
```

---

## Phase 2: Voice Expeditor Integration for TFE Resume

**Goal**: Wire the existing TFE resume endpoint into the voice pipeline so `"resume the TFE plan from April 12"` works end-to-end.

### Files to modify (CoSA submodule)

- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` — new agent entry
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` — new handler method

### Files to add (Lupin parent)

- `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter-resume.txt` — 30 voice templates
- Registration in `src/conf/training/agent-router-agentic-commands.json`

### Step 2.1: Agent registry entry

In `agent_registry.py` (search for the existing test_fix_expediter entry and add a sibling):

```python
"agent router go to test fix expediter resume" : {
    "display_name"       : "TFE Resume",
    "job_type"           : "tfe_resume",
    "required_user_args" : [ "resume_from" ],
    "optional_user_args" : [],
    "system_args"        : [ "user_email", "user_id", "session_id" ],
    "special_handlers"   : {
        "resume_from" : "tfe_checkpoint_match",
    },
}
```

### Step 2.2: Expeditor handler

In `expeditor.py` (after `_handle_fuzzy_file_match` around line 844):

```python
def _handle_tfe_checkpoint_match( self, user_email: str, user_description: str = None ) -> Optional[str]:
    """
    Fuzzy match user's description of a stalled TFE job or plan doc.

    Reuses resume_resolver.list_resume_candidates + fuzzy_match_candidates
    (already implemented in session 9056c113 doc 15 Phase 2).

    Returns:
        str: Resolved job_id or plan path for the REST endpoint to dispatch
    """
    from cosa.agents.test_fix_expediter.resume_resolver import (
        list_resume_candidates, fuzzy_match_candidates,
    )

    candidates = list_resume_candidates( user_email )
    if not candidates:
        return self._ask_for_arg( "resume_from",
            "No stalled TFE jobs or recent plans found. Provide a job ID or plan path.",
            user_email )

    if not user_description:
        user_description = self._ask_for_arg( "resume_from",
            "Which TFE job would you like to resume?",
            user_email )
        if not user_description:
            return None

    matches = fuzzy_match_candidates( user_description, candidates, debug=self.debug )

    # Auto-accept if top match confidence >= 0.9 AND is stalled
    if matches and matches[ 0 ][ "confidence" ] >= 0.9 and matches[ 0 ].get( "status" ) == "stalled":
        return matches[ 0 ][ "job_id" ]

    # Multi-match disambiguation via existing _ask_for_arg pattern
    if not matches:
        return self._ask_for_arg( "resume_from",
            "Couldn't match any job. Please provide a job ID or paste a plan path.",
            user_email )

    # Single low-confidence or multiple matches — ask user to pick
    options_str = ", ".join(
        f"{i + 1}. {m['job_id']} ({m.get('summary', '?')[:40]})"
        for i, m in enumerate( matches[ :3 ] )
    )
    pick = self._ask_for_arg( "resume_from",
        f"Found {len( matches )} possible matches: {options_str}. Say the number or job ID.",
        user_email )
    if not pick:
        return None

    try:
        idx = int( pick.strip() ) - 1
        if 0 <= idx < len( matches ):
            return matches[ idx ][ "job_id" ]
    except ValueError:
        pass

    # Partial string match fallback
    for m in matches:
        if pick.lower().strip() in m[ "job_id" ].lower():
            return m[ "job_id" ]

    return matches[ 0 ][ "job_id" ]   # fallback to top match
```

Then register this handler in the main `_handle_special_arg()` dispatch (around line 264-277 where `fuzzy_file_match` is handled).

### Step 2.3: Factory routing

The existing `agentic_job_factory.create_agentic_job()` needs an elif branch for `"agent router go to test fix expediter resume"` that calls the **existing** `resume_job()` factory (session 9056c113 Phase D) with the resolved `resume_from` value — or better, routes through the **existing** `POST /api/test-fix-expediter/resume-from` endpoint as an internal call.

Simplest: have the voice command invoke the endpoint programmatically via an internal HTTP call, OR refactor `resume_tfe_smart` endpoint logic into a reusable async function that both the endpoint AND the factory can call. The latter is cleaner.

### Step 2.4: PEFT training templates

New file `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter-resume.txt` with ~30 examples:

```
Resume the TFE plan from April 12
Pick up the stalled test fix expediter
Continue the TFE job from this morning
Resume job tfe-7c25082a
Continue where TFE left off
Resume the most recent stalled TFE
Resume the visual regression fix
Resume TFE job, the one awaiting input
...
```

Register in `src/conf/training/agent-router-agentic-commands.json`. Add to `AGENTIC_TEMPLATES` whitelist in `test_swe_team_training_data.py`.

**USER-RUN only**: The PEFT trainer is NOT invoked by this plan. User runs `./src/scripts/run-agentic-intent-training.sh test` (sanity) then `full` on their own GPU schedule.

### Step 2.5: Unit tests

New file `src/tests/unit/test_tfe_resume_expeditor.py`:
- `test_handle_tfe_checkpoint_match_with_high_confidence_auto_selects`
- `test_handle_tfe_checkpoint_match_with_ambiguous_asks_user`
- `test_handle_tfe_checkpoint_match_no_candidates_prompts_manual`
- `test_agent_registry_has_tfe_resume_entry`

### Verification

```bash
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/runtime_argument_expeditor/expeditor.py', doraise=True )"
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_tfe_resume_expeditor.py -v
```

---

## Phase 3: Live TFE Resume E2E Validation (Task #11)

**Goal**: End-to-end validation of the full stall-and-resume loop against a real server.

**Precondition**: Phase 1 and 2 CoSA edits committed + server restarted.

### Steps

1. **Pre-flight**: Confirm server log shows `[Watchdogs] BFE=ENABLED, TFE=ENABLED` after restart.

2. **Force a stall**: Submit a TFE job via `POST /api/test-suite/submit` with a known-failing test suite AND `test fix expediter feedback timeout seconds = 5` temporarily set in INI (low timeout forces the MCP to hit `exit_code == 2`). Do NOT respond to the voice gate.

3. **Verify stall**:
   - Voice notification received: `"TFE stalled at proposing — resume when ready"`
   - UI job card shows stalled badge (`⏸`) + "Resume from Checkpoint" button + "View Plan" link
   - `GET /api/queue/todo` (or equivalent) returns the stalled job
   - `job_history` row has `status=stalled` and `metadata_json.artifacts.checkpoint` populated

4. **Resume via UI button**: Click "Resume from Checkpoint" on the stalled card.
   - New TFE job created with incremented `resume_count`
   - Original orchestrator state loaded: clusters, diagnoses, proposals restored
   - Phase ordinal 0-2 skipped, resumes at Phase 3 (fixing)

5. **Resume via smart endpoint**: Submit a separate stall, then from the TFE Resume card paste the plan doc path → `POST /api/test-fix-expediter/resume-from` → verify same restoration.

6. **Resume via voice** (Phase 2 gated): Speak `"resume the TFE plan from today"` → LORA classifies → expeditor fuzzy-matches → resumes. Validate the activity log shows the voice command routed correctly.

7. **Resume via natural-language typed input**: Type `"the visual regression one"` into the TFE Resume textarea → LLM fuzzy matcher ranks candidates → auto-resumes if high confidence or shows disambiguation.

### Success criteria

- All 7 resume paths succeed without error
- Resumed job reaches Phase 6 (RESUBMITTING) and queues a validation TestSuiteJob
- No regression in existing test suite (3169+ baseline preserved)
- Log trace shows `checkpoint.resume_count == 1` after first resume

### Test script

Shell driver at `src/tests/e2e/run-tfe-resume-e2e.sh` with `--dry-run` (mocks + env overrides) and `--live` (real server + real failing suite). Cost gate: ~$2-8 depending on cluster count.

---

## File Summary

### CoSA submodule (all working-tree only, user commits separately)

**Phase 1**:
- `agents/utils/agent_notification_dispatcher.py` (2 methods modified — `ask_confirmation`, `present_choices`)
- `agents/bug_fix_expediter/orchestrator.py` (wrap 2 voice gate callers in run_diagnosis + run_proposal)

**Phase 2**:
- `agents/runtime_argument_expeditor/agent_registry.py` (1 new entry)
- `agents/runtime_argument_expeditor/expeditor.py` (1 new handler + 1 dispatch case)
- `rest/agentic_job_factory.py` (1 new elif branch OR refactor shared async fn)
- `rest/routers/queues.py` (potential extraction of resume-from handler into shared fn)

### Lupin parent repo

**Phase 1**:
- `src/tests/unit/test_mcp_timeout_detection.py` (new — ~5 tests)

**Phase 2**:
- `src/tests/unit/test_tfe_resume_expeditor.py` (new — ~4 tests)
- `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter-resume.txt` (new)
- `src/conf/training/agent-router-agentic-commands.json` (register new command)
- `src/tests/unit/test_swe_team_training_data.py` (AGENTIC_TEMPLATES whitelist)

**Phase 3**:
- `src/tests/e2e/run-tfe-resume-e2e.sh` (new shell driver)
- `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/16-final-mile-mcp-timeouts-voice-resume-e2e.md` (serialized plan)

**Skill doc** (Lupin parent — after all phases land):
- `src/workflow/agentic-voice-workflow.md` v3.2 → v3.3 with MCP timeout detection wire-up in Phase 12

---

## Verification Ladder

| Phase | Verification | Scope |
|-------|-------------|-------|
| 1 | Unit tests for dispatcher + orchestrator gate catching | CoSA working tree |
| 1 | Full TFE + BFE + JobState regression | 490+ tests still green |
| 2 | Unit tests for expeditor handler | new tests pass |
| 2 | (Optional) PEFT trainer test run | USER-RUN |
| 3 | Live server E2E — all 7 resume paths | Real MCP + real voice gate |
| 3 | Zero regression in nightly automated suite | Pattern compliance |

---

## CoSA Submodule Rule

All CoSA edits stay working-tree only from Lupin context. User commits CoSA in a separate session before Phase 3 live E2E. Per standing rule since session 9056c113 inception.
