# Presentation Generator Phase 4: Outline & Elaborate + fuzzy_file_match

**Date**: 2026-03-24
**Session**: 371
**Plan source**: `~/.claude/plans/memoized-popping-bunny.md`

## Context

Phases 1-3 of the Presentation Generator are complete (foundation, state models, ingest + narrative analysis + Gate 1). Phase 4 implements the core content generation: generating slide outlines with titles and visual types, then elaborating each slide with full content and presenter notes. This is the heart of the presentation pipeline — once Phase 4 is done, the system produces reviewable structured content from any source document.

Additionally, the `fuzzy_file_match` special handler TODO item needs resolution — investigation shows it's **already wired** and functional (shared config with Podcast Generator). A dedicated config key for presentation-specific search paths is the only remaining work.

---

## Part A: fuzzy_file_match — Config Key (Small)

**Status**: Handler logic, registry entry, and search paths all work. The `source` arg in the presentation generator registry already maps to `fuzzy_file_match`. The handler uses `podcast generator source search paths = /src` which recursively covers `src/rnd/` and `src/docs/`. The `io/deep-research/{user}/` path is hardcoded in the handler.

**Change**: Add a presentation-specific config key so search paths can diverge from podcast's in the future.

### Files to modify:
1. **`src/conf/lupin-app.ini`** — Add `presentation generator source search paths = /src` under `[Lupin: Baseline]`
2. **`src/conf/lupin-app-splainer.ini`** — Add matching explainer entry
3. **`src/cosa/agents/runtime_argument_expeditor/expeditor.py`** — In `_handle_fuzzy_file_match()`, check for agent-specific config key first, fall back to podcast key
4. **Update TODO.md** — Mark fuzzy_file_match item as complete

---

## Part B: Phase 4 — Outline & Elaborate (Main Work)

### Design Decisions

1. **Two new prompt files** (`prompts/outline.py` and `prompts/elaboration.py`) — narrative.py is ~280 lines and handles one concern. Each new file follows the same 3-part pattern: system prompt + prompt builder + response parser.

2. **New `SlideOutline` Pydantic model** in `state.py` — lightweight intermediate between NarrativeSection and SlideModel. Carries `number`, `arc_position`, `type`, `title`, `visual_type`, `source_hint`. This gives type safety for Gate 2 and a clean contract for elaboration input.

3. **Elaboration strategy: all-at-once** with chunked fallback — a 15-slide deck produces ~3-4K tokens of JSON, well within 8192 max_tokens. If response is truncated (stop_reason != "end_turn"), split into batches of ~6 slides and retry.

4. **Gate 2/3 use same voice I/O pattern as Gate 1** — `present_choices()` with Approve/Revise/Cancel, revision loop with feedback via `get_input()`, max_revisions tracking.

### Implementation Order

#### Step 1: `state.py` — Add SlideOutline model
- Add `SlideOutline( BaseModel )` between `NarrativeSection` and `PresenterNotes`
- Fields: `number: int`, `arc_position: str`, `type: str`, `title: str`, `visual_type: str = "text_only"`, `source_hint: Optional[str] = None`
- Add `outline_revision_count` and `elaborate_revision_count` to `create_initial_state()`
- Update smoke test with SlideOutline test case
- **Reuse**: Existing `SlideModel` field conventions (arc_position as str, visual_type default)

#### Step 2: `prompts/outline.py` — New file (~250 lines)
- **System prompt** (`OUTLINE_SYSTEM_PROMPT`): role assignment → structural formula (2-3 opening + N body + 2-3 closing) → assertion-style title instruction with examples → visual type taxonomy (all 8 types with when-to-use) → visual rhythm rule ("never 3+ consecutive text_only") → slide type taxonomy (title, hook, agenda, key_point, evidence, comparison, summary, cta, qa) → JSON schema
- **Prompt builder** (`get_outline_prompt()`): params = narrative_sections, slide_budget, title_style, audience, audience_context, human_feedback. Import `AUDIENCE_COMPLEXITY_GUIDELINES` from `narrative.py`. Format sections as numbered list with arc positions + proposed counts.
- **Response parser** (`parse_outline_response()`): strip markdown code blocks → parse JSON → extract `outline` array → validate arc_position ∈ {opening, body, closing}, visual_type ∈ taxonomy, type ∈ slide types → coerce types → return `List[dict]`
- **Constants**: `SLIDE_TYPES`, `VISUAL_TYPES`, `STRUCTURAL_POSITIONS` lists

#### Step 3: Unit tests for outline prompts (~35 tests)
- **File**: `src/tests/unit/test_presentation_outline_prompts.py`
- Test groups: system prompt content (5), prompt builder (10), response parser (15), constants (5)
- Follow pattern from `test_presentation_prompts.py`

