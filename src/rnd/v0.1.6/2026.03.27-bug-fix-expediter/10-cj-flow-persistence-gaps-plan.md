# CJ Flow Persistence Gaps — Fix + Phase 6 Cleanup

**Created**: 2026-04-10
**Status**: READY FOR IMPLEMENTATION
**Prefix**: [LUPIN]
**Prior plan**: `09-phase6-dry-run-smoke-test-plan.md` (complete)
**Follow-up for**: Persistence gaps surfaced during Phase 6 dry-run smoke test verification

---

## Context

While verifying the Phase 6 automated repair loop end-to-end, we discovered that three fields
are not being persisted to `job_history` when agentic jobs are submitted via the native REST
endpoints (`/api/deep-research/submit`, etc.) or via the voice/expediter path:

| Field | Symptom | Root cause |
|-------|---------|------------|
| `job_history.session_id` | `NULL` in the DB even when the job was instantiated with a valid `session_id` | `todo_fifo_queue.py:push()` builds a metadata dict but does not extract `item.session_id` |
| `job_history.routing_command` | `NULL` for every agentic job | `agentic_job_factory.create_agentic_job()` never assigns `job.routing_command`; the metadata dict in `push()` never extracts it |
| `job_history.metadata_json.original_args` | Never written anywhere in the codebase | No code ever populates this field. BFE was designed to read it, but no writer exists. `_build_metadata_json()` doesn't even include it in its rich-fields whitelist. |

**Why it matters for production Phase 6**: when BFE "fixes" a real failed job and resubmits it,
it currently reconstructs the resubmitted job from a crude fallback (`{"query": question_text}`),
**losing user-supplied parameters** like `budget`, `audience`, `source_path`, `target_languages`,
`content_model`, etc. The automated repair loop claims to retry "your job" but actually runs
"a job with the same query and default everything else." That's a faithfulness regression that
would silently burn budget or produce wrong output.

**Secondary finding**: `persist_job_completed_from_metadata()` and
`persist_job_failed_from_metadata()` **overwrite** `metadata_json` on state transitions
(`job_persistence.py:240, 288`). Even if we populate `original_args` at creation, it would be
stomped when the job transitions to `completed` or `failed`. The fix has to include metadata
merging on update, not just extraction on insert.

**Goal**: Fix all three gaps at the source, delete the band-aid workarounds in the BFE reader
path that I added during smoke-test debug, and prove the round-trip with a new test that
submits a job with custom args, fails it, and asserts the resubmitted job carries the same args.

---

## Current-State Findings (confirmed by exploration)

### Persistence writer path (REST and voice both hit this)
- `src/cosa/rest/todo_fifo_queue.py:1159` — `TodoFifoQueue.push()` entry point
- `src/cosa/rest/todo_fifo_queue.py:1184-1192` — metadata dict built for `emit_job_state_transition()`. Missing fields: `session_id`, `routing_command`, `original_args`.
- `src/cosa/rest/queue_util.py:92` — `emit_job_state_transition()` calls `persist_job_created_from_metadata()`
- `src/cosa/rest/job_persistence.py:146-180` — `persist_job_created_from_metadata()` reads `session_id`, `routing_command`, builds `metadata_json` via whitelist
- `src/cosa/rest/job_persistence.py:113-139` — `_build_metadata_json()` whitelist. `original_args` is **NOT** in the list.
- `src/cosa/rest/job_persistence.py:240, 288` — `persist_job_completed_from_metadata()` and `persist_job_failed_from_metadata()` **overwrite** `metadata_json` with fresh build (stomps `original_args`).

### Job factory
- `src/cosa/rest/agentic_job_factory.py:78-283` — big if/elif tree, each branch returns a constructed job. `routing_command` and `original_args` are never assigned.

### AgenticJobBase
- `src/cosa/agents/agentic_job_base.py:58-115` — base `__init__`. No `routing_command` or `original_args` attributes exist.

