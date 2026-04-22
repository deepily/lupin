# TFE File-Path Resume + Smart Voice Path Parsing

**Date**: 2026-04-12
**Session**: 9056c113 (continued)
**Status**: Plan approved — pending implementation
**Predecessor**: [`14-checkpoint-resume-and-completion-report.md`](14-checkpoke-resume-and-completion-report.md) (Phase D4b-D4d deferred work)

---

## Context

Phase D4b-D4d deferred work from Session 9056c113. Users want to resume stalled TFE jobs by specifying a file path — either typed into the notifications UI or spoken via voice. For voice, descriptions like *"the TFE plan from April 12"* or *"the most recent stalled checkpoint"* must be normalized to an actual file path or job ID. Mirrors the Presentation Generator's proven `render_only` + `yaml_path` auto-detection pattern.

**Good news from exploration**: Most infrastructure already exists. The Runtime Argument Expeditor has a `_handle_fuzzy_file_match()` that scans dirs and uses LLM for fuzzy matching. The `POST /api/jobs/{id}/resume-from-checkpoint` endpoint already works. We just need to (a) add a TFE-specific fuzzy handler, (b) expose it via a new endpoint that accepts free-form input, (c) wire it into the expeditor for voice, and (d) add a UI card.

---

## Architecture

Four input types flow through **one endpoint** with auto-detection:

```
User input (typed or voice) → smart dispatcher
                                  │
    ┌─────────────────────────────┼─────────────────────────────┐
    │                             │                             │
  tfe-*                        *.md                         natural
(job ID)                  (plan doc)                       language
    │                             │                             │
    └──────────────┬──────────────┴───────────┬─────────────────┘
                   │                          │
                   ▼                          ▼
    resume_job(id_hash)              fuzzy match via LLM
                   │                          │
                   └────────────┬─────────────┘
                                ▼
                    orchestrator.resume_from_phase()
                    push to todo queue
```

Also: `*.json` → checkpoint file (future-proof, low-priority)

---

## Phase 1: Backend — Endpoint + Dispatcher

### Files to modify (CoSA submodule)

- `src/cosa/rest/routers/test_suite.py` OR new `src/cosa/rest/routers/test_fix_expediter.py`
- `src/cosa/rest/agentic_job_factory.py` — add `resume_job_from_plan_doc()`
- `src/cosa/agents/test_fix_expediter/` — new `resume_resolver.py` module

### Step 1.1: New resolver module — `test_fix_expediter/resume_resolver.py`

Pure-Python dispatcher that takes any input string and returns `(resolved_job_id, resume_path_type, diagnostic)`:

```python
def resolve_resume_target( resume_from: str, user_email: str ) -> ResumeTarget:
    """
    Dispatch a resume_from string to the right resolver.

    Requires:
        - resume_from is a non-empty string (job ID, file path, or description)
        - user_email is the requesting user's email

    Ensures:
        - Returns ResumeTarget with (job_id, source_type, confidence, diagnostic)
        - Returns None if no match found
        - Never raises — reports errors in diagnostic field
    """
    s = resume_from.strip()

    # Type 1: TFE job ID — fastest path, no file I/O
    if s.startswith( "tfe-" ) and "::" in s:
        return _resolve_by_job_id( s )

    # Type 2: Plan doc path ending in -plan.md
    if s.endswith( "-plan.md" ) or "/plans/" in s:
        return _resolve_by_plan_path( s, user_email )

    # Type 3: Checkpoint JSON file
    if s.endswith( ".json" ) and "checkpoint" in s.lower():
        return _resolve_by_checkpoint_file( s, user_email )

    # Type 4: Natural language — fuzzy match
    return _resolve_by_fuzzy_match( s, user_email )
```

**`ResumeTarget` Pydantic model**:
```python
class ResumeTarget( BaseModel ):
    job_id        : Optional[str] = None     # Resolved stalled job ID
    source_type   : str                       # "job_id" | "plan_path" | "checkpoint" | "fuzzy"
    matched_path  : Optional[str] = None     # File path if resolved from a file
    confidence    : float         = 1.0      # 1.0 for exact, <1.0 for fuzzy
    candidates    : list[dict]    = []       # Multiple matches for user disambiguation
    diagnostic    : str           = ""       # Human-readable explanation
```

### Step 1.2: Plan-doc → job-ID extractor

TFE plan filenames embed the source TestSuiteJob ID:
```
2026.04.12-1-clusters-from-ts86c172f70cf47e2dd5a14cd4addf79810fd32b15-c1-plan.md
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                          source_test_suite_job_id (no dashes)
```

Parse the filename to extract the source TSJ ID, then query `job_history` for:
1. Any stalled TFE job whose `source_test_suite_job_id` matches (exact join via metadata)
2. Most recent TFE job for that source (fallback)

