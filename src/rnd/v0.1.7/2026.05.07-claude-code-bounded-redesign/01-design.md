# 2026.05.07 — Bounded ClaudeCodeJob Canonical Redesign

**Status**: ✅ Plan approved 2026-05-07 (session 6825e6af). Serialized from `~/.claude/plans/so-it-looks-like-silly-map.md`. Awaiting PIP plan review (REUSE → Pass 1 → Pass 2 sequential) before implementation.
**Predecessor**: `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/` (the rogue `/api/claude-code/dispatch` cluster retirement; this redesign brings the surviving cj-flow path to canonical shape).
**Origin plan file**: `~/.claude/plans/so-it-looks-like-silly-map.md` (approved by user via ExitPlanMode 2026-05-07).
**Companion file**: `90-execution-log.md` (phase-by-phase progress, appended at each phase boundary).

---

## Context

### Why this change is being made

The `/api/claude-code/dispatch` rogue endpoint cluster was retired on 2026-05-05 (commit `73bee1b`, session `1a8900ee`). The cj-flow successor `claude_code_queue.py` + `ClaudeCodeJob` works for BOUNDED submission but is structurally incomplete vs the canonical agentic-job pattern.

Audit findings:
- `src/cosa/agents/claude_code/` has only **4 of 8** canonical files — missing `config.py`, `state.py`, `orchestrator.py`, `__main__.py`
- Output is truncated to 500 chars in artifacts (no full transcript file like DeepResearch's `report_path`)
- `cosa_interface.py` lacks the `set_dispatch_context()` ContextVar isolation that prevents sender-ID leaks under concurrent agentic-pool execution
- INTERACTIVE controls (inject / interrupt / end_session) entirely absent from the cj-flow path
- The dispatcher implementation lives at `src/cosa/orchestration/claude_code/dispatcher.py` — outside the canonical `src/cosa/agents/{name}/` containment hierarchy

### What this redesign solves

Bring `ClaudeCodeJob` to first-class CJ Flow agentic-job status — drop-in compatible with the same lifecycle / notification / artifacts contract used by Deep Research, Podcast Generator, Presentation Generator, etc.

### Two foundational questions answered during exploration

**Why was Claude Code created?** Delegate code-related tasks (bug investigation, codebase analysis, test fixes) from Lupin browser UI / voice / mobile *without leaving current context*. Three consumer surfaces planned (browser, voice, mobile); per the original 2026-01-08 cold-call-path-1 plan.

**BOUNDED vs INTERACTIVE distinction (semantic)**:
- **BOUNDED**: `claude -p` print-mode subprocess that runs to completion. User cannot push input unprompted, but Claude can call cosa-voice MCP tools (`converse`, `ask_yes_no`) to ask clarifications. Use cases: CI/CD, scheduled jobs, delegated subtasks.
- **INTERACTIVE**: Agent SDK persistent session with `inject` / `interrupt` / `end_session` user controls. Use cases: pair-programming, exploratory debugging, voice-driven development.

**Today's redesign is BOUNDED.** INTERACTIVE method names are reserved as `NotImplementedError` stubs (extensibility hooks) per the locked decision below.

### Locked design decisions

**Status**: FROZEN 2026-05-07
**Source**: User selections via `AskUserQuestion` during plan mode, 2026-05-07.

#### Q1 — INTERACTIVE forward-compat scope

- **Question**: How much should the BOUNDED redesign anticipate the future INTERACTIVE restoration?
- **✅ Decision**: BOUNDED with extensibility hooks — reserve method names (`inject` / `interrupt` / `end_session`) and state-machine slots (`WAITING_INJECT` / `INTERRUPTED` / `SESSION_ENDED`) for INTERACTIVE; methods raise `NotImplementedError` today.
- **Rationale**: Pure-BOUNDED today is cleanest scope but risks refactor when INTERACTIVE returns. Designing both today is largest scope and uneconomic given INTERACTIVE has no immediate consumer. Reserving names is a small abstraction tax now (~10 lines of stub methods + 3 state-machine entries) that eliminates a future rename cycle.
- **Implication**: Phase 1 `state.py` ships 3 reserved enum values. Phase 2 `orchestrator.py` ships 3 `NotImplementedError` stub methods. Phase 4 `job.py` ships 3 corresponding `NotImplementedError` job-level stubs. Tests assert these raise (AC9). Future INTERACTIVE work fills the bodies; no signature changes needed.

#### Q2 — Output persistence strategy

- **Question**: How should the BOUNDED job persist Claude's output?
- **✅ Decision**: Full transcript to file (`io/claude-code/YYYY.MM.DD-at-HH:MM-EST-<slug>.md`); `self.artifacts["transcript_path"]` carries the path; completion notification links via `abstract`.
- **Rationale**: Matches DeepResearch's `report_path` canonical pattern. Summary-only notifications break the canonical "job-card → artifact link" UX. Hybrid (tail-summary inline + full file) duplicates state of truth. The DR-mirror approach is single-source-of-truth and well-understood.
- **Implication**: Phase 1 `config.py` ships `transcript_dir = "/io/claude-code"` + `transcript_filename_format` (presentation-filename convention per `feedback_presentation_filename_convention`). Phase 2 `orchestrator.py` ships `write_transcript()` using `Gister`-driven slug. Phase 4 `job.py` removes the `output_text[:500]` truncation entirely — `self.output_text` carries full transcript, and `self.artifacts["transcript_path"]` is non-null after BOUNDED runs (AC7, AC8).

#### Q3 — Voice clarifications mid-task

- **Question**: How should mid-task voice clarifications (BOUNDED's killer feature) flow?
- **✅ Decision**: Direct cosa-voice MCP from the spawned subprocess — clarifications surface in parent user's notification UI as they would for any Claude Code session.
- **Rationale**: Simplest path. cosa-voice MCP is already user-scope-installed (the spawned subprocess inherits the registration via `~/.claude.json`). Routing through the runtime_argument_expeditor (RAE) hard-gate would constrain BOUNDED's flexibility — RAE is for *documented* required args only; mid-task ad-hoc clarifications need MCP's flexibility. Hybrid is unnecessary complexity.
- **Implication**: Phase 1 `config.py` does NOT add an RAE-hard-gate flag. Phase 2 `orchestrator.run_bounded()` does NOT wrap MCP calls. Phase 4 `job.py` keeps RAE for `expeditor_required_args=("prompt",)` only — everything else is optional with defaults, MCP handles the rest at runtime.

### Gold reference

`src/cosa/agents/deep_research/` (DeepResearchJob). Mirror its 8-file layout + `set_dispatch_context()` ContextVar pattern + `Gister`-driven slug + `set_job_id`/`clear_job_id` voice_io binding.

---

## Architecture target — 8 canonical files + relocate the orphan tree

The dispatcher's current home `src/cosa/orchestration/claude_code/` is itself the architectural anomaly — it's a Claude-Code-only module sitting outside the canonical `src/cosa/agents/{name}/` containment. README.md and `__init__.py` confirm: not a shared orchestration layer, just a misplaced legacy from before the agentic-job pattern existed. **Relocate, don't wrap.**

| File | Status | Purpose |
|------|--------|---------|
| `__init__.py` | ✅ Keep | Exports |
| `job.py` | ⚠️ Rewire | Consume `ClaudeCodeConfig` + `ClaudeCodeOrchestrator` + `ClaudeCodeState`; full output; transcript artifact; INTERACTIVE stubs |
| `cosa_interface.py` | ⚠️ Refactor | Add `set_dispatch_context()` ContextVar isolation (port from DeepResearch lines 91-130) |
| `voice_io.py` | ⚠️ Refactor | Agent-bound wrapper (mirror DR lines 1-56), not bare re-export |
| `config.py` | 🆕 NEW | `ClaudeCodeConfig` dataclass with `.from_config(config_mgr)` |
| `state.py` | 🆕 NEW | `ClaudeCodeState` enum + relocated `Task`/`TaskType`/`TaskResult`/`SessionInfo` dataclasses from `orchestration/claude_code/dispatcher.py` |
| `orchestrator.py` | 🆕 NEW | **Relocated from `src/cosa/orchestration/claude_code/dispatcher.py`** with rename (`ClaudeCodeDispatcher` → `ClaudeCodeOrchestrator`, `dispatch()` → `run_bounded()`). BOUNDED logic preserved verbatim; INTERACTIVE branch kept as commented archaeology + new method stubs raise `NotImplementedError`. |
| `message_history.py` | 🆕 NEW | **Relocated from `src/cosa/orchestration/claude_code/message_history.py`** as-is |
| `__main__.py` | 🆕 NEW | CLI: `python -m cosa.agents.claude_code --prompt "..." --dry-run` |

Total: **9** in-agent files (the original 8 canonical + `message_history.py` as agent-internal helper).

**Delete after relocation**: `src/cosa/orchestration/` (entire directory + README.md + `__init__.py` + `claude_code/` subdir). Once empty, the parent `orchestration/` directory goes too — there is no "shared orchestration layer" to preserve.

---

## Sibling-agent dependency surface (verified)

User flagged a concern that TFE / BFE / swe_team may consume the Claude Code surface as a sub-task primitive. Direct grep verification (2026-05-07):

| Sibling | Code imports of CC surface | Test imports | Action |
|---------|---------------------------|--------------|--------|
| `src/cosa/agents/test_fix_expediter/` (TFE) | **ZERO** | **ZERO** | None |
| `src/cosa/agents/bug_fix_expediter/` (BFE) | **ZERO** | **ZERO** | None |
| `src/cosa/agents/swe_team/` | **ZERO code**; 1 docstring at `hooks.py:14` ("Pattern source: ClaudeCodeDispatcher (dispatcher.py) on_message() callbacks") | **ZERO** | Update docstring to new class name + path |
| `src/cosa/agents/shared/` (FixExecutor, PlanWriter, GitStrategist) | **ZERO** | **ZERO** | None |

**TFE-to-CC bridge** (`src/cosa/agents/tfe_to_cc/`): per its `__init__.py` docstring, this is a **prompt-builder package only**, not a runtime CC consumer. Quote: *"Selection between engines is runtime via INI flags (future work): `test fix expediter phase 1 engine = sdk | claude_code`"*. Contains `prompts/{bundle_phase1,bundle_phase3,output_contract}.py`. Tests import only the prompt builders. **Today it does not depend on the Claude Code surface; it pre-stages prompts for a runtime integration that hasn't shipped.** When the INI flag eventually flips on, the new `ClaudeCodeOrchestrator.run_bounded()` becomes the natural target — design with this forward-compat in mind (clean public API, no hidden invariants).

**Manual experimental scripts** (`src/scripts/tfe_to_cc_phase{1,3}_*.py`): standalone `subprocess` shellouts to `claude -p`. They do not import `ClaudeCodeDispatcher`. Out of scope.

**Real cross-cutting test surface** (must be updated by this plan):

| Test file | Imports | Risk |
|-----------|---------|------|
| `src/tests/integration/test_dispatcher_e2e.py` (723 LOC) | `from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType, TaskResult` + `ClaudeCodeDispatcher()` + `.dispatch(...)` | **HIGH** — must update import path, class name, method name |
| `src/tests/integration/test_dispatcher_bidirectional.py` (381 LOC) | Same + `from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE` + `.inject() / .interrupt() / .get_active_sessions()` | **HIGH** — INTERACTIVE methods now `NotImplementedError`; skip-mark + import update OR keep as restoration breadcrumbs |
| `src/tests/integration/test_sdk_validation.py` (377 LOC) | `from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE` | **MEDIUM** — `SDK_AVAILABLE` flag must be re-exported from new location |
| `src/tests/manual/test_option_b_interactive.py` | Same direct imports | INTERACTIVE — skip-mark + import update |
| `src/tests/manual/test_option_b_inject_info.py` | Same | Same |
| `src/tests/manual/test_option_b_inject_interrupt.py` | Same | Same |
| `src/tests/manual/test_option_b_bidirectional.py` | Same | Same |

**Conclusion**: relocation is safe for the agent layer (zero hard deps). The work is concentrated in 3 integration tests + 4 manual tests + 1 docstring. The forward-compat consideration for `tfe_to_cc/` is documented, not blocking.

---

## Phases

### Phase 0 — Documentation (DOCUMENTATION-FIRST PROTOCOL)

R&D directory: this directory (`src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/`).

`01-design.md` — this file.
`90-execution-log.md` — paired tracker, populated as work progresses.

### Phase 1 — `config.py` + `state.py`

`config.py` mirrors `src/cosa/agents/deep_research/config.py:12-100`:

```python
@dataclass
class ClaudeCodeConfig:
    max_turns                  : int               = 50            # claude code bounded job max turns
    timeout_seconds            : int               = 3600          # claude code bounded job timeout seconds
    project_default            : str               = "lupin"
    transcript_dir             : str               = "/io/claude-code"  # claude code bounded job transcript dir
    transcript_filename_format : str               = "{date}-at-{time}-EST-{slug}.md"
    narrate_progress           : bool              = True          # claude code bounded job narrate progress
    expeditor_required_args    : tuple[ str, ... ] = ( "prompt", )

    @classmethod
    def from_config( cls, config_mgr, debug=False ) -> "ClaudeCodeConfig": ...
```

INI keys: `claude code bounded job max turns`, `claude code bounded job timeout seconds`, `claude code bounded job transcript dir`, `claude code bounded job narrate progress`. **Prefix rationale**: anticipates the future INTERACTIVE/unbounded restoration getting its own `claude code interactive job *` namespace — separate prefixes prevent the two variants colliding on shared config (the variants will need different `max turns` defaults; INTERACTIVE will likely run longer).

**Migration approach — atomic rename in Phase 1** (no backward-compat shim):

1. Edit `src/conf/lupin-app.ini`: rename existing keys at lines 388-389 in-place — `claude code job max turns default` → `claude code bounded job max turns`, `claude code job timeout seconds default` → `claude code bounded job timeout seconds`. Preserve values. Drop the `default` suffix (defaults belong in the `ClaudeCodeConfig` dataclass, not in key names).
2. Add 2 new keys: `claude code bounded job transcript dir` (default `/io/claude-code`), `claude code bounded job narrate progress` (default `True`).
3. Edit `src/conf/lupin-app-splainer.ini`: rename matching entries; add new entries.
4. `ClaudeCodeConfig.from_config()` uses standard `config_mgr.get("claude code bounded job <field>", default=…, return_type=…)` pattern — same shape as DeepResearch / Podcast / BFE. **No shim, no fallback logic, no deprecation warnings.**

The atomic rename matches the convention used by every other agentic-job config in the codebase. The INI file ships with the source; `git pull` updates code + INI together, so there is no migration-window state to defend against. **MANDATE**: paired entries in `src/conf/lupin-app-splainer.ini`.

`state.py`:

```python
class ClaudeCodeState( Enum ):
    PRE_FLIGHT      = "pre_flight"
    DISPATCHING     = "dispatching"
    EXECUTING       = "executing"
    PERSISTING      = "persisting"
    # Reserved for INTERACTIVE
    WAITING_INJECT  = "waiting_inject"
    INTERRUPTED     = "interrupted"
    SESSION_ENDED   = "session_ended"
    # Terminal
    COMPLETED       = "completed"
    FAILED          = "failed"
```

Coexists with `cosa.rest.job_state.JobState` (cross-cutting queue state); `ClaudeCodeState` is agent-internal sub-state, written to `self.artifacts["cc_state"]`.

### Phase 2 — Relocate `orchestration/claude_code/` → `agents/claude_code/`

**Relocation, not wrapping.** Move the entire `src/cosa/orchestration/claude_code/` tree into the agent's containment, rename the public class to use canonical "orchestrator" terminology, and delete the now-empty parent.

#### Sub-phase 2a — Move + rename

| Source | Destination | Transformation |
|--------|-------------|----------------|
| `src/cosa/orchestration/claude_code/dispatcher.py` | `src/cosa/agents/claude_code/orchestrator.py` | Class `ClaudeCodeDispatcher` → `ClaudeCodeOrchestrator`; method `dispatch( Task )` → `run_bounded( prompt, project, job_id, ... )` (BOUNDED branch only); INTERACTIVE branch preserved as commented archaeology + new method stubs `inject` / `interrupt` / `end_session` raise `NotImplementedError` |
| `src/cosa/orchestration/claude_code/message_history.py` | `src/cosa/agents/claude_code/message_history.py` | Verbatim move (just update internal imports) |
| `src/cosa/orchestration/claude_code/__init__.py` | (delete) | Re-exports become unnecessary — agent's own `__init__.py` handles its surface |
| `Task` / `TaskType` / `TaskResult` / `SessionInfo` dataclasses (currently inside `dispatcher.py`) | `src/cosa/agents/claude_code/state.py` (alongside `ClaudeCodeState`) | Group all agent-internal types together |

The `ClaudeCodeOrchestrator` final shape — **all args on `__init__`, parameterless run methods** (matches Podcast / DR / SWE / TFE convention; the current `dispatch(Task)` is the outlier and gets dropped):

```python
class ClaudeCodeOrchestrator:
    def __init__(
        self,
        config           : ClaudeCodeConfig,
        prompt           : str,
        project          : str,
        job_id           : str,
        max_turns        : Optional[ int ]      = None,   # falls back to config.max_turns
        timeout_seconds  : Optional[ int ]      = None,   # falls back to config.timeout_seconds
        working_dir      : Optional[ str ]      = None,   # falls back to <project_root>/<project>
        on_message       : Optional[ Callable ] = None,
        debug            : bool                  = False,
    ):
        # Validate working_dir resolves; raise ValueError if not
        ...

    # BOUNDED — runs to completion via `claude -p` subprocess
    async def run_bounded( self ) -> "ClaudeCodeRunResult": ...

    # INTERACTIVE — Agent SDK persistent session; deferred today
    async def run_interactive( self ) -> "ClaudeCodeRunResult":
        raise NotImplementedError( "INTERACTIVE deferred — see TODO.md restoration milestone" )
    async def inject( self, message: str ):
        raise NotImplementedError( "INTERACTIVE deferred — see TODO.md restoration milestone" )
    async def interrupt( self ):
        raise NotImplementedError( "INTERACTIVE deferred — see TODO.md restoration milestone" )
    async def end_session( self ):
        raise NotImplementedError( "INTERACTIVE deferred — see TODO.md restoration milestone" )

    def write_transcript( self, output_text: str, semantic_topic: str ) -> str:
        """Writes io/claude-code/<filename>.md and returns abs path."""
```

**Job-level routing** (mirrors Podcast's `do_all_async / do_review_only_async / do_audio_only_async` mode-method pattern): `ClaudeCodeJob._execute()` instantiates ONE orchestrator and calls the right run-method based on `self.task_type`:

```python
async def _execute( self ):
    orchestrator = ClaudeCodeOrchestrator(
        config = self.config,
        prompt = self.prompt,
        project = self.project,
        job_id = self.id_hash,
        max_turns = self.max_turns,
        timeout_seconds = self.timeout_seconds,
        on_message = self._on_message_callback,
        debug = self.debug,
    )
    if self.task_type == "BOUNDED":
        result = await orchestrator.run_bounded()
    elif self.task_type == "INTERACTIVE":
        result = await orchestrator.run_interactive()  # raises NotImplementedError today
    else:
        raise ValueError( f"Unknown task_type: {self.task_type!r}" )
    ...
```

`run_bounded()` runs the EXISTING dispatcher's BOUNDED-mode logic (subprocess `claude -p ...`) — preserved verbatim from `dispatcher.py:122+`, just relocated and rebound onto the orchestrator instance state. The internal `if task.type == BOUNDED: ... else: ...` branch in the current `dispatcher.dispatch()` body splits into two separate methods.

**`on_message` placement**: stays on `__init__` (mirrors current dispatcher shape + every other agent's callback placement; not a per-call concern). **`working_dir` resolution**: defaults to `cu.get_project_root()` (project="lupin" case) or `cu.get_project_root() + "/" + project` (other projects); validated as existing directory in `__init__`; raises `ValueError` if not.

**`ClaudeCodeRunResult` is NOT net-new** — it's `TaskResult` (currently at `dispatcher.py:101-111`) renamed during relocation, with one field added (`transcript_path`) and one renamed (`result` → `output_text` for symmetry with `self.output_text` on the job). Migration: rename → relocate to `state.py` alongside `Task`/`TaskType`/`SessionInfo` → add `transcript_path: str` field → rename `result` → `output_text`. Existing 7 fields (`task_id`, `success`, `session_id`, `cost_usd`, `duration_ms`, `error`, `exit_code`) preserved.

**`write_transcript()` placement — architectural choice**: this method lives on the orchestrator class (not as a utility function like DR's `save_report_with_frontmatter` in `cli.py:788-850`, and not as a job-level method like TFE/BFE's `_write_final_report`). The choice is intentional: the orchestrator owns the subprocess-spawn lifecycle and is the only call site that knows when output is final-and-ready-to-persist. Pushing it to a utility would force the orchestrator to call into utility code with all its state; pushing it to the job would re-couple the job layer to BOUNDED-specific output-formatting logic that should stay encapsulated. The tradeoff: orchestrator now does I/O (file write) + Gister-based slug generation in addition to dispatch — slightly broadens its responsibility, but the alternative (separation) is a lossy abstraction.

`write_transcript` uses `cu.get_project_root()` + `config.transcript_dir`, generates slug via `Gister` (mirror DR `job.py:237-244`), follows `feedback_presentation_filename_convention` (EST timestamp).

#### Sub-phase 2b — Update consumers

| Consumer | Current | After |
|----------|---------|-------|
| `src/cosa/agents/claude_code/job.py:240` | `from cosa.orchestration.claude_code import ClaudeCodeDispatcher, Task, TaskType` | `from cosa.agents.claude_code.orchestrator import ClaudeCodeOrchestrator` (and Task/TaskType from `state`) |
| `src/cosa/agents/claude_code/job.py:468` | `from cosa.orchestration.claude_code.message_history import MessageHistory` | `from cosa.agents.claude_code.message_history import MessageHistory` |
| `src/cosa/agents/swe_team/hooks.py:14` | docstring reference: `ClaudeCodeDispatcher (dispatcher.py)` | docstring reference: `ClaudeCodeOrchestrator (cosa.agents.claude_code.orchestrator)` — comment-only update, no code change |
| `src/tests/manual/test_option_b_interactive.py` | `from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType, TaskResult` | Update import to new path + add `pytest.mark.skip(reason="INTERACTIVE deferred — see TODO.md")` per 2026-05-05 retirement skip-with-breadcrumb convention |
| `src/tests/manual/test_option_b_inject_info.py` | same | same skip-mark |
| `src/tests/manual/test_option_b_inject_interrupt.py` | same | same skip-mark |
| `src/tests/manual/test_option_b_bidirectional.py` | same | same skip-mark |
| `src/tests/integration/test_dispatcher_e2e.py` | `from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType, TaskResult` + constructor + `.dispatch()` | Update import to `cosa.agents.claude_code.orchestrator.ClaudeCodeOrchestrator`; rename `.dispatch()` callsites to `.run_bounded()`; reframe asserts to match new return-shape (`ClaudeCodeRunResult`). Stays active. |
| `src/tests/integration/test_dispatcher_bidirectional.py` | Same imports + INTERACTIVE methods (`.inject() / .interrupt() / .get_active_sessions()`) + `from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE` | Update import paths; the INTERACTIVE-method tests get `pytest.mark.skip(reason="INTERACTIVE deferred")` (those methods now raise NotImplementedError); BOUNDED tests stay active with method rename. |
| `src/tests/integration/test_sdk_validation.py` | `from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE` | Update import path. **MANDATE**: `SDK_AVAILABLE` MUST be explicitly listed in `cosa/agents/claude_code/__init__.py` `__all__` exports (in addition to whatever the orchestrator module re-exports) so the flag's public surface stays addressable. Without explicit `__all__` listing, `from cosa.agents.claude_code import SDK_AVAILABLE` may fail silently depending on Python import machinery. |

#### Sub-phase 2c — Delete the orphan tree

```bash
rm -rf src/cosa/orchestration/
```

Single command after consumer updates land. Verify `grep -rn "cosa\.orchestration" src/ | grep -v "\.pyc\|__pycache__\|/rnd/\|history\.md"` returns zero hits before deletion.

R&D archaeology references in `src/rnd/v0.1.0/2025.12.31-claude-code-via-mcp-and-cosa-vox/` and `src/rnd/v0.1.1/2026.01.08-cold-call-path-1-ui-card-plan.md` stay — they're frozen design history, not active imports. Optional: append retirement-pointer footnote citing the new location.

### Phase 3 — `cosa_interface.py` + `voice_io.py` refactor

`cosa_interface.py` — port the ContextVar isolation block from `src/cosa/agents/deep_research/cosa_interface.py:91-130`:
- `set_dispatch_context( sender_id, target_user, session_name )` — sets ContextVars
- `reset_dispatch_context( tokens )` — restores
- Module-level `SENDER_ID` / `TARGET_USER` / `SESSION_NAME` retained for back-compat
- `_get_sender_id( suffix=None )` accepts optional suffix
- Add `notify_completion( ... )` + `notify_failure( ... )` thin wrappers around existing `_dispatcher.notify_progress`

`voice_io.py` — replace 15-line shim with agent-bound wrapper (mirror DR `voice_io.py:1-56`):

```python
from cosa.agents.utils import voice_io as _core_voice_io
from . import cosa_interface as _cosa_interface

_core_voice_io.configure( _cosa_interface )

def reconfigure(): _core_voice_io.configure( _cosa_interface )

# Re-export: set_cli_mode, is_voice_available, set_job_id, clear_job_id,
# notify, ask_yes_no, get_input, choose
```

**Notification contract** (BOUNDED): start (`priority=low`), pre-flight done (`low`), dispatch begin (`medium`), per-message progress via `on_message_callback` (`low`), completion (`medium` with `abstract` linking transcript), failure (`urgent`).

### Phase 4 — `job.py` rewire

In-place edits to `src/cosa/agents/claude_code/job.py`:

1. Delete inline `_load_config_defaults()` classmethod + `_default_max_turns/_default_timeout` cls-vars (lines ~73-90); replace with `self.config = ClaudeCodeConfig.from_config( config_mgr )` in `__init__`.
2. Add `self.cc_state = ClaudeCodeState.PRE_FLIGHT`. Top-level `JobState` transitions in `do_all()` (lines 193-211) stay as-is; `cc_state` is the parallel agent-internal track.
3. In `_execute()` (lines 225+): replace direct dispatcher import (line 240) with `from cosa.agents.claude_code.orchestrator import ClaudeCodeOrchestrator`. Instantiate the orchestrator with ALL args on `__init__` (config, prompt, project, job_id, max_turns, timeout_seconds, on_message, debug). Then route on `self.task_type`: `if self.task_type == "BOUNDED": result = await orchestrator.run_bounded()` / `elif self.task_type == "INTERACTIVE": result = await orchestrator.run_interactive()` (raises `NotImplementedError` today) / `else: raise ValueError(...)`. Job-level routing mirrors Podcast's mode-method pattern (`do_all_async` / `do_review_only_async` / `do_audio_only_async`).
4. Generate `semantic_topic` via `Gister` (mirror DR `job.py:237-244`).
5. Apply ContextVar isolation block (mirror DR `job.py:246-262`): build per-job `sender_id`, call `cosa_interface.set_dispatch_context( ... )`, call `voice_io.set_job_id( self.id_hash )`.
6. Compute `transcript_path = orchestrator.write_transcript( result.output_text, ... )`.
7. Replace truncated artifacts (lines 289-296) with full artifacts dict:
   ```python
   self.artifacts = {
       "transcript_path" : transcript_path,
       "abstract"        : completion_abstract,
       "cost_usd"        : self.cost_usd,
       "task_type"       : self.task_type,
       "project"         : self.project,
       "session_id"      : result.session_id,
       "duration_ms"     : result.duration_ms,
       "cc_state"        : self.cc_state.value,
   }
   self.output_text = result.output_text  # full, not [:500]
   ```
8. Reserve `inject( self, message )`, `interrupt( self )`, `end_session( self )` methods on the job — each raises `NotImplementedError( "INTERACTIVE controls deferred — see TODO.md restoration milestone" )`.
9. `finally: voice_io.clear_job_id()` (mirror DR line 391).

### Phase 5 — `__main__.py` (CLI)

argparse:
- `--prompt` (required)
- `--project` (default "lupin")
- `--task-type` (BOUNDED only today; reject INTERACTIVE with "deferred" message)
- `--max-turns` (int) / `--timeout` (int)
- `--dry-run` / `--debug` / `--verbose`

Flow: `ConfigurationManager` → `ClaudeCodeConfig.from_config` → `ClaudeCodeJob( ... )` → `job.do_all()` → print `transcript_path` + `cost_usd` + last 200 chars of output. Runnable: `python -m cosa.agents.claude_code --prompt "..." --dry-run` (after `PYTHONPATH=src` bootstrap).

### Phase 6 — Tests

Lupin parent-repo paths.

**Test-file deliverables (code edits)**:

- [ ] EXECUTOR: AI — Update `src/tests/smoke/test_claude_code_dry_run_smoke.py`: replace `output_text[:500]` assertion with `len( job.output_text ) >= len( expected_full )`; add `"transcript_path" in job.artifacts`, `Path( job.artifacts["transcript_path"] ).exists()`, `"cc_state" in job.artifacts`.
- [ ] EXECUTOR: AI — Create `src/tests/unit/test_claude_code_orchestrator.py`: mock `ClaudeCodeDispatcher.dispatch`; assert `run_bounded` returns `ClaudeCodeRunResult` with full output; assert `inject/interrupt/end_session` raise `NotImplementedError`; assert `write_transcript` produces presentation-filename pattern.
- [ ] EXECUTOR: AI — Create `src/tests/unit/test_claude_code_state.py`: enum membership; pre_flight → executing → completed transition recorded.
- [ ] EXECUTOR: AI — Create `src/tests/unit/test_claude_code_config.py`: defaults; `from_config` with mocked `ConfigurationManager` reading `claude code max turns`, `claude code transcript dir`, etc.
- [ ] EXECUTOR: AI — Create `src/tests/unit/test_claude_code_cosa_interface.py`: `set_dispatch_context` writes ContextVars; concurrent fake jobs see isolated `sender_id`s (regression test for the isolation contract under agentic-pool concurrency).
- [ ] EXECUTOR: AI — Create `src/tests/smoke/test_claude_code_cli_smoke.py`: `subprocess.run([ sys.executable, "-m", "cosa.agents.claude_code", "--dry-run", "--prompt", "hi" ])` returncode 0.

**Verification ladder** (per project POST-EDIT VERIFICATION mandate):

- [ ] EXECUTOR: AI — `python -m py_compile` each new + edited file.
- [ ] EXECUTOR: AI — Import-chain check: `python -c "from cosa.agents.claude_code.{job,orchestrator,config,state} import *; print('ok')"`.
- [ ] EXECUTOR: AI — Unit suite: `pytest src/tests/unit/test_claude_code_*.py -v` → all green.
- [ ] EXECUTOR: AI — Smoke suite on `:7999` (non-destructive dry-runs): `pytest src/tests/smoke/test_claude_code_dry_run_smoke.py src/tests/smoke/test_claude_code_cli_smoke.py -v` → all green.
- [ ] EXECUTOR: AI — Live BOUNDED run on `:7999` per Phase 7a below.

### Phase 7 — Live verification + cross-agent regression

#### Sub-phase 7a — Live `:7999` verification (Claude Code direct path)

- [ ] EXECUTOR: AI — `POST :7999/api/claude-code/queue/submit` with `dry_run=true` and a real prompt; assert HTTP 202; poll `/api/jobs/{job_id}` until status=`COMPLETED`; assert `artifacts.transcript_path` non-null and file exists on disk under `io/claude-code/`.
- [ ] EXECUTOR: AI — Concurrent isolation test: submit two jobs back-to-back with different `user_email` JWTs; verify completion notifications route correctly (no sender_id leak between jobs). End-to-end validation of the ContextVar work.
- [ ] EXECUTOR: AI — Smoke router survival: assert `agentic_job_factory.py:199-212` still constructs `ClaudeCodeJob` correctly (no signature break) by submitting one job and confirming it lands in the run queue under the expected `cc-*` ID prefix.

#### Sub-phase 7b — Cross-agent regression (sibling-agent contracts)

**Pre-refactor baseline** — captured **BEFORE Phase 1** (i.e., before ANY code edits land — Phase 2a's relocation alone could leak into TFE/BFE/swe_team/tfe_to_cc, so the baseline must precede Phase 1's first edit). Per the regression-guard contract in `00-working-contract.md`:

- [ ] EXECUTOR: AI — `pytest src/tests/smoke/test_tfe_error_capture_smoke.py -v --tb=no | tee /tmp/cc-redesign-baseline-tfe.txt`
- [ ] EXECUTOR: AI — `pytest src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py -v --tb=no | tee /tmp/cc-redesign-baseline-bfe.txt`
- [ ] EXECUTOR: AI — `pytest src/tests/smoke/test_swe_team_dry_run_e2e.py src/tests/smoke/test_swe_team_orchestrator_dry_run_smoke.py -v --tb=no | tee /tmp/cc-redesign-baseline-swe.txt`
- [ ] EXECUTOR: AI — `pytest src/tests/unit/test_tfe_to_cc_*.py -v --tb=no | tee /tmp/cc-redesign-baseline-tfe2cc.txt`
- [ ] EXECUTOR: HUMAN (baseline acknowledgement gate — per `00-working-contract.md` user-involvement gate item 5) — Confirm the baseline files exist before AI proceeds with Phase 4 code rewire.

Snapshot pass/fail counts in `90-execution-log.md` Phase 7b. **Expected**: all green pre-refactor.

**Post-refactor regression run** — after Phase 4 job rewire lands (i.e., AFTER all of Phase 1 → Phase 2a → 2b → 2c → 3 → 4 are complete; this is the final regression check before Phase 5 CLI work):

- [ ] EXECUTOR: AI — Direct CC: `pytest src/tests/smoke/test_claude_code_dry_run_smoke.py src/tests/smoke/test_claude_code_max_subscription.py -v` → all green.
- [ ] EXECUTOR: AI — Integration BOUNDED: `pytest src/tests/integration/test_dispatcher_e2e.py -v` → all green.
- [ ] EXECUTOR: AI — Integration mixed (BOUNDED-only subset): `pytest src/tests/integration/test_dispatcher_bidirectional.py -v -k "not interactive and not inject and not interrupt"` → all green; INTERACTIVE-method tests skip-marked (counted but not executed).
- [ ] EXECUTOR: AI — Integration SDK: `pytest src/tests/integration/test_sdk_validation.py -v` → all green; `SDK_AVAILABLE` flag re-exported correctly.
- [ ] EXECUTOR: AI — Sibling regression TFE: `pytest src/tests/smoke/test_tfe_error_capture_smoke.py -v --tb=no | tee /tmp/cc-redesign-post-tfe.txt`; diff vs `/tmp/cc-redesign-baseline-tfe.txt` → zero new failures.
- [ ] EXECUTOR: AI — Sibling regression BFE: same shape, baseline path `/tmp/cc-redesign-baseline-bfe.txt`.
- [ ] EXECUTOR: AI — Sibling regression swe_team: same shape, baseline path `/tmp/cc-redesign-baseline-swe.txt`.
- [ ] EXECUTOR: AI — Sibling regression tfe_to_cc prompt-builders (forward-compat): same shape, baseline path `/tmp/cc-redesign-baseline-tfe2cc.txt`.

**Acceptance**: post-refactor counts must match the baseline snapshot. Any new failure in TFE/BFE/swe_team/tfe_to_cc indicates the refactor leaked into a path that the audit missed — STOP and re-investigate before continuing.

**Forward-compat note**: `src/cosa/agents/tfe_to_cc/` will eventually invoke the new orchestrator at runtime when the INI engine flag flips on (per `__init__.py` future-work comment). The tests' continued green state is the contract that says "the orchestrator is callable from outside the agent" — preserving this is part of the design goal.

#### Sub-phase 7c — `:8000` scheduled run (full regression sweep)

Per `feedback_test_server_monopolize_mode`: schedule via `POST /api/test-suite/submit` with user-confirmed `scheduled_at`. Suite scope: full smoke + relevant integration. The `:8000` slot-ask is calendar coordination only — NOT budget approval.

- [ ] EXECUTOR: HUMAN (`:8000` slot-availability per Lupin CLAUDE.md §TESTING VENUES — user has schedule visibility AI does not) — Confirm a clean monopolize-mode slot for the full regression sweep.
- [ ] EXECUTOR: AI — Submit via `POST /api/test-suite/submit` with `test_types=smoke,integration` and the user-confirmed `scheduled_at`.
- [ ] EXECUTOR: AI — Poll the test-suite job until done; pull report; assert zero new failures vs the `:7999` Phase-7b post-refactor counts.

### Phase 8 — Documentation refresh

1. **NEW** `src/docs/agents/claude-code-job-guide.md` — canonical agent-doc shape (sibling to `bug-fix-expediter-guide.md`).
2. **Update** `src/docs/rest-api-reference.md` — `/api/claude-code/queue/submit` row: mention `artifacts.transcript_path` is full output (untruncated).
3. **Update** `TODO.md` — close the "Restore Claude Code INTERACTIVE controls" pre-work milestone (extensibility hooks landed); leave actual INTERACTIVE restoration row OPEN, note hooks are in place.
4. **Refresh** `/src/ephemera/prompts/data/synthetic-data-agent-routing-claude-code.txt` — add 5-10 examples calling out the new transcript-file affordance ("save the output to disk", "give me a transcript link") per `feedback_voice_routing_training_data`.

### Phase 9 — Wrap

- File a tracking entry in `bug-fix-queue.md` under Completed (this redesign predates a bug; tracking-only).
- `history.md` (Lupin parent) entry; duplicate to `src/cosa/history.md` per CoSA CLAUDE.md ritual.
- **Commit shape** (user-driven for both — Claude must NOT run git in `src/cosa/` per `feedback_lupin_only_never_cosa`):
  - **Commit 1 (CoSA submodule)**: 9 files in `src/cosa/agents/claude_code/` (3 edited, 4 new, 2 relocated) + `src/cosa/agents/swe_team/hooks.py` (docstring) + DELETION of `src/cosa/orchestration/` (entire tree) + `src/cosa/history.md` ritual entry
  - **Commit 2 (Lupin parent)**: tests (1 edit, 5 new, 3 manual-test imports + skip-marks, 3 integration tests) + docs (`src/docs/agents/claude-code-job-guide.md` new, `rest-api-reference.md` edit) + R&D pair (01-design + 90-execution-log) + INI splainer + training data + TODO.md + history.md

---

## Critical files

**Edit (CoSA — user commits separately)**:
- `src/cosa/agents/claude_code/job.py` — primary rewire + import path updates (240, 468)
- `src/cosa/agents/claude_code/cosa_interface.py` — ContextVar isolation
- `src/cosa/agents/claude_code/voice_io.py` — agent-bound wrapper
- `src/cosa/agents/swe_team/hooks.py:14` — docstring comment update (orchestrator path reference)

**MOVE (CoSA — user commits separately)**:
- `src/cosa/orchestration/claude_code/dispatcher.py` → `src/cosa/agents/claude_code/orchestrator.py` (rename class + method per canonical naming)
- `src/cosa/orchestration/claude_code/message_history.py` → `src/cosa/agents/claude_code/message_history.py` (verbatim)

**DELETE (CoSA — user commits separately)**:
- `src/cosa/orchestration/` (entire directory: README.md, `__init__.py`, `claude_code/`, all `.pyc` caches)

**NEW (CoSA — user commits separately)**:
- `src/cosa/agents/claude_code/config.py`
- `src/cosa/agents/claude_code/state.py` (includes relocated `Task`/`TaskType`/`TaskResult`/`SessionInfo` dataclasses)
- `src/cosa/agents/claude_code/__main__.py`

**Edit (Lupin parent)**:
- `src/tests/smoke/test_claude_code_dry_run_smoke.py` — assertion updates
- `src/tests/smoke/test_claude_code_max_subscription.py` — assertion updates if needed
- `src/tests/integration/test_dispatcher_e2e.py` — import path + class rename + method rename
- `src/tests/integration/test_dispatcher_bidirectional.py` — import path + class rename; INTERACTIVE skip-marked
- `src/tests/integration/test_sdk_validation.py` — import path (`SDK_AVAILABLE` re-exported from new location)
- `src/tests/manual/test_option_b_interactive.py` — import path update + skip-mark
- `src/tests/manual/test_option_b_inject_info.py` — import path update + skip-mark
- `src/tests/manual/test_option_b_inject_interrupt.py` — import path update + skip-mark
- `src/tests/manual/test_option_b_bidirectional.py` — import path update + skip-mark
- `src/conf/lupin-app.ini` + `lupin-app-splainer.ini` — new `claude code *` keys
- `TODO.md` — close pre-work milestone
- `src/docs/rest-api-reference.md` — refresh queue-submit row
- `/src/ephemera/prompts/data/synthetic-data-agent-routing-claude-code.txt` — add transcript examples

**NEW (Lupin parent)**:
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/{01-design.md,90-execution-log.md}` (this directory)
- `src/tests/unit/test_claude_code_orchestrator.py`
- `src/tests/unit/test_claude_code_state.py`
- `src/tests/unit/test_claude_code_config.py`
- `src/tests/unit/test_claude_code_cosa_interface.py`
- `src/tests/smoke/test_claude_code_cli_smoke.py`
- `src/docs/agents/claude-code-job-guide.md`

**Reference (read-only — copy patterns)**:
- `src/cosa/agents/deep_research/job.py` — gold reference for `_execute()` shape (lines 237-262, 391)
- `src/cosa/agents/deep_research/cosa_interface.py:91-130` — ContextVar block to port
- `src/cosa/agents/deep_research/voice_io.py:1-56` — agent-bound wrapper pattern
- `src/cosa/agents/deep_research/config.py:12-100` — config dataclass shape
- `src/cosa/agents/deep_research/state.py:14-56` — state enum shape
- `src/cosa/orchestration/claude_code/dispatcher.py` — existing BOUNDED implementation to relocate (preserve verbatim during move)

**Wiring (no changes needed)**:
- `src/cosa/rest/agentic_job_factory.py:199-212` — factory dispatch (keep `__init__` signature backward-compatible)
- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py:106-126` — expeditor registry
- `conf/training/agent-router-agentic-commands.json:63-66` — voice training entry

---

## Verification (EXECUTOR-tagged)

All verification below is AI-executable on `:7999` (AI-discretionary venue per Lupin CLAUDE.md §TESTING VENUES). The `:8000` step requires a user-confirmed slot per Phase 7c above.

- [ ] EXECUTOR: AI — `python -m py_compile src/cosa/agents/claude_code/{config,state,orchestrator,cosa_interface,voice_io,job,__main__,__init__}.py` (after `PYTHONPATH=src` bootstrap)
- [ ] EXECUTOR: AI — `python -c "from cosa.agents.claude_code.job import ClaudeCodeJob; from cosa.agents.claude_code.orchestrator import ClaudeCodeOrchestrator; from cosa.agents.claude_code.config import ClaudeCodeConfig; from cosa.agents.claude_code.state import ClaudeCodeState; print('ok')"`
- [ ] EXECUTOR: AI — CLI smoke: `python -m cosa.agents.claude_code --prompt "list files" --dry-run --debug`
- [ ] EXECUTOR: AI — Unit suite: `pytest src/tests/unit/test_claude_code_config.py src/tests/unit/test_claude_code_state.py src/tests/unit/test_claude_code_orchestrator.py src/tests/unit/test_claude_code_cosa_interface.py -v`
- [ ] EXECUTOR: AI — Smoke against `:7999`: `pytest src/tests/smoke/test_claude_code_dry_run_smoke.py src/tests/smoke/test_claude_code_cli_smoke.py -v`
- [ ] EXECUTOR: AI — Live `:7999` BOUNDED probe: `curl -X POST http://localhost:7999/api/claude-code/queue/submit -H "Authorization: Bearer ${JWT}" -d '{"prompt":"echo hi","dry_run":true}'`; poll `/api/jobs/{id}` until COMPLETED; verify transcript file on disk.
- [ ] EXECUTOR: AI — Concurrent isolation test: 2x POST with different JWTs; verify no sender_id leak.
- [ ] EXECUTOR: AI — Cross-agent baseline: `pytest src/tests/smoke/test_tfe_error_capture_smoke.py src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py src/tests/smoke/test_swe_team_dry_run_e2e.py src/tests/smoke/test_swe_team_orchestrator_dry_run_smoke.py src/tests/unit/test_tfe_to_cc_*.py -v --tb=no | tee /tmp/cc-redesign-baseline.txt` (**BEFORE Phase 1** — pre-refactor state)
- [ ] EXECUTOR: AI — Cross-agent post-refactor: same suite, output to `/tmp/cc-redesign-post.txt`; `diff /tmp/cc-redesign-baseline.txt /tmp/cc-redesign-post.txt | grep -E "FAILED|PASSED|ERROR"` shows zero new failures.
- [ ] EXECUTOR: AI — Residue check 1 (orphan tree gone): `ls src/cosa/orchestration/` returns "No such file or directory".
- [ ] EXECUTOR: AI — Residue check 2 (zero active references): `grep -rn "cosa\.orchestration" src/ | grep -v "\.pyc\|__pycache__\|/rnd/\|history\.md"` returns zero hits.
- [ ] EXECUTOR: AI — Residue check 3 (class rename complete): `grep -rn "ClaudeCodeDispatcher" src/cosa/ src/tests/ src/fastapi_app/ | grep -v "\.pyc\|__pycache__\|/rnd/\|history\.md\|# .*ClaudeCodeDispatcher"` returns zero hits in active code.

---

## Acceptance criteria

| AC | Criterion |
|----|-----------|
| AC1 | 9 canonical files present in `src/cosa/agents/claude_code/` (8 + `message_history.py`) |
| AC2 | `ClaudeCodeConfig.from_config` round-trips INI overrides |
| AC3 | `ClaudeCodeState` enum exposed; `cc_state` in artifacts |
| AC4 | **`src/cosa/orchestration/` directory does NOT exist** — `ls src/cosa/orchestration` returns "No such file or directory" |
| AC4b | **`grep -rn "cosa\.orchestration" src/ \| grep -v "\.pyc\|__pycache__\|/rnd/\|history\.md"` returns zero hits** (no active code references the relocated tree) |
| AC5 | `set_dispatch_context()` exists; concurrent-jobs unit test passes (no sender_id leak) |
| AC6 | `voice_io.py` is agent-bound wrapper (binds `_core_voice_io.configure( _cosa_interface )`), not bare re-export |
| AC7 | `job.artifacts["transcript_path"]` non-null and file exists on disk after BOUNDED run |
| AC8 | `job.output_text` is full (untruncated) — no `[:500]` slice anywhere |
| AC9 | `inject` / `interrupt` / `end_session` exist on both job and orchestrator and raise `NotImplementedError` |
| AC10 | `python -m cosa.agents.claude_code --dry-run --prompt "..."` completes returncode 0 |
| AC11 | The 4 manual tests in `src/tests/manual/test_option_b_*.py` import cleanly from new path AND INTERACTIVE-method tests are skip-marked with retirement breadcrumb |
| AC12 | `src/tests/integration/test_dispatcher_e2e.py` BOUNDED test cases pass with relocated imports + renamed method (`run_bounded`) |
| AC13 | `src/tests/integration/test_dispatcher_bidirectional.py` BOUNDED-subset passes; INTERACTIVE methods skip-marked |
| AC14 | `src/tests/integration/test_sdk_validation.py` passes — `SDK_AVAILABLE` flag re-exported from new location |
| AC15 | **Cross-agent regression: zero new failures** in TFE / BFE / swe_team smoke + tfe_to_cc unit tests vs pre-refactor baseline |
| AC16 | Forward-compat: `tfe_to_cc/` package imports cleanly; the future runtime-engine path can call `ClaudeCodeOrchestrator.run_bounded()` without further refactoring |
| AC17 | `ClaudeCodeOrchestrator.__init__` validates `working_dir` resolves to an existing directory; raises `ValueError` with the offending path when not. Defaults: `project="lupin"` → `cu.get_project_root()`; otherwise `cu.get_project_root() + "/" + project`. |
| AC18 | `ClaudeCodeJob._execute()` routes on `self.task_type`: BOUNDED → `run_bounded()`, INTERACTIVE → `run_interactive()` (raises `NotImplementedError`), unknown → `ValueError`. Single orchestrator instantiation per job; mode-method pattern matches Podcast (`do_all_async` / `do_review_only_async` / `do_audio_only_async`). |

---

## Risk surface

- **ContextVar pool isolation regression** (highest): if `set_dispatch_context()` is wired wrong, concurrent jobs leak `sender_id` — notifications route to wrong user. **Mitigation**: dedicated unit test `test_claude_code_cosa_interface.py` runs two fake jobs in parallel via `asyncio.gather`, asserts each sees its own ContextVar.
- **Smoke-test signature drift**: `test_claude_code_dry_run_smoke.py` currently asserts truncated `output_text`. **Mitigation**: deliberate assertion update, not a rewrite — only the truncation assertion changes.
- **Dispatcher BOUNDED-branch behavioral preservation**: the relocation is mechanical for the BOUNDED path — class rename + method rename + new file location, but the actual subprocess-spawn logic stays verbatim. The INTERACTIVE branch in the original `dispatcher.py` is preserved as commented archaeology in `orchestrator.py` for restoration paper trail (per 2026-05-05 retirement convention).
- **Factory wiring regression**: `agentic_job_factory.py:199-212` constructs `ClaudeCodeJob` with positional/keyword args — keep `__init__` signature backward-compatible (additions only, no renames).
- **Splainer mandate**: every new INI key in `lupin-app.ini` needs a paired entry in `lupin-app-splainer.ini` (CoSA CLAUDE.md). Easy to forget; checklist item in execution log.
- **CoSA git boundary**: Claude must not run any git commands inside `src/cosa/` per `feedback_lupin_only_never_cosa`. Phase 9 commit-1 is user-driven; Claude only stages the file list mentally.

---

## Out of scope

- INTERACTIVE runtime (the `inject` / `interrupt` / `end_session` IMPLEMENTATIONS — only stubs land today)
- Mobile port (`lupin-mobile/lib/features/claude_code/data/claude_code_repository.dart` — separate mobile session, already in TODO.md)
- Per-turn streaming UI (lost in 2026-05-05 retirement; restoration is a separate plan tied to the Multiplexer ClaudeCodeTransport decision)
- `ClaudeCodeDispatcher` BOUNDED logic refactoring (preserve verbatim during relocation; only rename + reframe public interface)
- TFE/BFE runtime integration via `tfe_to_cc/` (future work behind INI engine flag — design with this in mind, but don't implement)

---

## Next steps

User-driven, per `feedback_pip_plan_review_is_sequential`:

1. **PIP plan review — sequential, three gates** (NOT parallel — the parallel-shortcut antipattern was flagged on 2026-05-05):
   - **REUSE pass** — find existing functions / utilities / patterns the plan should call instead of writing new code. User gate. Apply.
   - **Pass 1 Fitness** — does the plan satisfy its own ACs? Does it match the problem? User gate. Apply per-finding (NOT batched).
   - **Pass 2 Adversarial** — what's the worst case? What ambiguities, race conditions, security gaps? User gate. Apply per-finding.
2. **Execution begins** only after Pass 2 closure. Phase 1 config/state → Phase 2 relocate → ... → Phase 9 wrap.
3. **Cross-agent baseline** captured in Phase 7b BEFORE any code changes (as the regression-guard contract).