### BFE reader side (band-aids I added during verification)
- `src/cosa/agents/bug_fix_expediter/dead_job_packager.py` — `_JOB_TYPE_TO_ROUTING_COMMAND` lookup table at the top, `or ""` coercions for `session_id`/`user_email`/`question_text` in the `DeadJobContext` construction.
- `src/cosa/agents/bug_fix_expediter/job.py:_execute_dry_run()` — defensive args-building that synthesizes `{"dry_run": True, "query": stripped_question}` when `original_args` is missing.

### Existing tests to preserve
- `src/tests/unit/test_bfe_phase6.py` — 70 tests currently passing. My new code changes must not break them.
- `src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py` — must continue to pass in both modes (WATCHDOG_DISABLED and DR_LOOP_HAPPY).

---

## Recommended Approach

**Option A** for `original_args`: add attributes to `AgenticJobBase`, have the factory set them
post-construction. No subclass `__init__` signatures need to change. Minimal blast radius.

### Change 1 — Add `original_args` to all three CJ Flow base classes

**Invariant**: every job that flows through CJ Flow already has `routing_command` as a first-class
attribute (`AgentBase.__init__` at `agent_base.py:75,113`; `SolutionSnapshot.__init__` at
`solution_snapshot.py:177,235`). Only `AgenticJobBase` is missing it. `original_args` is missing
on all three. After this fix, every CJ Flow-eligible job has both attributes — no defensive
reads anywhere downstream.

**File 1**: `src/cosa/agents/agentic_job_base.py` — `AgenticJobBase.__init__` body

```python
# CJ Flow persistence fields — populated by agentic_job_factory.create_agentic_job()
self.routing_command : Optional[ str ]  = None
self.original_args   : Optional[ dict ] = None
```

**File 2**: `src/cosa/agents/agent_base.py` — `AgentBase.__init__` body (after existing
`self.routing_command = routing_command` at line 113)

```python
# CJ Flow persistence field — agent-class jobs don't carry structured args, default to None
self.original_args : Optional[ dict ] = None
```

**File 3**: `src/cosa/memory/solution_snapshot.py` — `SolutionSnapshot.__init__` body (after
existing `self.routing_command = routing_command` at line 235)

```python
# CJ Flow persistence field — cached snapshots replay prior runs, no args needed
self.original_args : Optional[ dict ] = None
```

No signature changes anywhere. Subclasses inherit automatically. Every QueueableJob instance
now has both `routing_command` and `original_args` attributes — guaranteed, not hoped for.

### Change 2 — `agentic_job_factory.create_agentic_job()`: direct assignment

**File**: `src/cosa/rest/agentic_job_factory.py:78-307`

No wrapper, no helper function. Change each branch's `return FooJob(...)` to `job = FooJob(...)`
and drop the `return` inside the branch. At the end of the function (after the final `else`),
set both attributes and return once:

```python
def create_agentic_job( command, args_dict, user_id, user_email, session_id, debug=False, verbose=False ):
    ...
    if command == "agent router go to deep research":
        job = DeepResearchJob( ... )
    elif command == "agent router go to podcast generator":
        job = PodcastGeneratorJob( ... )
    elif command == "agent router go to research to podcast":
        job = DeepResearchToPodcastJob( ... )
    elif command == "agent router go to claude code":
        job = ClaudeCodeJob( ... )
    elif command == "agent router go to presentation generator":
        job = PresentationGeneratorJob( ... )
    elif command == "agent router go to research to presentation":
        job = DeepResearchToPresentationJob( ... )
    elif command == "agent router go to swe team":
        job = SweTeamJob( ... )
    elif command == "agent router go to test suite":
        job = TestSuiteJob( ... )
    elif command == "agent router go to bug fix expediter":
        job = BugFixExpediterJob( ... )
    elif command == "agent router go to test fix expediter":
        job = TestFixExpediterJob( ... )
    else:
        print( f"[agentic_job_factory] Unknown command: {command}" )
        return None

    job.routing_command = command
    job.original_args   = dict( args_dict )
    return job
```