Cross-reference: TFE job's `metadata_json["artifacts"]["plan_path"]` should equal this plan path — confirms the match.

### Step 1.3: Fuzzy matcher — reuse expeditor infrastructure

New handler `_handle_tfe_checkpoint_match()` in `expeditor.py`, modeled on `_handle_fuzzy_file_match()`:

**Search sources**:
1. **Plan docs**: `io/swe-team/plans/{user_email}/*-plan.md`
2. **Stalled jobs in job_history**: `SELECT * FROM job_history WHERE status='stalled' AND user_email=?`
3. **Recent TFE jobs**: Last 20 TFE jobs ordered by `completed_at` DESC

**Index built for LLM**:
```python
candidates = [
    {
        "job_id"    : "tfe-7c25082a::user1",
        "status"    : "stalled",
        "stalled_at": "2026-04-12T03:14:00",
        "plan_path" : "io/swe-team/plans/.../c1-plan.md",
        "summary"   : "1 cluster, 12 visual regression failures, env mismatch",
        "source_ts" : "ts-86c172f7::user1",
    },
    ...
]
```

**LLM prompt** (Opus or Sonnet, ~$0.001/call):
```
The user said: "{resume_from}"

Available stalled/recent TFE jobs:
{candidates JSON}

Match the user's description to at most 3 candidates. Return JSON:
{
  "matches": [
    {"job_id": "...", "confidence": 0.0-1.0, "reason": "why this matches"}
  ]
}
```

Returns ranked candidates. If confidence > 0.9 on top match → auto-select. Otherwise → user disambiguation.

### Step 1.4: REST endpoint — `POST /api/test-fix-expediter/resume-from`

```python
class TFEResumeFromRequest( BaseModel ):
    resume_from : str                        # Any of: job ID, plan path, checkpoint path, description
    auto_select : bool = True                # If True, auto-pick top match if confidence >= threshold

@router.post( "/api/test-fix-expediter/resume-from" )
async def resume_tfe_from( request: TFEResumeFromRequest, current_user = Depends( get_current_user ) ):
    """
    Smart resume: auto-detect input type and dispatch.

    Supports:
    - Job ID (tfe-*::*): Direct lookup → resume
    - Plan doc path (*-plan.md): Extract job ID from filename → resume
    - Checkpoint JSON: Load checkpoint → reconstruct job
    - Natural language: LLM fuzzy match against stalled + recent jobs

    Response:
    - 200 with resumed_job_id if auto-resolved
    - 200 with candidates list if multiple matches (user must disambiguate)
    - 404 if no match
    """
    target = resolve_resume_target( request.resume_from, current_user["email"] )

    if target.source_type == "not_found":
        raise HTTPException( 404, detail=target.diagnostic )

    # Multi-match case — return candidates for UI disambiguation
    if target.job_id is None and target.candidates:
        return {
            "status"     : "ambiguous",
            "candidates" : target.candidates,
            "diagnostic" : target.diagnostic,
        }

    # Single match — delegate to existing resume endpoint logic
    from cosa.rest.agentic_job_factory import resume_job
    job = resume_job( target.job_id, config_mgr=None )
    if job is None:
        raise HTTPException( 404, detail=f"Job {target.job_id} cannot be resumed" )

    todo_queue = get_todo_queue()
    todo_queue.push( job )

    return {
        "status"           : "resumed",
        "source_type"      : target.source_type,
        "matched_path"     : target.matched_path,
        "confidence"       : target.confidence,
        "resumed_job_id"   : job.id_hash,
        "original_job_id"  : target.job_id,
        "resume_from_phase": job._resume_checkpoint[ "phase_ordinal" ],
        "phase_name"       : job._resume_checkpoint[ "phase_name" ],
    }
```

---

## Phase 2: Voice Integration (Expeditor + Agent Registry)

### Files to modify (CoSA submodule)

- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` — new agent entry
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` — new handler

### Step 2.1: New agent registry entry

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
    "arg_extraction_hints" : {
        "resume_from" : [
            "the TFE plan from {date}",
            "the stalled TFE job",
            "the most recent stalled one",
            "job {job_id}",
            "the plan for {source_test_suite_job_id}",
        ],
    },
}
```

### Step 2.2: New expeditor handler

```python
def _handle_tfe_checkpoint_match( self, user_email: str, user_description: str = None ) -> Optional[str]:
    """
    Fuzzy match user's description of a stalled TFE job or plan doc.

    Leverages the same LLM-based fuzzy matching as _handle_fuzzy_file_match()
    but with a different candidate index (stalled jobs + recent TFE jobs +
    plan docs on disk).

    Returns:
        str: The resolved identifier (job ID or plan path) the REST endpoint
             will further dispatch. Returns None if user cancels or no match.
    """
    from cosa.agents.test_fix_expediter.resume_resolver import (
        list_resume_candidates,
        fuzzy_match_candidates,
    )

    # 1. Build candidate index
    candidates = list_resume_candidates( user_email )
    if not candidates:
        return self._ask_for_arg( "resume_from",
            "No stalled TFE jobs or recent plans found. Provide a job ID or plan path.",
            user_email )

    # 2. If user_description not provided, ask via TTS
    if not user_description:
        user_description = self._ask_for_arg( "resume_from",
            "Which TFE job would you like to resume?",
            user_email )
        if not user_description:
            return None

    # 3. LLM fuzzy match
    matches = fuzzy_match_candidates( user_description, candidates )

    # 4. Auto-accept if top match confidence >= 0.9
    if matches and matches[ 0 ][ "confidence" ] >= 0.9:
        return matches[ 0 ][ "job_id" ]

    # 5. Multi-match disambiguation via ask_multiple_choice (voice+UI)
    return self._disambiguate_matches( matches, user_email )
