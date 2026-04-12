# TFE Checkpoint-Resume + Completion Report — Full Implementation Plan

**Date**: 2026-04-12
**Session**: 9056c113
**Status**: Design — pending user review
**Trigger**: TFE job `tfe-7c25082a` stalled at Phase 2 voice gate with 0 selections; user wants (a) completion voice reports, (b) checkpoint-resume so stalled jobs can be continued later, (c) both patterns standardized in the agentic-voice-workflow skill

---

## Forensic Summary — tfe-7c25082a

| Phase | Status | Detail |
|-------|--------|--------|
| Phase 0: Clustering | Ran | 1 cluster (C1), 12 visual regression failures, 82% confidence |
| Phase 1: Diagnosis | Ran | Environment mismatch — uid 1001 baselines vs Docker root |
| Phase 2: Proposal | Ran | 3 fixes proposed, **0 selected** at voice gate |
| Phase 3-6 | Skipped | Guards cascaded from empty selections |

**Root cause of missing resubmission**: Phase 6 guard requires successful fixes. Zero selections → zero fixes → no rerun. By design, not a bug. But the job should have **stalled** at the voice gate instead of silently completing with nothing done.

---

## Implementation Phases

### Phase A: TFE Completion Report

**Goal**: Add voice notification to TFE success path, mirroring Deep Research pattern.

**Files to modify**:
- `src/cosa/agents/test_fix_expediter/job.py` (CoSA submodule)
- `src/tests/unit/test_tfe_forensics.py` (Lupin parent)

#### Step A1: Add `_start_time` to `_execute()` entry

In `job.py`, at the top of `_execute()` (line ~180, after the method signature and docstring):

```python
import time
self._start_time = time.time()
```

#### Step A2: Compute `total_failures` from orchestrator

Need to verify how to get total failure count. The orchestrator has `self.remediation_context.failures` (a list). Use `len( self.orchestrator.remediation_context.failures )` as the total.

#### Step A3: Replace success return block (lines 265-276)

Replace the current artifacts + return block with:

```python
# Populate artifacts for UI
self.artifacts[ "remediation_snapshot_path" ] = self.remediation_snapshot_path
self.artifacts[ "source_test_suite_job_id" ]  = self.source_test_suite_job_id
self.artifacts[ "cluster_count" ]             = len( clusters )
self.artifacts[ "fix_count" ]                 = len( fix_results )
self.artifacts[ "validation_run_job_id" ]     = validation_run_job_id
if self.orchestrator.last_plan_path:
    self.artifacts[ "plan_path" ] = self.orchestrator.last_plan_path

# Build completion report
n_clusters     = len( clusters )
n_failures     = len( self.orchestrator.remediation_context.failures )
n_proposed     = len( self.orchestrator.proposed_fixes )
n_selected     = len( self.orchestrator.selected_fixes )
n_fixed        = sum( 1 for r in fix_results if r.success )
n_failed_fixes = sum( 1 for r in fix_results if not r.success )
duration       = round( time.time() - self._start_time, 1 )
rerun_status   = (
    f"Validation queued: {validation_run_job_id}"
    if validation_run_job_id
    else "No rerun (no successful fixes)"
)

# Brief TTS message — outcome-aware
if n_fixed > 0:
    tts_msg = (
        f"Test Fix Expediter complete. "
        f"{n_fixed} fix{'es' if n_fixed != 1 else ''} applied "
        f"across {n_clusters} cluster{'s' if n_clusters != 1 else ''}."
    )
elif n_selected == 0:
    tts_msg = (
        f"Test Fix Expediter complete. "
        f"{n_clusters} cluster{'s' if n_clusters != 1 else ''} diagnosed, "
        f"no fixes selected."
    )
else:
    tts_msg = (
        f"Test Fix Expediter complete. "
        f"{n_selected} fix{'es' if n_selected != 1 else ''} attempted, "
        f"{n_failed_fixes} failed."
    )

# Rich markdown abstract (UI-only, not spoken)
lines = [ "**TFE Activity Report**", "" ]
lines.append( f"**Source**: `{self.source_test_suite_job_id}`" )
lines.append( f"**Clusters**: {n_clusters} (from {n_failures} failures)" )
lines.append(
    f"**Proposed**: {n_proposed} | **Selected**: {n_selected} | "
    f"**Fixed**: {n_fixed} | **Failed**: {n_failed_fixes}"
)
if self.orchestrator.last_plan_path:
    lines.append( f"**Plan**: `{self.orchestrator.last_plan_path}`" )
lines.append( f"**Rerun**: {rerun_status}" )
lines.append( f"**Duration**: {duration}s" )

# Per-cluster diagnosis detail
if self.orchestrator.diagnoses:
    lines.append( "" )
    lines.append( "**Cluster Diagnoses:**" )
    for cid, diag in self.orchestrator.diagnoses.items():
        conf = f"{diag.confidence:.0%}" if hasattr( diag, "confidence" ) else "?"
        lines.append(
            f"- **{cid}**: {diag.root_cause[ :120 ]} ({conf}, {diag.error_category})"
        )

completion_abstract = "\n".join( lines )

try:
    await voice_io.notify(
        tts_msg,
        priority   = "medium",
        abstract   = completion_abstract,
        job_id     = self.id_hash,
        queue_name = "run",
    )
except Exception as notify_err:
    print( f"[TestFixExpediterJob] completion notify failed: {notify_err}" )

# Conversational answer
return (
    f"TFE complete: {n_clusters} clusters, {n_proposed} proposed, "
    f"{n_selected} selected, {n_fixed} fixed. {rerun_status}. "
    f"Source: {self.source_test_suite_job_id}."
)
```

