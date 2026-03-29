# Presentation Generator Phase 8: Delivery & Chaining

**Date**: 2026-03-28
**Scope**: Orchestrator delivery, Deep Research → Presentation bridge, REST router, factory, expeditor, UI integration
**MVP**: Final phase — completes the end-to-end pipeline

---

## Context

Phases 1-7 produce a complete presentation: structured YAML (Phase 5), Marp Markdown (Phase 6), and visual elements (Phase 7). Phase 8 is the final phase with two concerns:

1. **Delivery** (Part A) — The orchestrator's `_deliver_async()` verifies all artifacts exist, builds a delivery summary, and stores it for the job to read. This is lightweight because `job.py` already handles artifact collection, cost summaries, clickable links, and completion notifications (lines 261-318).

2. **Chaining** (Parts B-D) — Build the Deep Research → Presentation bridge so users can say *"research quantum computing and make me a presentation"* and get both a research report and a slide deck. This follows the existing `deep_research_to_podcast` pattern exactly.

---

## What We're Building

### Part A: Orchestrator Delivery Phase

Replace the `_deliver_async()` stub with real logic: verify artifact files, build delivery summary dict, log final metrics.

### Part B: Deep Research → Presentation Bridge

Create `src/cosa/agents/deep_research_to_presentation/` with job, agent, state, and entry point. Follows the `deep_research_to_podcast` pattern exactly.

### Part C: Integration (Router, Factory, Expeditor, UI)

Wire the chained job into the REST API, factory, expeditor registry, and frontend.

### Part D: Unit Tests

Tests for state models, job construction, factory routing, and registry entry.

---

## Detailed Implementation

### Part A: Orchestrator `_deliver_async()`

**A.1 — Replace stub**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (replace lines 1128-1135)

Current stub:
```python
async def _deliver_async( self, presentation: Optional[ PresentationModel ] ) -> None:
    """Phase 8: Save final artifacts and send completion notification. TODO."""
    if self.debug: print( "[Orchestrator] Phase 8: Deliver (stub)" )
    await asyncio.sleep( 0.1 )
```

Replacement:

```python
async def _deliver_async( self, presentation: Optional[ PresentationModel ] ) -> None:
    """
    Phase 8: Verify and summarize all generated artifacts.

    The job (job.py) handles artifact collection, cost summary,
    clickable links, and completion notifications. This method
    verifies file existence and builds a delivery summary dict
    for the job to read.

    Requires:
        - presentation is a valid PresentationModel
        - _presentation_state has yaml_path and marp_path from Phases 5-6

    Ensures:
        - delivery_summary stored in _presentation_state
        - All artifact paths verified on disk
        - Total timing calculated from presenter notes
    """
    if presentation is None:
        logger.warning( "Phase 8: No presentation model — skipping delivery" )
        return

    if self.debug: print( "[Orchestrator] Phase 8: Deliver — building summary" )

    yaml_path = self._presentation_state.get( "yaml_path" )
    marp_path = self._presentation_state.get( "marp_path" )
    visuals_rendered = self._presentation_state.get( "visuals_rendered", 0 )

    # Verify files exist
    artifacts_verified = {}
    for name, path in [ ( "yaml", yaml_path ), ( "marp", marp_path ) ]:
        if path and os.path.exists( path ):
            file_size = os.path.getsize( path )
            artifacts_verified[ name ] = { "path": path, "size_bytes": file_size, "exists": True }
        else:
            artifacts_verified[ name ] = { "path": path, "size_bytes": 0, "exists": False }
            if path: logger.warning( f"Phase 8: Artifact missing: {name} = {path}" )

    # Calculate total estimated speaking time
    total_timing = sum(
        slide.presenter_notes.timing_seconds
        for slide in presentation.slides
        if slide.presenter_notes and slide.presenter_notes.timing_seconds
    )

    # Build delivery summary
    delivery_summary = {
        "total_slides"      : presentation.total_slides,
        "total_timing_secs" : total_timing,
        "total_timing_min"  : round( total_timing / 60, 1 ),
        "visuals_rendered"  : visuals_rendered,
        "artifacts"         : artifacts_verified,
        "theme"             : presentation.theme,
    }

    self._presentation_state[ "delivery_summary" ] = delivery_summary

    if self.debug:
        print( f"[Orchestrator] Delivery summary:" )
        print( f"  Slides: {presentation.total_slides}" )
        print( f"  Est. duration: {delivery_summary[ 'total_timing_min' ]}m" )
        print( f"  Visuals: {visuals_rendered}" )
        for name, info in artifacts_verified.items():
            status = "OK" if info[ "exists" ] else "MISSING"
            print( f"  {name}: {status} ({info[ 'size_bytes' ]:,} bytes)" )
```