Note: accounts for the new `TestFixExpediterJob` branch that was added to the factory.

### Change 3 — `TodoFifoQueue.push()`: direct attribute reads

**File**: `src/cosa/rest/todo_fifo_queue.py:1184-1192`

Read the attributes directly — no `getattr` fallbacks. Every QueueableJob is guaranteed to have
`session_id`, `routing_command`, and `original_args` after Change 1.

```python
metadata = {
    'question_text'    : item.last_question_asked,
    'agent_type'       : item.job_type,
    'timestamp'        : item.created_date,
    'scheduled_at'     : item.scheduled_at,
    'monopolize'       : item.monopolize,
    'paused'           : item.state == JobState.PAUSED,
    'user_email'       : item.user_email,
    'session_id'       : item.session_id,        # NEW
    'routing_command'  : item.routing_command,   # NEW
    'original_args'    : item.original_args,     # NEW
}
```

Any future QueueableJob subclass that forgets these attributes fails loudly at the first push
— which is exactly what we want.

### Change 4 — `_build_metadata_json()`: whitelist `original_args`

**File**: `src/cosa/rest/job_persistence.py:127-132`

Add `"original_args"` to the `rich_fields` list:

```python
rich_fields = [
    "response_text", "abstract", "report_link",
    "cost_summary", "artifacts", "answer_conversational",
    "push_counter", "agent_type", "stack_trace",
    "scheduled_at", "monopolize",
    "original_args",  # NEW — preserves submitted args for BFE resubmit
]
```

### Change 5 — preserve `original_args` through state transitions

**File**: `src/cosa/rest/job_persistence.py:216-304`

`persist_job_completed_from_metadata()` and `persist_job_failed_from_metadata()` currently
overwrite `metadata_json` with a fresh build. They must **merge** new fields into the existing
row's `metadata_json` so `original_args` (set at creation) survives.

Approach: read the existing `metadata_json` via the same session, merge the new rich fields on
top (new fields win on conflict), write back. One extra `SELECT` per update, acceptable cost.

```python
# Inside persist_job_completed_from_metadata and persist_job_failed_from_metadata,
# replace the single `metadata_json = _build_metadata_json(metadata)` line with:

with get_db() as session:
    existing_row = session.execute(
        select( JobHistory.metadata_json, JobHistory.started_at )
        .where( JobHistory.id_hash == job_id )
    ).one_or_none()
    existing_metadata = ( existing_row.metadata_json if existing_row else {} ) or {}
    new_metadata      = _build_metadata_json( metadata )
    merged            = { **existing_metadata, **new_metadata }
    values[ "metadata_json" ] = merged
    if existing_row is not None and existing_row.started_at is not None:
        values[ "duration_seconds" ] = ( now - existing_row.started_at ).total_seconds()
    session.execute( update( JobHistory ).where( JobHistory.id_hash == job_id ).values( **values ) )
```

The existing two-statement SELECT+UPDATE pattern already does a similar two-step; this
consolidates them slightly and adds the merge.

### Change 6 — clean up `dead_job_packager.py`

**File**: `src/cosa/agents/bug_fix_expediter/dead_job_packager.py`

Now that the fields are reliably populated, remove:
- The entire `_JOB_TYPE_TO_ROUTING_COMMAND` lookup table
- The `or ""` coercions on `session_id`, `user_email`, `question_text`
- The derived-routing-command logic

Revert to the pre-workaround form:

```python
context = DeadJobContext(
    id_hash          = row[ "id_hash" ],
    job_type         = row[ "job_type" ],
    user_id          = row[ "user_id" ],
    user_email       = row[ "user_email" ],
    session_id       = row[ "session_id" ],
    status           = status,
    question_text    = row[ "question_text" ],
    error            = row.get( "error" ),
    stack_trace      = stack_trace,
    routing_command  = row[ "routing_command" ],
    duration_seconds = row.get( "duration_seconds" ),
    metadata_json    = metadata,
    created_at       = row.get( "created_at" ),
    started_at       = row.get( "started_at" ),
    completed_at     = row.get( "completed_at" ),
)
```