#### Step A4: Add `import time` to imports

Add `import time` to the stdlib imports at top of `job.py`.

#### Step A5: Unit test for completion notification

In `test_tfe_forensics.py`, add a test that mocks `voice_io.notify` and verifies it's called on the success path with the expected TTS message and abstract containing per-cluster detail.

#### Step A6: Verify

```bash
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/test_fix_expediter/job.py', doraise=True )"
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_tfe_forensics.py -v
```

---

### Phase B: `STALLED` JobState + Transition Matrix

**Goal**: Add new state to the unified job state machine.

**Files to modify**:
- `src/cosa/rest/job_state.py` (CoSA submodule)
- `src/tests/unit/test_job_state.py` (Lupin parent — create if not exists)

#### Step B1: Add STALLED enum member

In `job_state.py`, after `CANCELLED` (line 37):

```python
STALLED     = "stalled"      # Voice gate timeout — waiting for user, resumable
```

#### Step B2: Update transition matrix

```python
VALID_TRANSITIONS = {
    ...
    JobState.RUNNING     : frozenset( { JobState.COMPLETED, JobState.FAILED,
                                        JobState.CANCELLED, JobState.INTERRUPTED,
                                        JobState.STALLED } ),
    JobState.STALLED     : frozenset( { JobState.RUNNING, JobState.CANCELLED } ),
    ...
}
```

#### Step B3: Update convenience sets

```python
TERMINAL_STATES       = frozenset( { JobState.COMPLETED, JobState.FAILED,
                                     JobState.CANCELLED, JobState.INTERRUPTED } )
                                     # STALLED is NOT terminal
PRE_EXECUTION_STATES  = frozenset( { JobState.PENDING, JobState.QUEUED,
                                     JobState.SCHEDULED, JobState.PAUSED } )
ACTIVE_STATES         = frozenset( { JobState.RUNNING } )
RESUMABLE_STATES      = frozenset( { JobState.STALLED } )   # NEW convenience set
```

#### Step B4: Update UI container mapping

```python
STATE_TO_UI_CONTAINER = {
    ...
    JobState.STALLED     : "todo",   # Shows in todo with "stalled" badge
}
```

#### Step B5: Unit tests

Test cases:
- `RUNNING → STALLED` is valid
- `STALLED → RUNNING` is valid (resume)
- `STALLED → CANCELLED` is valid (user gives up)
- `STALLED → COMPLETED` is **invalid** (must go through RUNNING first)
- `STALLED → FAILED` is **invalid**
- STALLED is not in `TERMINAL_STATES`
- STALLED is in `RESUMABLE_STATES`
- STALLED maps to "todo" UI container

#### Step B6: Verify

```bash
python -c "import py_compile; py_compile.compile( 'src/cosa/rest/job_state.py', doraise=True )"
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_job_state.py -v  # or wherever state tests live
```

---

### Phase C: Checkpoint Infrastructure

**Goal**: Exception types, checkpoint data model, serialization on orchestrator, stall handling in job.

**Files to modify**:
- `src/cosa/agents/agentic_job_base.py` — add `CheckpointData` TypedDict, stall-aware `do_all()` pattern (CoSA)
- `src/cosa/agents/test_fix_expediter/state.py` — add `VoiceGateTimeoutError`, `StalledException` (CoSA)
- `src/cosa/agents/test_fix_expediter/orchestrator.py` — add `save_checkpoint()`, `load_checkpoint()`, `resume_from_phase()` (CoSA)
- `src/cosa/agents/test_fix_expediter/job.py` — catch `StalledException` in `_execute()` + `do_all()` (CoSA)
- `src/cosa/agents/test_fix_expediter/cosa_interface.py` — voice gate timeout detection (CoSA)
- `src/cosa/rest/job_persistence.py` — persist checkpoint in metadata_json (CoSA)
- `src/tests/unit/test_tfe_checkpoint.py` — round-trip serialization + stall flow tests (Lupin)

#### Step C1: Exception types in `state.py`

Add after `TFEState` (around line 205):

```python
class VoiceGateTimeoutError( Exception ):
    """
    Voice gate timed out without user response.

    Requires:
        - phase is a valid TFEPhase value string

    Ensures:
        - Carries the phase where timeout occurred
    """
    def __init__( self, phase: str, message: str = "" ):
        self.phase = phase
        super().__init__( message or f"Voice gate timeout at {phase}" )


class StalledException( Exception ):
    """
    Orchestrator requests a clean stall with checkpoint.

    Requires:
        - checkpoint is a JSON-serializable dict
        - phase is a valid TFEPhase value string

    Ensures:
        - job._execute() catches this and transitions to STALLED
        - NOT treated as a failure — this is a clean yield point
    """
    def __init__( self, checkpoint: dict, phase: str, message: str = "" ):
        self.checkpoint = checkpoint
        self.phase      = phase
        super().__init__( message or f"Stalled at {phase}" )
```