**A.2 — Update `create_initial_state()` in `state.py`**

File: `src/cosa/agents/presentation_generator/state.py`

Add `"delivery_summary": None` and `"visuals_rendered": 0` to the initial state dict if not already present.

---

### Part B: Deep Research → Presentation Bridge

Follow the `deep_research_to_podcast` pattern exactly. Replace podcast-specific concepts with presentation-specific ones.

**B.1 — Create `state.py`**

File: `src/cosa/agents/deep_research_to_presentation/state.py` (new, ~120 lines)

```python
class PipelineState( Enum ):
    INITIALIZED              = "initialized"
    RUNNING_DEEP_RESEARCH    = "running_deep_research"
    DEEP_RESEARCH_DONE       = "deep_research_done"
    RUNNING_PRESENTATION_GEN = "running_presentation_gen"
    PRESENTATION_GEN_DONE    = "presentation_gen_done"
    COMPLETED                = "completed"
    FAILED                   = "failed"
    CANCELLED                = "cancelled"


@dataclass
class ChainedResult:
    # Primary outputs
    research_path      : Optional[ str ] = None
    research_abstract  : Optional[ str ] = None
    yaml_path          : Optional[ str ] = None
    marp_path          : Optional[ str ] = None

    # Cost tracking
    total_cost         : float = 0.0
    dr_cost            : float = 0.0
    pg_cost            : float = 0.0  # "pg" = presentation generator

    # Timing
    duration_seconds   : float = 0.0
    started_at         : Optional[ str ] = None
    completed_at       : Optional[ str ] = None

    # State
    state              : PipelineState = PipelineState.INITIALIZED
    error              : Optional[ str ] = None

    # Additional artifacts
    dr_artifacts       : Dict[ str, Any ] = field( default_factory=dict )
    pg_artifacts       : Dict[ str, Any ] = field( default_factory=dict )

    def is_success( self ) -> bool: ...
    def is_partial( self ) -> bool: ...
    def get_summary( self ) -> str: ...
```

Include `quick_smoke_test()` with same pattern as DR-to-podcast state.

**B.2 — Create `agent.py`**

File: `src/cosa/agents/deep_research_to_presentation/agent.py` (new, ~250 lines)

```python
class DeepResearchToPresentationAgent:
    """
    Orchestrates: Deep Research → Presentation Generation.

    1. Runs Deep Research to produce a research report
    2. Extracts report_path from DR output
    3. Passes report_path as source_path to Presentation Generator
    4. Returns combined ChainedResult
    """

    def __init__(
        self,
        query: str,
        user_email: str,
        # Deep Research options
        budget: Optional[ float ] = None,
        lead_model: Optional[ str ] = None,
        no_confirm: bool = False,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        # Presentation Generator options
        target_duration_minutes: Optional[ int ] = None,
        theme: Optional[ str ] = None,
        # Common options
        cli_mode: bool = False,
        debug: bool = False,
        verbose: bool = False,
    ): ...

    def _set_modality( self ) -> None:
        """Set voice/CLI mode on both DR and PG voice_io modules."""
        ...

    async def run_async( self ) -> ChainedResult:
        """Execute full chain: DR → PG."""
        # Step 1: Run Deep Research
        dr_result = await self._run_deep_research()
        # Extract report_path
        # Store DR artifacts in result

        # Checkpoint notification: DR complete, starting PG

        # Step 2: Run Presentation Generator
        # Pass report_path as source_path
        pg_result = await self._run_presentation_gen( report_path )
        # Extract yaml_path, marp_path
        # Aggregate costs

        return self._finalize_result()

    async def _run_deep_research( self ) -> dict: ...
    async def _run_presentation_gen( self, source_path: str ) -> dict: ...
    async def _notify( self, message, **kwargs ) -> None: ...
    def _finalize_result( self ) -> ChainedResult: ...
```