Fail-fast on missing fields (per user memory `feedback_no_defensive_programming.md`).

### Change 7 — simplify `bug_fix_expediter/job.py:_execute_dry_run()` resubmit args

**File**: `src/cosa/agents/bug_fix_expediter/job.py` (inside `_execute_dry_run`)

Now that `original_args` is always populated, simplify the resubmit-args logic:

```python
# Simulate "fix applied" by stripping force_failure_mode from original_args and
# ensuring dry_run=True so the resubmitted job stays in dry-run mode.
metadata      = self.dead_job_context.metadata_json or {}
original_args = dict( metadata.get( "original_args" ) or {} )
original_args.pop( "force_failure_mode", None )
original_args[ "dry_run" ] = True
metadata[ "original_args" ] = original_args
self.dead_job_context.metadata_json = metadata
if self.debug: print( f"[BugFixExpediterJob] Dry-run fix: resubmit args = {original_args}" )
```

No more question_text prefix stripping, no more manual fallback-query synthesis. `original_args`
now contains the real original arguments verbatim.

### Change 8 — new unit tests for the round-trip

**File**: `src/tests/unit/test_bfe_phase6.py`

Add a new test class `TestPersistenceRoundTrip` with these assertions:

1. **AgenticJobBase attributes exist**: fresh job has `routing_command=None` and `original_args=None`
2. **Factory sets attributes**: after `create_agentic_job(command="agent router go to deep research", args_dict={"query": "...", "budget": 1.0, "audience": "expert"}, ...)`, the returned job has `job.routing_command == "agent router go to deep research"` and `job.original_args == {"query": "...", "budget": 1.0, "audience": "expert"}`
3. **Factory copies args_dict defensively**: mutating `args_dict` after factory call does NOT mutate `job.original_args`
4. **`_build_metadata_json()` preserves original_args**: calling it with `{"original_args": {...}}` includes that field in the output
5. **Missing original_args**: calling `_build_metadata_json()` with no `original_args` key does NOT include it (null-safe)

No DB test — keep it fast and in-process.

### Change 9 — extend smoke test to validate args preservation

**File**: `src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py`

Add a second scenario in `DR_LOOP_HAPPY`: after the resubmitted DR completes, fetch its
`job_history` row via a direct DB read (the test already imports `get_job_by_id_hash`) and
assert:

- `routing_command == "agent router go to deep research"` (not None)
- `session_id == "phase6-smoke-dr"` (not None, equals the websocket_id we submitted with)
- `metadata_json["original_args"]["query"]` starts with "phase6 smoke test"
- `metadata_json["original_args"]["budget"]` equals what we submitted
- `metadata_json["original_args"]["audience"]` equals what we submitted (if we added it)
- `metadata_json["original_args"]` does NOT contain `force_failure_mode` (stripped by BFE)
- `metadata_json["original_args"]["dry_run"] is True` (set by BFE for dry-run resubmit)

Also update the original DR submission in `run_dr_loop_happy_scenario()` to include
`audience="expert"` so the assertion has something to check against.

This turns the smoke test into a real regression guard — if anyone breaks persistence in the
future, this test fails.

---

## Implementation Sequence