#### Step C2: CheckpointData TypedDict in `state.py`

Add after the exception types:

```python
class CheckpointData( TypedDict ):
    """Serialized mid-execution state for resume."""
    phase_ordinal  : int     # Ordinal of last completed phase (0=loading, 1=clustering, ...)
    phase_name     : str     # Human-readable (e.g., "PROPOSING")
    stall_reason   : str     # "voice_gate_timeout", "rate_limit", "user_cancel"
    stalled_at     : str     # ISO timestamp
    state_snapshot : dict    # Serialized TFEState (JSON-safe)
    artifacts      : dict    # Paths to durable artifacts created so far
    resume_count   : int     # How many times this job has been resumed (starts at 0)
```

#### Step C3: Phase ordinal mapping in `state.py`

```python
TFE_PHASE_ORDINALS = {
    TFEPhase.LOADING      : 0,
    TFEPhase.CLUSTERING   : 1,
    TFEPhase.DIAGNOSING   : 2,
    TFEPhase.PROPOSING    : 3,
    TFEPhase.FIXING       : 4,
    TFEPhase.COMMITTING   : 5,
    TFEPhase.RESUBMITTING : 6,
}
```

#### Step C4: `save_checkpoint()` on orchestrator

Add to `TFEOrchestrator` class:

```python
def save_checkpoint( self ) -> dict:
    """
    Serialize current pipeline state to a JSON-safe dict.

    Requires:
        - Called after at least one phase has completed

    Ensures:
        - Returns dict matching CheckpointData schema
        - All Pydantic models converted to dicts via .model_dump()
        - Cluster list, diagnosis dict, proposal list all serialized
    """
    from cosa.agents.test_fix_expediter.state import TFE_PHASE_ORDINALS

    state_snapshot = {
        "source_test_suite_job_id"  : self.remediation_context.source_test_suite_job_id,
        "remediation_snapshot_path" : self.remediation_context.snapshot_path,
        "clusters"                  : [ c.model_dump() for c in self.clusters ],
        "diagnoses"                 : { k: v.model_dump() for k, v in self.diagnoses.items() },
        "proposed_fixes"            : [ p.model_dump() for p in self.proposed_fixes ],
        "selected_fixes"            : [ s.model_dump() for s in self.selected_fixes ],
        "fix_results"               : [ r.model_dump() if hasattr( r, "model_dump" ) else r
                                        for r in self.fix_results ],
        "files_changed_by_cluster"  : dict( self.files_changed_by_cluster ),
        "last_plan_path"            : self.last_plan_path,
        "branch_name"               : self.branch_name,
        "commit_hashes"             : list( self.commit_hashes ),
        "pr_url"                    : self.pr_url,
        "validation_run_job_id"     : self.validation_run_job_id,
    }

    artifacts = {}
    if self.last_plan_path: artifacts[ "plan_path" ] = self.last_plan_path

    return {
        "phase_ordinal"  : TFE_PHASE_ORDINALS.get( self.current_phase, -1 ),
        "phase_name"     : self.current_phase.value,
        "stall_reason"   : "voice_gate_timeout",
        "stalled_at"     : datetime.now().isoformat(),
        "state_snapshot" : state_snapshot,
        "artifacts"      : artifacts,
        "resume_count"   : 0,
    }
```

#### Step C5: `load_checkpoint()` on orchestrator

```python
def load_checkpoint( self, data: dict ) -> None:
    """
    Restore pipeline state from a previously saved checkpoint.

    Requires:
        - data matches CheckpointData schema
        - self.remediation_context is already loaded (snapshot_loader ran)

    Ensures:
        - All instance attributes restored to checkpoint values
        - Pydantic models reconstructed from dicts
    """
    from cosa.agents.test_fix_expediter.state import (
        FailureCluster, TestDiagnosisResult, TFEProposedFix, TFEPhase
    )

    snap = data[ "state_snapshot" ]

    self.clusters                = [ FailureCluster( **c ) for c in snap.get( "clusters", [] ) ]
    self.diagnoses               = { k: TestDiagnosisResult( **v )
                                     for k, v in snap.get( "diagnoses", {} ).items() }
    self.proposed_fixes          = [ TFEProposedFix( **p ) for p in snap.get( "proposed_fixes", [] ) ]
    self.selected_fixes          = [ TFEProposedFix( **s ) for s in snap.get( "selected_fixes", [] ) ]
    self.fix_results             = snap.get( "fix_results", [] )
    self.files_changed_by_cluster = snap.get( "files_changed_by_cluster", {} )
    self.last_plan_path          = snap.get( "last_plan_path" )
    self.branch_name             = snap.get( "branch_name" )
    self.commit_hashes           = snap.get( "commit_hashes", [] )
    self.pr_url                  = snap.get( "pr_url" )
    self.validation_run_job_id   = snap.get( "validation_run_job_id" )
    self.current_phase           = TFEPhase( data[ "phase_name" ] )
```

#### Step C6: `resume_from_phase()` on orchestrator