**Key differences from DR-to-podcast agent**:
- Podcast-specific: `target_languages`, `max_segments`, `audio_path`, `script_path`
- Presentation-specific: `target_duration_minutes`, `theme`, `yaml_path`, `marp_path`
- Step 2 creates a `PresentationGeneratorJob` instead of `PodcastGeneratorJob`
- The source_path for PG is the DR report_path

**B.3 — Create `job.py`**

File: `src/cosa/agents/deep_research_to_presentation/job.py` (new, ~200 lines)

```python
class DeepResearchToPresentationJob( AgenticJobBase ):
    JOB_TYPE   = "research_to_presentation"
    JOB_PREFIX = "rx"

    def __init__(
        self,
        query: str,
        user_id: str,
        user_email: str,
        session_id: str,
        budget: Optional[ float ] = None,
        target_duration_minutes: Optional[ int ] = None,
        theme: Optional[ str ] = None,
        dry_run: bool = False,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False,
    ) -> None: ...

    def do_all( self ) -> str: ...      # asyncio.run( self._execute() )
    async def _execute( self ) -> str:  # Create agent, run, collect artifacts
        ...
```

Result artifacts: `research_path`, `yaml_path`, `marp_path`, `cost_summary`.

**B.4 — Create `__init__.py` and `__main__.py`**

Standard module files. `__main__.py` includes argparse CLI entry point following the same pattern as `deep_research_to_podcast/__main__.py`.

---

### Part C: Integration

**C.1 — Create REST router**

File: `src/cosa/rest/routers/deep_research_to_presentation.py` (new, ~80 lines)

Follow `deep_research_to_podcast.py` pattern:

```python
router = APIRouter( prefix="/api/deep-research-to-presentation", tags=[ "Deep Research to Presentation" ] )

class ResearchToPresentationSubmitRequest( BaseModel ):
    query                    : str
    budget                   : Optional[ float ] = None
    target_duration_minutes  : Optional[ int ]   = None
    theme                    : Optional[ str ]   = None
    audience                 : Optional[ str ]   = None
    audience_context         : Optional[ str ]   = None
    dry_run                  : bool              = False
    scheduled_at             : Optional[ str ]   = None
    monopolize               : bool              = False

class ResearchToPresentationSubmitResponse( BaseModel ):
    job_id          : str
    queue_position  : int
    status          : str
    message         : str

@router.post( "/submit", response_model=ResearchToPresentationSubmitResponse )
async def submit_research_to_presentation( request, ... ):
    # Create job via factory → push to todo queue
    ...
```

**C.2 — Add factory branch**

File: `src/cosa/rest/agentic_job_factory.py` (modify)

Add `elif` branch after the presentation generator entry (~line 197):

```python
elif command == "agent router go to research to presentation":
    from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
    return DeepResearchToPresentationJob(
        query                   = args_dict.get( "query", "" ),
        user_id                 = user_id,
        user_email              = user_email,
        session_id              = session_id,
        budget                  = _parse_optional_float( args_dict.get( "budget" ) ),
        target_duration_minutes = _parse_optional_int( args_dict.get( "target_duration_minutes" ) ),
        theme                   = args_dict.get( "theme" ),
        dry_run                 = _parse_boolean( args_dict.get( "dry_run" ) ),
        audience                = args_dict.get( "audience" ),
        audience_context        = args_dict.get( "audience_context" ),
        debug                   = debug,
        verbose                 = verbose,
    )
```

**C.3 — Add expeditor registry entry**

File: `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` (modify)

Add new entry to `AGENTIC_AGENTS`:

```python
"agent router go to research to presentation" : {
    "job_prefix"         : "rx",
    "cli_module"         : "cosa.agents.deep_research_to_presentation",
    "job_class_path"     : "cosa.agents.deep_research_to_presentation.job.DeepResearchToPresentationJob",
    "display_name"       : "Deep Research to Presentation",
    "required_user_args" : [ "query" ],
    "system_provided"    : [ "user_id", "user_email", "session_id" ],
    "arg_mapping"        : {
        "query"                   : "query",
        "topic"                   : "query",
        "question"                : "query",
        "budget"                  : "budget",
        "target_duration_minutes" : "target_duration_minutes",
        "duration"                : "target_duration_minutes",
        "theme"                   : "theme",
        "audience"                : "audience",
        "audience_context"        : "audience_context",
    },
    "fallback_questions" : {
        "query"                   : "What topic should I research and present? Describe the topic or question.",
        "budget"                  : "Research budget in USD? Say a number, or 'default' for unlimited.",
        "target_duration_minutes" : "How long should the presentation be? Say minutes, or 'default' for 15.",
        "theme"                   : "Presentation theme? Say 'default' or a theme name.",
    },
    "fallback_defaults" : {
        "budget"                  : "default",
        "target_duration_minutes" : "default",
        "theme"                   : "default",
        "audience"                : "general",
        "audience_context"        : "none",
    },
    "special_handlers" : {},  # No source file — query-driven, not file-driven
},
```

Update smoke test assertion: `assert len( AGENTIC_AGENTS ) == 7` (was 6).

**C.4 — Register router in main.py**

File: `src/fastapi_app/main.py` (modify)

Add to import line and router registration:

```python
# Import (line 66 — add deep_research_to_presentation to the import list)
from cosa.rest.routers import ..., deep_research_to_presentation, ...

# Registration (after presentation_generator.router)
app.include_router( deep_research_to_presentation.router )
```

**C.5 — Add UI mode metadata (optional)**

File: `src/fastapi_app/static/js/notifications.js` (modify)

Add `"research_to_presentation"` to `MODE_METADATA` and `AGENTIC_MODE_MAP` alongside the existing `"research_to_podcast"` entry. Add HTML submission card and JS handler following the pattern from Session 374.

**Design note**: The UI integration (C.5) is optional for MVP. The chained job works via voice commands and direct API calls without UI. Can be deferred to a follow-up session.

---

### Part D: Unit Tests

**D.1 — State model tests**

File: `src/tests/unit/test_deep_research_to_presentation.py` (new, ~200 lines)

```
class TestPipelineState:
    test_state_enum_values                    # All states have expected values
    test_state_initial_value                  # INITIALIZED is default

class TestChainedResult:
    test_default_construction                 # All fields have expected defaults
    test_success_detection                    # is_success() for COMPLETED state
    test_partial_detection                    # is_partial() for DR done, PG failed
    test_failed_detection                     # Neither success nor partial
    test_summary_success                      # get_summary() for complete pipeline
    test_summary_partial                      # get_summary() mentions partial
    test_summary_failed                       # get_summary() mentions error

class TestJobConstruction:
    test_job_type_and_prefix                  # JOB_TYPE == "research_to_presentation", PREFIX == "rx"
    test_job_id_format                        # ID starts with "rx-"
    test_job_construction_defaults            # Default values correct
    test_last_question_asked_format           # Display string format

class TestFactoryRouting:
    test_factory_creates_job                  # Factory returns DeepResearchToPresentationJob
    test_factory_passes_args                  # All args forwarded correctly

class TestRegistryEntry:
    test_registry_entry_exists                # Entry in AGENTIC_AGENTS
    test_registry_required_keys               # Has required_user_args, arg_mapping, etc.
    test_registry_agent_count                 # Total agent count is 7
```

---

## Implementation Order

| Step | Part | What | Dependencies |
|------|------|------|-------------|
| 0 | — | Serialize plan + update `00-index.md` | None |
| 1 | A.1 | `_deliver_async()` in orchestrator | None |
| 2 | A.2 | Update `create_initial_state()` if needed | None |
| 3 | B.1 | `state.py` (PipelineState + ChainedResult) | None |
| 4 | B.2 | `agent.py` (DeepResearchToPresentationAgent) | B.1 |
| 5 | B.3 | `job.py` (DeepResearchToPresentationJob) | B.2 |
| 6 | B.4 | `__init__.py` + `__main__.py` | B.3 |
| 7 | C.1 | REST router | B.3 |
| 8 | C.2 | Factory branch | B.3 |
| 9 | C.3 | Expeditor registry entry | B.3 |
| 10 | C.4 | main.py registration | C.1 |
| 11 | D.1 | Unit tests | All |
| 12 | — | Full unit suite — verify no regressions | All |