| Step | Task | Scope | Verification |
|------|------|-------|--------------|
| 1a | Add `original_args=None` + `routing_command=None` to `AgenticJobBase.__init__` | 2 lines | unit test assertion (1) |
| 1b | Add `original_args=None` to `AgentBase.__init__` | 1 line | existing AgentBase tests still pass |
| 1c | Add `original_args=None` to `SolutionSnapshot.__init__` | 1 line | existing SolutionSnapshot tests still pass |
| 2 | Direct assignment in `agentic_job_factory.create_agentic_job()` (no wrapper) | ~12 lines: change each `return FooJob(...)` to `job = FooJob(...)` + single `return job` at end | unit test assertions (2-3) |
| 3 | Direct attribute reads in `TodoFifoQueue.push()` metadata dict (no `getattr`) | 3 lines | exercised by smoke test end-to-end |
| 4 | Add `"original_args"` to `_build_metadata_json()` whitelist | 1 line | unit test assertions (4-5) |
| 5 | Merge logic in `persist_job_completed_from_metadata()` and `persist_job_failed_from_metadata()` | ~20 lines across 2 functions | smoke test round-trip |
| 6 | Clean up `dead_job_packager.py` — remove lookup table + coercions | ~30 lines deleted | existing unit tests still pass |
| 7 | Simplify `bug_fix_expediter/job.py:_execute_dry_run()` resubmit-args block | ~10 lines simpler | smoke test still passes |
| 8 | Add `TestPersistenceRoundTrip` class to `test_bfe_phase6.py` | ~60 lines | `pytest src/tests/unit/test_bfe_phase6.py` |
| 9 | Extend smoke test DR_LOOP_HAPPY with DB assertions + `audience="expert"` | ~30 lines | `python src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py` |
| 10 | Full regression: 70+ unit tests + smoke test in both modes | N/A | tabular summary |