```python
def set_resume_phase( self, phase_ordinal: int ) -> None:
    """
    Mark phases up to phase_ordinal as already completed.
    The next call to the phase runner will skip completed phases.

    Requires:
        - phase_ordinal >= 0
        - load_checkpoint() has already been called

    Ensures:
        - self._resume_from_ordinal is set
        - Phase methods check this and skip if already done
    """
    self._resume_from_ordinal = phase_ordinal
```

Each phase method gets a guard at the top:

```python
async def run_phase2_propose( self ):
    # Resume guard
    if hasattr( self, "_resume_from_ordinal" ) and self._resume_from_ordinal >= 3:
        await self._notify( "Phase 2 skipped (resumed from checkpoint)", priority="low" )
        return ( self.proposed_fixes, self.selected_fixes, self.last_plan_path )
    ...
```

#### Step C7: Voice gate timeout → `VoiceGateTimeoutError`

In `orchestrator.py`, modify `_aggregate_voice_gate()` (around line 903):

**Current**:
```python
except Exception as e:
    logger.warning( f"[TFE] Voice gate failed: {e} — auto-selecting all" )
    return list( proposals )
```

**New**:
```python
except VoiceGateTimeoutError:
    # Don't auto-select — let the stall propagate
    raise
except Exception as e:
    logger.warning( f"[TFE] Voice gate failed: {e} — auto-selecting all" )
    return list( proposals )
```

And in `run_phase2_propose()`, wrap the voice gate call:

```python
try:
    self.selected_fixes = await self._proposal_voice_gate( all_proposals )
except VoiceGateTimeoutError:
    checkpoint = self.save_checkpoint()
    raise StalledException(
        checkpoint = checkpoint,
        phase      = TFEPhase.PROPOSING.value,
        message    = f"Voice gate timeout at Phase 2 — {len( all_proposals )} proposals await review",
    )
```

#### Step C8: Detect timeout in `cosa_interface.py`

The timeout detection depends on how `present_choices` reports timeouts. Check if the cosa-voice MCP returns a specific timeout indicator. If the MCP returns a timeout response (e.g., `{"error": "timeout"}`), wrap it:

```python
async def present_choices( *args, **kwargs ):
    result = await _bfe_present_choices( *args, **kwargs )
    # Check if result indicates timeout (no user response)
    if _is_timeout_response( result ):
        raise VoiceGateTimeoutError( phase="proposing" )
    return result
```

**Alternative**: If the MCP raises an exception on timeout, the existing `except Exception` in the orchestrator already catches it. In that case, distinguish timeout from other exceptions by checking the exception message or type.

**Investigation needed during implementation**: Check actual MCP timeout behavior by reading `cosa_interface._bfe_present_choices` and the cosa-voice server response format for timeouts vs explicit empty selections.

#### Step C9: Stall handling in `_execute()` and `do_all()`

In `job.py _execute()`, add a catch before the generic Exception handler:

```python
except StalledException as stall:
    # Persist checkpoint to artifacts for metadata_json
    self.artifacts[ "checkpoint" ] = stall.checkpoint
    if stall.checkpoint.get( "artifacts", {} ).get( "plan_path" ):
        self.artifacts[ "plan_path" ] = stall.checkpoint[ "artifacts" ][ "plan_path" ]

    # Voice notification
    try:
        await voice_io.notify(
            f"TFE stalled at {stall.phase} — resume when ready",
            priority = "high",
            abstract = (
                f"**TFE Stalled**\n\n"
                f"**Phase**: {stall.phase}\n"
                f"**Reason**: {stall.checkpoint[ 'stall_reason' ]}\n"
                f"**Clusters diagnosed**: {len( self.orchestrator.clusters )}\n"
                f"**Proposals awaiting review**: {len( self.orchestrator.proposed_fixes )}\n\n"
                f"Resume via UI 'Resume' button or API `POST /api/jobs/{self.id_hash}/resume`"
            ),
            job_id     = self.id_hash,
            queue_name = "todo",
        )
    except Exception as notify_err:
        print( f"[TestFixExpediterJob] stall notify failed: {notify_err}" )

    # Return a special sentinel that do_all() recognizes
    return "__STALLED__"
```

In `do_all()`, add stall detection after `_execute()` returns:

```python
result = asyncio.run( self._execute() )

if result == "__STALLED__":
    self.state = JobState.STALLED
    self.answer_conversational = (
        f"TFE stalled at voice gate. {len( self.orchestrator.proposed_fixes )} "
        f"proposals await your review. Resume when ready."
    )
    return self.answer_conversational
```

#### Step C10: Persist stalled state in `job_persistence.py`

Add `"checkpoint"` to the `rich_fields` list in `_build_metadata_json()`:

```python
rich_fields = [
    "response_text", "abstract", "report_link",
    "cost_summary", "artifacts", "answer_conversational",
    "push_counter", "agent_type", "stack_trace",
    "scheduled_at", "monopolize",
    "original_args",
    "checkpoint",    # NEW — checkpoint data for stalled jobs
]
```

Also need a `persist_job_stalled_from_metadata()` function or handle `STALLED` as a variant of the completion persistence path. Simplest: treat stall as a special completion (status=stalled instead of completed), reuse `persist_job_completed_from_metadata` but override status.

#### Step C11: Unit tests for checkpoint round-trip