Steps 3-6 can be done as a batch (bridge module). Steps 7-10 can be done as a batch (integration).

---

## Files Summary

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `src/cosa/agents/deep_research_to_presentation/__init__.py` | ~5 |
| **Create** | `src/cosa/agents/deep_research_to_presentation/state.py` | ~120 |
| **Create** | `src/cosa/agents/deep_research_to_presentation/agent.py` | ~250 |
| **Create** | `src/cosa/agents/deep_research_to_presentation/job.py` | ~200 |
| **Create** | `src/cosa/agents/deep_research_to_presentation/__main__.py` | ~80 |
| **Create** | `src/cosa/rest/routers/deep_research_to_presentation.py` | ~80 |
| **Create** | `src/tests/unit/test_deep_research_to_presentation.py` | ~200 |
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | +40 (delivery) |
| **Modify** | `src/cosa/agents/presentation_generator/state.py` | +2 (initial state) |
| **Modify** | `src/cosa/rest/agentic_job_factory.py` | +20 |
| **Modify** | `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` | +30 |
| **Modify** | `src/fastapi_app/main.py` | +2 (import + register) |

**Reuse existing**:
- `deep_research_to_podcast/` — pattern template for all Part B files
- `PresentationGeneratorJob` — composed inside the chained agent
- `voice_io` / `cosa_interface` — modality switching pattern from DR-to-podcast
- `agentic_job_factory._parse_optional_int()` / `_parse_boolean()` — arg parsing helpers

---

## Edge Cases & Error Handling

| Edge Case | Handling |
|-----------|---------|
| DR fails | ChainedResult.state = FAILED, PG never runs |
| DR succeeds but no report_path | ChainedResult.state = FAILED with descriptive error |
| DR cancelled by user | ChainedResult.state = CANCELLED |
| PG fails after DR succeeds | ChainedResult.state = FAILED, is_partial() = True, DR artifacts preserved |
| PG cancelled by user | ChainedResult.state = CANCELLED, DR artifacts preserved |
| Missing artifacts at delivery | Logged as warning, job still completes with available paths |
| Delivery summary has 0 timing | Possible if all slides have timing_seconds=0; show "0.0m" |
| Dry run of chained job | Both DR and PG run in dry-run mode |

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| `_deliver_async()` is lightweight | Yes | `job.py` already handles 90% of delivery (lines 261-318) |
| Bridge follows DR-to-podcast exactly | Yes | Proven pattern, minimal design risk |
| `JOB_PREFIX = "rx"` | "rx" for research-to-presentation | Follows: "rp" (research-to-podcast), "pr" (presentation), "dr" (deep-research) |
| UI integration is optional for MVP | Yes | Voice commands and direct API work without UI |
| Expeditor entry has no `special_handlers` | Correct | Query-driven (not file-driven like presentation generator) |
| `_deliver_async()` doesn't send notifications | Correct | `do_all_async()` sends completion notification at line 275 after delivery |

---

## Verification

### Part A (Delivery)
1. `py_compile` on modified orchestrator
2. Dry-run: delivery_summary populated in state
3. Live run: all artifact files verified on disk

### Part B (Bridge)
4. `py_compile` on all new files
5. Import chain: `from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob`
6. Smoke test: `python -m cosa.agents.deep_research_to_presentation.state` passes
7. Smoke test: `python -m cosa.agents.deep_research_to_presentation` passes (with `--user-visible-args`)

### Part C (Integration)
8. Factory: `create_agentic_job( "agent router go to research to presentation", ... )` returns correct job type
9. Expeditor: `python -m cosa.agents.runtime_argument_expeditor.agent_registry` passes (7 agents)
10. Router: Server starts without import errors (router registered)

### Part D (Tests)
11. `pytest src/tests/unit/test_deep_research_to_presentation.py -v` — all pass
12. `pytest src/tests/unit/ -v` — full suite, no regressions

### End-to-End
13. Submit chained job via voice: "research quantum computing and make a presentation"
14. Verify: DR report generated → PG uses report as source → YAML + Marp produced
15. Cost summary aggregates both DR and PG costs