**Order matters**: Steps 1a-1c must all land before Step 3 (otherwise push() will fail with AttributeError on non-agentic jobs). Steps 1-5 must land before Step 6 (can't remove workarounds until source is fixed).

**Order matters**: Steps 1-5 must land before Step 6 (can't remove workarounds until source is fixed). Steps 8-9 can be written in parallel with 6-7 but must all land before Step 10.

**Smoke test re-run plan**:
- First, flip `auto fix enabled = false`, reset queues, run smoke → expect `WATCHDOG_DISABLED PASS`
- Then, flip `auto fix enabled = true`, touch `main.py` to force uvicorn reload, reset queues, run smoke → expect `DR_LOOP_HAPPY PASS` including the new DB assertions
- Then, flip `auto fix enabled = false` again to restore the committed state

---

## Critical Files

### Modified (production)
- `src/cosa/agents/agentic_job_base.py` — add `routing_command` + `original_args` attributes (Step 1a)
- `src/cosa/agents/agent_base.py` — add `original_args` attribute (Step 1b)
- `src/cosa/memory/solution_snapshot.py` — add `original_args` attribute (Step 1c)
- `src/cosa/rest/agentic_job_factory.py` — direct assignment refactor, no wrapper (Step 2)
- `src/cosa/rest/todo_fifo_queue.py` — metadata dict enrichment, direct reads (Step 3)
- `src/cosa/rest/job_persistence.py` — whitelist + merge logic (Steps 4-5)
- `src/cosa/agents/bug_fix_expediter/dead_job_packager.py` — cleanup (Step 6)
- `src/cosa/agents/bug_fix_expediter/job.py` — cleanup of `_execute_dry_run()` (Step 7)

### Modified (tests)
- `src/tests/unit/test_bfe_phase6.py` — `TestPersistenceRoundTrip` class (Step 8)
- `src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py` — DB assertions (Step 9)

### Unchanged
- `src/cosa/rest/dead_queue_watchdog.py` — already propagates `dry_run` correctly
- `src/cosa/rest/routers/*.py` — already plumb `dry_run` and `force_failure_mode` into args_dict
- `src/cosa/agents/bug_fix_expediter/state.py` — `DeadJobContext` schema unchanged
- All other agentic job classes (DR, podcast, presentation, etc.) — no changes, they inherit new attributes from base

---

## Verification Plan

### Per-step
1. **Steps 1-4** (writer): run `pytest src/tests/unit/test_bfe_phase6.py::TestPersistenceRoundTrip` — all 5 new assertions pass
2. **Step 5** (merge): run the full smoke test — round-trip should preserve `original_args` through the failed state transition
3. **Step 6** (cleanup): run the full existing test suite — no regressions from removing the workaround (proof that the workaround is no longer needed)
4. **Step 7** (BFE dry-run): run smoke test DR_LOOP_HAPPY — resubmitted job still reaches done queue with `dry_run=True`

### End-to-end regression
```bash
# 1. Unit tests
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_bfe_phase6.py src/tests/unit/test_repair_integration.py -q

# 2. Smoke test — disabled mode
sed -i 's/auto fix enabled.*= true/auto fix enabled                                               = false/' src/conf/lupin-app.ini
touch src/fastapi_app/main.py && sleep 6
PYTHONPATH=src:$PYTHONPATH python src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py

# 3. Smoke test — happy mode (+ new DB assertions)
sed -i 's/auto fix enabled.*= false/auto fix enabled                                               = true/' src/conf/lupin-app.ini
touch src/fastapi_app/main.py && sleep 6
PYTHONPATH=src:$PYTHONPATH python3 -c "import os, requests; h={'Authorization':'Bearer '+requests.post('http://localhost:7999/auth/login', json={'email':os.environ['LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL'], 'password':os.environ['LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD']}).json()['tokens']['access_token']}; requests.post('http://localhost:7999/api/reset-queues', headers=h)"
PYTHONPATH=src:$PYTHONPATH python src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py

# 4. Restore config
sed -i 's/auto fix enabled.*= true/auto fix enabled                                               = false/' src/conf/lupin-app.ini
```

Expected:
- Unit tests: 75+ passed (70 existing + 5+ new in `TestPersistenceRoundTrip`)
- Disabled smoke: `WATCHDOG_DISABLED PASS`
- Happy smoke: `DR_LOOP_HAPPY PASS` including the new DB round-trip assertions

### Manual DB inspection (one-time, during development)
After a successful happy-path run, query the resubmitted DR job's row directly:
```python
from cosa.rest.job_persistence import get_job_by_id_hash
row = get_job_by_id_hash("<resubmit_job_id>")
assert row["session_id"] is not None
assert row["routing_command"] == "agent router go to deep research"
assert row["metadata_json"]["original_args"]["query"].startswith("phase6 smoke test")
```

---

## What This Plan Does NOT Cover

- **Other persistence gaps**: This plan fixes only the three fields that block Phase 6. Other fields on `JobHistory` (e.g., `duration_seconds`, `monopolize`) are out of scope.
- **Backward compatibility with legacy rows**: Existing `job_history` rows inserted before this fix will still have `NULL` in these columns. BFE's cleaned-up packager will raise a Pydantic validation error if asked to process them. This is intentional (fail fast), acceptable because in-memory queues are always fresh after server restart.
- **The AgentBase / SolutionSnapshot path**: Both already have `routing_command` as a first-class attribute (confirmed). This plan adds `original_args` to both as a `None` default so `TodoFifoQueue.push()` can read it directly. AgentBase jobs don't resubmit via BFE (not in the eligibility allow-list), but the attribute is present for consistency so CJ Flow's queue push path has zero special-cases.
- **Writer-side validation**: Nothing enforces that `original_args` is a JSON-serializable dict. If someone passes a non-serializable object, SQLAlchemy will fail at INSERT time. Relying on existing patterns rather than adding explicit validation.

---

## Open Questions

None — the approach is fully specified and all code paths are identified. Ready for implementation.

## Post-implementation follow-up (memory update)

After exiting plan mode, extend `~/.claude/projects/-mnt-DATA01.../memory/feedback_no_defensive_programming.md` to explicitly cover `getattr(obj, 'attr', default)` fallback patterns. The existing memory talks about `or ""` coercions but not getattr defaults — the underlying principle is the same ("fail loudly, not silently") but the pattern differs enough that future-me might miss it. Add a concrete example from this session: the `getattr( item, 'routing_command', None )` line that was prohibited here.