New file `src/tests/unit/test_tfe_checkpoint.py`:

- `test_save_checkpoint_serializes_clusters` — populate orchestrator with mock clusters/diagnoses, call `save_checkpoint()`, verify JSON structure
- `test_load_checkpoint_restores_state` — serialize → load → verify attributes match
- `test_save_load_round_trip` — full round-trip with all fields
- `test_stalled_exception_carries_checkpoint` — verify `StalledException.checkpoint` is the expected dict
- `test_voice_gate_timeout_propagates` — mock `present_choices` to raise `VoiceGateTimeoutError`, verify `StalledException` is raised from `run_phase2_propose`
- `test_stall_sets_job_state` — mock the full `_execute()` stall path, verify `do_all()` sets `state = STALLED`
- `test_checkpoint_in_artifacts` — verify checkpoint data appears in `self.artifacts["checkpoint"]`
- `test_resume_guard_skips_completed_phases` — set `_resume_from_ordinal = 3`, verify phases 0-2 are skipped

#### Step C12: Verify

```bash
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/test_fix_expediter/state.py', doraise=True )"
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/test_fix_expediter/orchestrator.py', doraise=True )"
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/test_fix_expediter/job.py', doraise=True )"
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_tfe_checkpoint.py -v
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/ -v --tb=short  # full regression
```

---

### Phase D: Resume Infrastructure

**Goal**: REST endpoint, CLI flag, UI button, job factory resume path.

**Files to modify**:
- `src/cosa/rest/routers/queues.py` — add `POST /api/jobs/{id_hash}/resume` (CoSA)
- `src/cosa/rest/routers/test_fix_expediter.py` — add `POST /api/test-fix-expediter/resume-from-file` (CoSA — new file or extend test_suite.py)
- `src/cosa/rest/agentic_job_factory.py` — add `resume_job()` + `resume_job_from_file()` factory functions (CoSA)
- `src/cosa/rest/job_persistence.py` — add `get_checkpoint_for_job()` query (CoSA)
- `src/fastapi_app/static/js/notifications.js` — "Resume" button on stalled cards + "Resume from" field on TFE submission card (Lupin)
- `src/fastapi_app/static/html/notifications.html` — stalled badge styling (Lupin)
- `src/tests/e2e/run-tfe-live-e2e.sh` — add `--resume <job_id>` and `--resume-from <path>` flags (Lupin)
- `src/tests/unit/test_tfe_resume.py` — unit tests for resume flow (Lupin)

#### Step D1: `get_checkpoint_for_job()` in `job_persistence.py`

```python
def get_checkpoint_for_job( job_id_hash: str ) -> Optional[ dict ]:
    """
    Retrieve checkpoint data for a stalled job.

    Requires:
        - job_id_hash is a valid job ID (e.g., "tfe-7c25082a::user_id")

    Ensures:
        - Returns checkpoint dict if job is stalled and has checkpoint data
        - Returns None if job not found, not stalled, or no checkpoint
    """
    session = get_session()
    row = session.query( JobHistory ).filter_by( id_hash=job_id_hash ).first()
    if not row or row.status != JobState.STALLED.value:
        return None
    metadata = row.metadata_json or {}
    checkpoint = metadata.get( "artifacts", {} ).get( "checkpoint" )
    if not checkpoint:
        checkpoint = metadata.get( "checkpoint" )
    return checkpoint
```

Also add `get_original_args_for_job()`:

```python
def get_original_args_for_job( job_id_hash: str ) -> Optional[ dict ]:
    """Retrieve original_args and routing_command for job reconstruction."""
    session = get_session()
    row = session.query( JobHistory ).filter_by( id_hash=job_id_hash ).first()
    if not row:
        return None
    metadata = row.metadata_json or {}
    return {
        "original_args"    : metadata.get( "original_args", {} ),
        "routing_command"   : row.routing_command,
        "user_id"           : row.user_id,
        "user_email"        : row.user_email,
        "session_id"        : row.session_id,
    }
```

#### Step D2: `resume_job()` in `agentic_job_factory.py`

```python
def resume_job( job_id_hash: str, config_mgr=None ) -> Optional:
    """
    Reconstruct a stalled job from its checkpoint and original args.

    Requires:
        - job_id_hash references a stalled job with checkpoint data

    Ensures:
        - Returns a fully constructed job ready for queue submission
        - Orchestrator has checkpoint loaded and resume phase set
        - Returns None if job cannot be resumed
    """
    from cosa.rest.job_persistence import get_checkpoint_for_job, get_original_args_for_job

    checkpoint = get_checkpoint_for_job( job_id_hash )
    if not checkpoint:
        return None

    job_info = get_original_args_for_job( job_id_hash )
    if not job_info:
        return None

    # Reconstruct via normal factory path
    job = create_agentic_job(
        command    = job_info[ "routing_command" ],
        args_dict  = job_info[ "original_args" ],
        user_id    = job_info[ "user_id" ],
        user_email = job_info[ "user_email" ],
        session_id = job_info[ "session_id" ],
        config_mgr = config_mgr,
    )

    if job is None:
        return None

    # Load checkpoint into orchestrator
    # The job needs to run _execute() which creates the orchestrator
    # Store checkpoint on the job for _execute() to pick up
    job._resume_checkpoint = checkpoint
    job._resume_checkpoint[ "resume_count" ] = checkpoint.get( "resume_count", 0 ) + 1

    return job
```