#### Step 4: `prompts/elaboration.py` — New file (~300 lines)
- **System prompt** (`ELABORATION_SYSTEM_PROMPT`): role as "presentation content writer and speaking coach" → content bullet guidelines (3-5 per slide, substantive, assertion-based) → presenter notes guidelines (transition, 2-4 talking points of what to SAY not what's ON slide, timing_seconds, emphasis) → visual_description guidelines (natural-language renderer spec) → JSON schema matching `SlideModel` fields
- **Prompt builder** (`get_elaboration_prompt()`): params = slide_outlines, source_content, target_duration_minutes, audience, audience_context, human_feedback. Format outlines as JSON. Include source (truncated at 30K chars). Calculate `avg_seconds_per_slide`.
- **Response parser** (`parse_elaboration_response()`): strip markdown → parse JSON → extract `slides` array → validate all SlideModel fields → ensure presenter_notes is complete dict → coerce types → return `List[dict]`

#### Step 5: Unit tests for elaboration prompts (~35 tests)
- **File**: `src/tests/unit/test_presentation_elaboration_prompts.py`
- Test groups: system prompt content (5), prompt builder (10), response parser (15), constants (5)

#### Step 6: `orchestrator.py` — Implement `_outline_async()`
- Import outline prompt functions
- Calculate `slide_budget = int( config.target_duration_minutes * config.slides_per_minute )`
- Build prompt via `get_outline_prompt()`
- Call `self.api_client.call_for_outline( OUTLINE_SYSTEM_PROMPT, prompt )`
- Increment `self.metrics["api_calls"]` and `self.metrics["tokens_used"]`
- Parse response via `parse_outline_response()`
- Convert dicts to `List[SlideOutline]` models
- Validate structural formula (log warning if opening/closing counts off)
- Store in `self._presentation_state["slide_outline"]`
- Notify slide count breakdown
- **Return type**: change from `list` to `List[SlideOutline]`

#### Step 7: `orchestrator.py` — Implement `_gate_2_outline_review()`
- Follow Gate 1 pattern exactly (lines 656-760)
- Build "story spine" summary: group slides by arc_position (OPENING/BODY/CLOSING), show numbered titles + visual types
- `present_choices()` with Approve/Revise/Cancel
- On Revise: get feedback via `get_input()`, re-run `_outline_async()` with feedback, recursive gate
- Track `outline_revision_count` against `config.max_revisions`
- Voice I/O failure → auto-approve

#### Step 8: `orchestrator.py` — Implement `_elaborate_async()`
- Import elaboration prompt functions
- Get `source_content` from `self._presentation_state["source_content"]`
- Build prompt via `get_elaboration_prompt()`
- Call `self.api_client.call_for_elaboration( ELABORATION_SYSTEM_PROMPT, prompt )`
- Check `response.stop_reason` — if truncated, split outline into batches of ~6 and retry per batch
- Parse via `parse_elaboration_response()`
- Convert dicts to `List[SlideModel]` Pydantic instances
- Calculate total timing: `sum( s.presenter_notes.timing_seconds for s in slides )`
- Notify slide count + estimated speaking time
- **Return type**: already `List[SlideModel]`

#### Step 9: `orchestrator.py` — Implement `_gate_3_content_review()`
- Follow Gate 1 pattern
- Build condensed summary: numbered titles + type + visual_type + timing + bullet count per slide, plus totals (estimated time, visual count by type)
- `present_choices()` with Approve/Revise/Cancel
- On Revise: get feedback, re-run `_elaborate_async()` with feedback, recursive gate
- Track `elaborate_revision_count`
- Voice I/O failure → auto-approve

#### Step 10: Orchestrator integration tests (~15 tests)
- Add to `src/tests/unit/test_presentation_generator_job.py`
- `TestSlideOutlineModel` (5): construction, defaults, validation, serialization
- `TestOrchestratorPhase4` (10): mock API responses, verify outline/elaborate return types, error handling, timing calculation, gate auto-approve on empty input

#### Step 11: `prompts/__init__.py` — Update exports
- Add imports for `outline` and `elaboration` modules

---

## Critical Files

| File | Action | Lines Est. |
|------|--------|------------|
| `src/cosa/agents/presentation_generator/state.py` | Add SlideOutline model | +25 |
| `src/cosa/agents/presentation_generator/prompts/outline.py` | **New** — outline prompts | ~250 |
| `src/cosa/agents/presentation_generator/prompts/elaboration.py` | **New** — elaboration prompts | ~300 |
| `src/cosa/agents/presentation_generator/orchestrator.py` | Implement 4 stub methods | ~200 |
| `src/cosa/agents/presentation_generator/prompts/__init__.py` | Update exports | +4 |
| `src/tests/unit/test_presentation_outline_prompts.py` | **New** — ~35 tests | ~350 |
| `src/tests/unit/test_presentation_elaboration_prompts.py` | **New** — ~35 tests | ~350 |
| `src/tests/unit/test_presentation_generator_job.py` | Add ~15 tests | +150 |
| `src/conf/lupin-app.ini` | Add presentation search paths key | +1 |
| `src/conf/lupin-app-splainer.ini` | Add matching explainer | +1 |

**Reuse existing**:
- `prompts/narrative.py` — import `AUDIENCE_COMPLEXITY_GUIDELINES` dict
- `voice_io.present_choices()`, `voice_io.get_input()`, `voice_io.notify()` — same pattern as Gate 1
- `api_client.call_for_outline()`, `call_for_elaboration()` — already stubbed with correct signatures

---

## Verification

1. **Unit tests**: Run `pytest src/tests/unit/test_presentation_outline_prompts.py test_presentation_elaboration_prompts.py test_presentation_generator_job.py -v` — all pass
2. **Full unit suite**: `pytest src/tests/unit/ -v` — no regressions (currently 2229/2231, 2 pre-existing)
3. **Smoke test**: `python -m cosa.agents.presentation_generator --smoke-test` — all 7 modules pass (6 existing + SlideOutline)
4. **Manual E2E** (optional): Feed a real markdown doc through `python -m cosa.agents.presentation_generator --source <doc> --dry-run` — verify outline and elaborated slides are coherent