```

### Step 2.3: PEFT training data (voice routing)

Add ~30 template examples to `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter-resume.txt`:

```
Resume the TFE plan from April 12
Resume the stalled test fix expediter
Pick up where TFE left off
Resume the job that's waiting for my input
Continue the TFE plan we made yesterday
Resume job tfe-7c25082a
Continue the visual regression fix
Resume the most recent stalled TFE
```

Register in `src/conf/training/agent-router-agentic-commands.json` + add to `AGENTIC_TEMPLATES` whitelist in `test_swe_team_training_data.py`.

**USER-RUN only**: PEFT trainer itself is not run by this plan (GPU rule). Training data generated; user runs trainer.

---

## Phase 3: UI — Resume Card

### Files to modify (Lupin parent)

- `src/fastapi_app/static/html/notifications.html` — new submission card
- `src/fastapi_app/static/js/notifications.js` — submit handler

### Step 3.1: New "TFE Resume" card in notifications dashboard

Placed near the TFE / test runner section:

```html
<div class="submission-card" id="tfe-resume-card">
    <h3>🔄 Resume Stalled TFE Job</h3>
    <p class="text-muted small">
        Describe or paste: job ID (<code>tfe-*</code>), plan path, or natural language
        (e.g., "the plan from April 12", "most recent stalled")
    </p>
    <textarea id="tfe-resume-input"
              rows="2"
              placeholder="tfe-7c25082a::user1  OR  io/swe-team/plans/.../c1-plan.md  OR  'the stalled one from today'">
    </textarea>
    <button id="tfe-resume-submit" class="btn btn-warning">
        ▶ Resume
    </button>
    <div id="tfe-resume-status" class="small mt-1"></div>
</div>
```

### Step 3.2: Submit handler

```javascript
async submitTFEResume() {
    const input = document.getElementById( "tfe-resume-input" ).value.trim();
    if ( !input ) return;

    const statusEl = document.getElementById( "tfe-resume-status" );
    statusEl.textContent = "Resolving...";

    try {
        const resp = await this.authedFetch( "/api/test-fix-expediter/resume-from", {
            method  : "POST",
            headers : { "Content-Type": "application/json" },
            body    : JSON.stringify( { resume_from: input } )
        } );
        const data = await resp.json();

        if ( data.status === "ambiguous" ) {
            // Show candidates for user to pick (modal or inline list)
            this.showResumeCandidates( data.candidates );
            return;
        }

        if ( data.status === "resumed" ) {
            this.showToast(
                `Resumed ${data.source_type}: ${data.resumed_job_id} from ${data.phase_name}`,
                "success"
            );
            statusEl.textContent = `✓ Resumed from ${data.phase_name}`;
        }
    } catch ( err ) {
        statusEl.textContent = `✗ ${err.message}`;
    }
}
```

### Step 3.3: Disambiguation modal

When multiple candidates match, show list with details for user to pick:

```
┌──────────────────────────────────────────────────────┐
│ Multiple stalled TFE jobs match your description     │
├──────────────────────────────────────────────────────┤
│ ○ tfe-7c25082a  | Stalled 2026-04-12 03:14           │
│   1 cluster, 12 visual regression failures           │
│   Plan: .../c1-plan.md                               │
│                                                      │
│ ○ tfe-3b8c92d1  | Stalled 2026-04-11 22:47           │
│   2 clusters, auth failures                          │
│   Plan: .../2-clusters-c1-plan.md                    │
│                                                      │
│        [ Cancel ]    [ Resume Selected ]             │
└──────────────────────────────────────────────────────┘
```

---

## Phase 4: Tests

### Files to create (Lupin parent)

- `src/tests/unit/test_tfe_resume_resolver.py` — resolver dispatch logic
- `src/tests/unit/test_tfe_resume_endpoint.py` — endpoint behavior

### Unit tests

**Resume resolver**:
- `test_job_id_exact_match` — `tfe-abc::user1` → direct lookup, no file I/O
- `test_plan_path_extracts_source_ts_id` — parse filename, query job_history
- `test_plan_path_missing_file_returns_not_found`
- `test_fuzzy_match_with_high_confidence_auto_selects` — mock LLM, verify auto-select
- `test_fuzzy_match_with_low_confidence_returns_candidates`
- `test_fuzzy_match_no_candidates_found`

**Endpoint**:
- `test_resume_by_job_id_returns_resumed_status` — mock `resume_job`, verify flow
- `test_resume_by_plan_path_extracts_and_resumes`
- `test_resume_ambiguous_returns_candidates_not_resumed`
- `test_resume_unauthorized_user_cannot_see_others_jobs` — RLS check

**Expeditor handler**:
- `test_tfe_checkpoint_match_with_stalled_jobs`
- `test_tfe_checkpoint_match_prompts_when_no_description`
- `test_tfe_checkpoint_match_disambiguates_on_low_confidence`

---

## Phase 5: Skill Update

### File to modify (Lupin parent)

- `src/workflow/agentic-voice-workflow.md` — extend Phase 12 with artifact-based resume pattern

### Step 5.1: Expand Phase 12 "Artifact-Based Resume" section

Replace the current 5-line mapping table with a full sub-section:

```markdown
### Artifact-Based Resume (Phase 12b)