In `job.py _execute()`, at the top after orchestrator creation:

```python
# Check for resume checkpoint
if hasattr( self, "_resume_checkpoint" ) and self._resume_checkpoint:
    self.orchestrator.load_checkpoint( self._resume_checkpoint )
    self.orchestrator.set_resume_phase( self._resume_checkpoint[ "phase_ordinal" ] )
    print( f"[TFE] Resuming from phase ordinal {self._resume_checkpoint[ 'phase_ordinal' ]}" )
```

#### Step D3: REST endpoint in `routers/queues.py`

```python
@router.post( "/api/jobs/{id_hash}/resume" )
async def resume_job_endpoint( id_hash: str ):
    """
    Resume a stalled job from its checkpoint.

    Requires:
        - id_hash references a stalled job with checkpoint data

    Ensures:
        - Job reconstructed and pushed to todo queue
        - Original job status updated to show it was resumed
        - Returns resumed job details
    """
    from cosa.rest.agentic_job_factory import resume_job

    job = resume_job( id_hash, config_mgr=config_mgr )
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job {id_hash} not found, not stalled, or has no checkpoint"
        )

    # Push to todo queue
    jobs_todo_queue.push( job )

    return {
        "resumed_job_id"   : job.id_hash,
        "original_job_id"  : id_hash,
        "resume_from_phase": job._resume_checkpoint[ "phase_ordinal" ],
        "phase_name"       : job._resume_checkpoint[ "phase_name" ],
        "resume_count"     : job._resume_checkpoint[ "resume_count" ],
    }
```

#### Step D4: UI "Resume" button on stalled job cards

In `notifications.js`, in the `renderJobCard()` function, add for stalled jobs:

```javascript
if ( job.status === "stalled" ) {
    const resumeBtn = document.createElement( "button" );
    resumeBtn.className = "btn btn-sm btn-warning";
    resumeBtn.textContent = "Resume";
    resumeBtn.onclick = async () => {
        const resp = await authedFetch( `/api/jobs/${job.id_hash}/resume`, { method: "POST" } );
        if ( resp.ok ) {
            const data = await resp.json();
            showToast( `Resumed from phase ${data.phase_name}`, "success" );
        } else {
            showToast( "Resume failed", "error" );
        }
    };
    cardActions.appendChild( resumeBtn );
}
```

In `notifications.html`, add stalled badge CSS:

```css
.badge-stalled {
    background-color: #f0ad4e;
    color: #000;
}
```

#### Step D4b: File-path-based resume in TFE submission card

**Pattern source**: Presentation Generator's `render_only` + `yaml_path` auto-detection (see `routers/presentation_generator.py:40,172-186`). When the user provides a YAML path, the job auto-detects render-only mode and skips Phases 1-5.

**TFE equivalent**: Add a `resume_from` field to the TFE submission path. The user provides a file path (plan doc or checkpoint JSON), and the system infers which phase to resume from.

**In `routers/test_suite.py` or a new `routers/test_fix_expediter.py`**, add to the request model:

```python
class TFEResumeRequest( BaseModel ):
    """Resume a TFE job from a file artifact."""
    resume_from         : str              # File path: plan doc (.md) or checkpoint (.json)
    remediation_snapshot: Optional[ str ]  = None  # Override snapshot path (optional)
    auto_fix_on_failure : Optional[ bool ] = None
```

**Auto-detection logic** (mirrors Presentation Generator pattern):

```python
@router.post( "/api/test-fix-expediter/resume-from-file" )
async def resume_tfe_from_file( request: TFEResumeRequest, current_user = Depends( get_current_user ) ):
    """
    Resume TFE from a file artifact.

    File type detection:
    - *.md (plan doc)  → resume from Phase 3 (fixing), loads proposals from plan
    - *.json (checkpoint) → resume from checkpoint's phase_ordinal + 1
    - Stalled job ID (tfe-*) → shortcut to /api/jobs/{id}/resume

    Mirrors Presentation Generator's render_only auto-detection.
    """
    path = request.resume_from.strip()

    # Auto-detect: stalled job ID
    if path.startswith( "tfe-" ):
        return await resume_job_endpoint( path )

    # Auto-detect: checkpoint JSON
    if path.endswith( ".json" ):
        import json
        with open( _resolve_path( path ), "r" ) as f:
            checkpoint = json.load( f )
        # Construct job with checkpoint
        ...

    # Auto-detect: plan doc (Phase 2 output)
    if path.endswith( ".md" ):
        # Plan doc means Phase 2 completed — proposals exist, user needs to select fixes
        # Reconstruct from plan doc + original remediation snapshot
        ...
```

**In `notifications.js`**, add to the TFE / test-runner submission card:

```javascript
// Resume from file (Presentation Generator pattern)
const resumeFromGroup = document.createElement( "div" );
resumeFromGroup.className = "form-group mt-2";
resumeFromGroup.innerHTML = `
    <label class="form-label small text-muted">Resume from (plan doc or checkpoint path):</label>
    <input type="text" class="form-control form-control-sm"
           id="tfe-resume-from" placeholder="io/swe-team/plans/.../c1-plan.md (optional)">
`;
```

When `resume_from` is non-empty, the submit function calls `/api/test-fix-expediter/resume-from-file` instead of the normal submission path.

#### Step D4c: File-path resume on stalled job card

When a job card shows status=stalled, the "Resume" button should also display the **checkpoint artifacts** (plan doc path, snapshot path) so the user can see what's available:

```javascript
if ( job.status === "stalled" ) {
    // Show checkpoint artifacts
    const checkpoint = job.artifacts?.checkpoint;
    if ( checkpoint?.artifacts?.plan_path ) {
        const planLink = document.createElement( "a" );
        planLink.href = `/app/docs?path=${encodeURIComponent( checkpoint.artifacts.plan_path )}`;
        planLink.textContent = "View Plan";
        planLink.className = "btn btn-sm btn-outline-info me-1";
        planLink.target = "_blank";
        cardActions.appendChild( planLink );
    }
    // Resume button (existing from D4)
    ...
}
```

#### Step D4d: General pattern for agentic-voice-workflow skill

Document the "resume from file path" pattern alongside the "resume from stalled job" pattern in Phase 12 of the skill doc:

- **Resume from stalled job ID**: `POST /api/jobs/{id}/resume` — auto-loads checkpoint from DB
- **Resume from file path**: `POST /api/{agent}/resume-from-file` with `resume_from` field — auto-detects file type and infers resume phase
- **File type mapping** (agent-specific):
  - TFE: `.md` plan doc → Phase 3, `.json` checkpoint → checkpoint's ordinal
  - Presentation: `.yaml` intermediate → Phase 6 (render-only)
  - Podcast: `.md` script → audio generation phase
  - Deep Research: `.md` report draft → synthesis phase

This becomes the canonical "artifact-based resume" pattern for all agentic jobs.

#### Step D5: CLI `--resume` flag

In `src/tests/e2e/run-tfe-live-e2e.sh`, add:

```bash
if [ "$1" = "--resume" ]; then
    JOB_ID="$2"
    curl -s -X POST "http://localhost:7999/api/jobs/${JOB_ID}/resume" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" | python -m json.tool
    exit 0
fi
```

#### Step D6: Unit tests for resume flow

New file `src/tests/unit/test_tfe_resume.py`:

- `test_get_checkpoint_for_stalled_job` — mock DB row with stalled status + checkpoint, verify returned
- `test_get_checkpoint_for_non_stalled_returns_none` — completed job returns None
- `test_resume_job_factory_creates_job_with_checkpoint` — verify `_resume_checkpoint` attribute set
- `test_resume_job_factory_increments_resume_count` — verify count goes from 0 → 1
- `test_resume_endpoint_returns_404_for_missing_job` — HTTP 404 for invalid job ID
- `test_resume_endpoint_pushes_to_queue` — mock queue, verify push called
- `test_execute_loads_checkpoint_on_resume` — verify orchestrator.load_checkpoint called
- `test_execute_sets_resume_phase` — verify set_resume_phase called with correct ordinal

#### Step D7: Verify

```bash
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_tfe_resume.py -v
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/ -v --tb=short  # full regression
```

---

### Phase E: Cross-Agent Rollout + Skill Update

**Goal**: Apply completion report + checkpoint-resume to BFE and Podcast, then standardize in agentic-voice-workflow skill.

**Files to modify**:
- `src/cosa/agents/bug_fix_expediter/job.py` — add completion voice notification (CoSA)
- `src/cosa/agents/bug_fix_expediter/orchestrator.py` — add `save_checkpoint()`/`load_checkpoint()` (CoSA)
- `src/cosa/agents/bug_fix_expediter/state.py` — add `BFE_PHASE_ORDINALS`, `VoiceGateTimeoutError` reuse (CoSA)
- `src/cosa/agents/podcast_generator/job.py` — add completion voice notification (CoSA)
- `src/workflow/agentic-voice-workflow.md` — add Phase 11 (Completion Report) + Phase 12 (Checkpoint-Resume) (Lupin)
- `src/tests/unit/test_bfe_completion_report.py` — BFE completion notification test (Lupin)
- `src/tests/unit/test_bfe_checkpoint.py` — BFE checkpoint tests (Lupin)

#### Step E1: BFE completion report

Mirror TFE's Phase A pattern. BFE already has a text summary (lines 283-290 of BFE `job.py`) but no voice notification. Add `voice_io.notify()` call with:
- TTS: `"Bug Fix Expediter complete. Root cause: {root_cause[:80]}. {fix_summary}."`
- Abstract: dead job ID, root cause, fix result, resubmit status, plan path, duration

#### Step E2: BFE checkpoint-resume

BFE has voice gates at Phase 2 (fix selection) and Phase 5 (trust confirmation). Add:
- `BFE_PHASE_ORDINALS` mapping in `state.py`
- `save_checkpoint()`/`load_checkpoint()` on BFE orchestrator
- `StalledException` catch in BFE `_execute()`
- Reuse the same `VoiceGateTimeoutError` from a shared location (or each agent defines its own — simpler)

#### Step E3: Podcast Generator completion report