Jobs can be resumed from **file paths** or **natural-language descriptions**, not just
stalled job IDs. The pattern mirrors Presentation Generator's `render_only` + `yaml_path`
auto-detection.

**Components**:

1. **Resume resolver module** (`{agent}/resume_resolver.py`):
   - `resolve_resume_target(resume_from: str, user_email: str) → ResumeTarget`
   - Dispatches by input type: job ID → plan path → checkpoint → fuzzy match

2. **Smart endpoint** (`POST /api/{agent}/resume-from`):
   - Accepts `resume_from: str` (free-form)
   - Returns `{status: "resumed"|"ambiguous"|"not_found", ...}`

3. **Expeditor handler** (extends Runtime Argument Expeditor):
   - New `special_handlers: {"resume_from": "{agent}_checkpoint_match"}`
   - LLM fuzzy matcher against candidate index (stalled jobs + recent jobs + plan docs)

4. **UI card** with free-form textarea input + disambiguation modal

5. **Voice training data**:
   - 30+ templates covering date/status/content/ID phrasings
   - Examples: "the plan from April 12", "the most recent stalled one"

**When to add**: Any agent with long-running phases that produces durable artifacts
(plan docs, outlines, scripts, YAML intermediates). Without this, users must remember
exact job IDs to resume anything.
```

---

## Implementation Phases (Sequencing)

| Phase | Scope | Dependencies |
|-------|-------|--------------|
| 1 | Resolver module + endpoint + job-ID + plan-path dispatch | None — builds on existing `resume_job()` |
| 2 | Fuzzy matcher + expeditor handler + agent registry | Phase 1 (resolver) |
| 3 | UI submission card + disambiguation modal | Phase 1 (endpoint) |
| 4 | Unit tests for all layers | Phases 1-3 |
| 5 | Skill update (Phase 12b section) | All above |
| — | PEFT training data (generated, not trained) | Phase 2 |

## Verification

```bash
# Syntax
python -c "import py_compile; py_compile.compile('src/cosa/agents/test_fix_expediter/resume_resolver.py', doraise=True)"

# Unit tests
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_tfe_resume_resolver.py src/tests/unit/test_tfe_resume_endpoint.py -v

# Full TFE regression
PYTHONPATH=src:$PYTHONPATH pytest src/tests/unit/test_tfe_*.py -v

# Live (after CoSA commits + server restart):
# 1. Type job ID into UI card → resume works
# 2. Type plan path into UI card → resume works
# 3. Type "the stalled one from today" → fuzzy match resumes correct job
# 4. Voice: "resume the TFE plan from April 12" → expeditor routes, auto-resumes
```

---

## CoSA Submodule Rule

Most edits land in `src/cosa/`:
- `rest/routers/{test_suite|test_fix_expediter}.py` — new endpoint
- `rest/agentic_job_factory.py` — potential additions
- `agents/test_fix_expediter/resume_resolver.py` — new module
- `agents/runtime_argument_expeditor/expeditor.py` — new handler
- `agents/runtime_argument_expeditor/agent_registry.py` — new agent entry

Lupin parent edits:
- `static/html/notifications.html`, `static/js/notifications.js` — UI card
- `tests/unit/test_tfe_resume_*.py` — new tests
- `ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter-resume.txt` — voice training data
- `workflow/agentic-voice-workflow.md` — Phase 12b expansion

Per standing rule: CoSA edits are working-tree only from Lupin context; user commits CoSA separately.