Podcast already has a completion notification pattern. Verify it matches the standard, add per-segment detail to abstract if missing.

#### Step E4: Update agentic-voice-workflow skill

Add two new phases to `src/workflow/agentic-voice-workflow.md` in Part II BUILD, after Phase 10:

**Phase 11: Completion Report**:
- Pattern: brief TTS message + rich markdown abstract
- Required data: duration, key metrics, artifact paths
- Three-variant TTS (success/partial/no-action)
- Abstract template with stats table + per-phase detail
- Reference: TFE `job.py` success path, Deep Research `job.py:338-356`

**Phase 12: Checkpoint-Resume**:
- When to add: any job with voice gates or long-running phases
- CheckpointData TypedDict template
- `save_checkpoint()`/`load_checkpoint()` contract
- Voice gate timeout → `VoiceGateTimeoutError` → `StalledException` flow
- Resume guard pattern for each phase method
- `_resume_checkpoint` attribute on job for factory integration
- STALLED → RUNNING transition on resume
- Reference: TFE orchestrator, `job_state.py` STALLED state

Update the **checklist** section:

```
Phase 11: Completion Report
[ ] voice_io.notify() on success path with TTS + markdown abstract
[ ] Three-variant TTS message (success/partial/no-action)
[ ] Per-phase detail in abstract (agent-specific metrics)
[ ] Duration tracking (self._start_time at _execute() entry)
[ ] Completion notification test

Phase 12: Checkpoint-Resume (if agent has voice gates)
[ ] Phase ordinal mapping in state.py
[ ] save_checkpoint() / load_checkpoint() on orchestrator
[ ] VoiceGateTimeoutError raised on voice gate timeout
[ ] StalledException caught in _execute()
[ ] Resume guard in each phase method
[ ] _resume_checkpoint integration in _execute() entry
[ ] Checkpoint round-trip unit tests
```

Update the **Reference Implementations** table:

```
| test_fix_expediter | src/cosa/agents/test_fix_expediter/ | Checkpoint-resume, multi-cluster, completion report |
```

Update **Version History**:

```
| 3.0 | 2026-04-12 | Phase 11 (Completion Report) + Phase 12 (Checkpoint-Resume) added. STALLED JobState. Cross-agent patterns from TFE forensics (Session 9056c113) |
```

#### Step E5: Verify cross-agent

```bash
# BFE
python -c "import py_compile; py_compile.compile( 'src/cosa/agents/bug_fix_expediter/job.py', doraise=True )"
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_bfe_*.py -v

# Full regression
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/ -v --tb=short
```

---

## Verification Plan (End-to-End)

| Phase | Verification | Command |
|-------|-------------|---------|
| A | py_compile + forensics tests | `pytest src/tests/unit/test_tfe_forensics.py -v` |
| B | State machine tests | `pytest src/tests/unit/test_job_state*.py -v` |
| C | Checkpoint round-trip + stall flow | `pytest src/tests/unit/test_tfe_checkpoint.py -v` |
| D | Resume factory + endpoint tests | `pytest src/tests/unit/test_tfe_resume.py -v` |
| E | BFE completion + checkpoint tests | `pytest src/tests/unit/test_bfe_*.py -v` |
| All | Full unit regression | `pytest src/tests/unit/ -v --tb=short` |
| Live | Next TFE run produces voice report | Schedule via `/schedule-tests` or watchdog trigger |

---

## CoSA Submodule Tracking

All phases modify files in `src/cosa/` (CoSA submodule). Per project rules:
- Edit files from Lupin context
- Do NOT run git in `src/cosa/`
- User commits CoSA in a separate session

**CoSA files touched**:
- `rest/job_state.py` (Phase B)
- `rest/job_persistence.py` (Phases C, D)
- `rest/routers/queues.py` (Phase D)
- `rest/routers/test_fix_expediter.py` (Phase D — new file, or extend `test_suite.py`)
- `rest/agentic_job_factory.py` (Phase D)
- `agents/agentic_job_base.py` (Phase C)
- `agents/test_fix_expediter/job.py` (Phases A, C)
- `agents/test_fix_expediter/state.py` (Phase C)
- `agents/test_fix_expediter/orchestrator.py` (Phase C)
- `agents/test_fix_expediter/cosa_interface.py` (Phase C)
- `agents/bug_fix_expediter/job.py` (Phase E)
- `agents/bug_fix_expediter/orchestrator.py` (Phase E)
- `agents/bug_fix_expediter/state.py` (Phase E)

**Lupin-parent files touched**:
- `src/tests/unit/test_tfe_forensics.py` (Phase A)
- `src/tests/unit/test_job_state.py` (Phase B — create)
- `src/tests/unit/test_tfe_checkpoint.py` (Phase C — create)
- `src/tests/unit/test_tfe_resume.py` (Phase D — create)
- `src/tests/unit/test_bfe_completion_report.py` (Phase E — create)
- `src/tests/unit/test_bfe_checkpoint.py` (Phase E — create)
- `src/fastapi_app/static/js/notifications.js` (Phase D)
- `src/fastapi_app/static/html/notifications.html` (Phase D)
- `src/tests/e2e/run-tfe-live-e2e.sh` (Phase D)
- `src/workflow/agentic-voice-workflow.md` (Phase E)
