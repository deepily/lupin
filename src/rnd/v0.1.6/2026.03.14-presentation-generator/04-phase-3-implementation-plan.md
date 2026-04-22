# Presentation Generator Agent — Phase 3 Implementation Plan

**Created**: 2026-03-24
**Plan source**: `~/.claude/plans/async-forging-grove.md`
**Scope**: Expeditor integration + Content Ingestion + Narrative Analysis + Gate 1

---

## Context

The Presentation Generator Agent transforms ~1200-word technical documents into 10-20 minute slide decks with presenter notes. Phases 1-2 (Session 367b) built the foundation: job class, config, REST router, factory registration, Pydantic state models, and an orchestrator skeleton with 8-phase state machine — all stub methods, no LLM calls.

**Phase 3 is where the agent starts doing real work**: reading a source document, calling Claude to analyze its narrative structure, and presenting the first human-in-the-loop gate for user approval.

**Problem discovered during planning**: The original Phase 3 spec (from `02-implementation-plan.md`) omits Runtime Argument Expeditor integration entirely. Without it, the presentation generator **cannot be invoked via voice commands** — which is the primary UX path for all agentic jobs. The factory branch exists (`agentic_job_factory.py:183-196`), but the expeditor registry entry and CLI argparse module are missing.

---

## What We're Building

### Part A: Runtime Argument Expeditor Integration (prerequisite)

Wire the presentation generator into the voice-command argument collection pipeline so users can say *"make me a presentation from my research doc"* and the expeditor collects/validates all required args.

### Part B: Content Ingestion (Orchestrator Phase 1: Ingest)

Read a source document (markdown or plain text), detect its format, and extract raw content sections by headings/paragraphs.

### Part C: Narrative Analysis (Orchestrator Phase 2: Analyze)

Call Claude API to classify each document section into narrative arc positions (setup, argument, evidence, transition, conclusion, CTA) and calculate proposed slide count.

### Part D: Gate 1 — Narrative Arc Review

Present the extracted narrative arc to the user via voice I/O for approve/revise/cancel before proceeding to outline generation.

---

## Detailed Implementation

### Part A: Expeditor Integration

**A.1 — Upgrade `__main__.py` to full CLI entry point**

File: `src/cosa/agents/presentation_generator/__main__.py` (rewrite, currently 51-line smoke test)

Follow the Podcast Generator pattern (`src/cosa/agents/podcast_generator/__main__.py`):

- Define `USER_VISIBLE_ARGS = [ "source", "target_duration_minutes", "audience", "audience_context", "theme" ]`
- Add argparse with these arguments:
  - `--source` / `-s` (str, required=False) — Path to source document (markdown/text)
  - `--target-duration-minutes` / `-d` (int, default=None) — Override target duration
  - `--audience` / `-a` (str, choices=beginner/general/expert/academic, default=None) — Audience level
  - `--audience-context` (str, default=None) — Free-text audience description (e.g., "AI architect familiar with LLMs")
  - `--theme` / `-t` (str, default=None) — Theme name
  - `--dry-run` (bool flag) — Simulate without API calls
  - `--user-visible-args` (bool flag) — Print JSON list and exit (expeditor protocol)
  - `--help` — Standard argparse help
  - System args: `--user-email`, `--user-id`, `--session-id`, `--no-confirm`
- Handle `--user-visible-args` early exit (before imports): `print( json.dumps( USER_VISIBLE_ARGS ) ); sys.exit( 0 )`
- Preserve existing smoke test functionality (move to `--smoke-test` flag or keep in separate function)

**A.2 — Add registry entry in `agent_registry.py`**

File: `src/cosa/agents/runtime_argument_expeditor/agent_registry.py`

Add new entry to `AGENTIC_AGENTS` dict:

```python
"agent router go to presentation generator" : {
    "job_prefix"         : "pr",
    "cli_module"         : "cosa.agents.presentation_generator",
    "job_class_path"     : "cosa.agents.presentation_generator.job.PresentationGeneratorJob",
    "display_name"       : "Presentation Generator",
    "required_user_args" : [ "source" ],
    "system_provided"    : [ "user_id", "user_email", "session_id" ],
    "arg_mapping"        : {
        "source"                  : "source",
        "source_path"             : "source",
        "document"                : "source",
        "file"                    : "source",
        "doc"                     : "source",
        "target_duration_minutes" : "target_duration_minutes",
        "duration"                : "target_duration_minutes",
        "minutes"                 : "target_duration_minutes",
        "audience"                : "audience",
        "audience_context"        : "audience_context",
        "theme"                   : "theme",
    },
    "fallback_questions" : {
        "source"                  : "Which document should I convert to a presentation? Describe it or say the filename.",
        "target_duration_minutes" : "How long should the presentation be in minutes? Say a number, or 'default' for 15 minutes.",
        "audience"                : "Who is the target audience? Options: beginner, general, expert, or academic.",
        "audience_context"        : "Any additional context about the audience? Say 'none' to skip.",
        "theme"                   : "Which presentation theme? Say 'default' or a theme name.",
    },
    "fallback_defaults" : {
        "target_duration_minutes" : "default",
        "audience"                : "general",
        "audience_context"        : "none",
        "theme"                   : "default",
    },
    "special_handlers" : {
        "source" : "fuzzy_file_match",  # Searches: io/deep-research/{user}/, src/rnd/, src/docs/
    },
},
```

Update smoke test assertion: `assert len( AGENTIC_AGENTS ) == 6` (was 5).

**A.3 — Update unit tests**

File: `src/tests/unit/test_presentation_generator_job.py`

Add tests for:
- `--user-visible-args` flag returns correct JSON list
- Registry entry exists and has required keys
- Factory creates job correctly from expeditor-style args_dict

---

### Part B: Content Ingestion (Phase 1: Ingest)

**B.1 — Implement `_ingest_async()` in orchestrator**

File: `src/cosa/agents/presentation_generator/orchestrator.py`

Replace stub with real implementation following `PodcastOrchestratorAgent._load_research_async()` pattern:

1. Resolve source path (absolute vs relative using `cu.get_project_root()`)
2. Read file in thread pool: `content = await asyncio.to_thread( _read_file, path )`
3. Detect format: check for markdown indicators (headings `#`, code fences, bullet lists) vs plain text
4. Extract raw sections:
   - **Markdown**: Split by `## ` / `### ` heading boundaries → list of `(heading, body)` tuples
   - **Plain text**: Split by double newlines → paragraph blocks
5. Store results in `self._presentation_state`:
   - `"source_content"`: raw full text
   - `"source_format"`: `"markdown"` or `"plaintext"`
   - `"raw_sections"`: list of extracted sections
   - `"word_count"`: total word count (used for slide count heuristic)
6. Send progress notification: `notify( "Document ingested: {word_count} words, {section_count} sections" )`
7. Return content string or None on error

Error handling: `FileNotFoundError` → notify user + return None → orchestrator transitions to FAILED.

**B.2 — Add helper function `_parse_markdown_sections()`**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (private method)

Regex-based markdown section parser:
- Split on heading patterns (`^#{1,3} `)
- Preserve heading level for arc position hinting (H1 = major topic, H2 = subtopic, H3 = detail)
- Handle edge cases: no headings (treat as single section), empty sections, frontmatter (skip YAML blocks)

---

### Part C: Narrative Analysis (Phase 2: Analyze)

**C.1 — Create `api_client.py`**

File: `src/cosa/agents/presentation_generator/api_client.py` (new, ~200 lines)

Follow `PodcastAPIClient` pattern (`src/cosa/agents/podcast_generator/api_client.py`):

- Class `PresentationAPIClient` with:
  - Constructor: `config`, `api_key=None`, `debug=False`, `verbose=False`
  - Firewalled API key resolution: param > `ANTHROPIC_API_KEY_FIREWALLED` env > `src/conf/keys/anthropic-api-key-firewalled` file
  - Lazy `AsyncAnthropic` client initialization
  - `APIResponse` dataclass (content, model, input_tokens, output_tokens, stop_reason)
  - `CostEstimate` dataclass with Opus pricing constants
- Methods:
  - `async call_for_analysis( system_prompt, user_message, max_tokens=4096, temp=0.7 ) → APIResponse`
  - `async call_for_outline( system_prompt, user_message, max_tokens=4096, temp=0.7 ) → APIResponse` (stub for Phase 4)
  - `async call_for_elaboration( system_prompt, user_message, max_tokens=8192, temp=0.7 ) → APIResponse` (stub for Phase 4)
  - `async _call_api( model, system_prompt, user_message, call_type, max_tokens, temp ) → APIResponse`
  - `async _call_with_retry( kwargs, max_retries=3, initial_delay=1.0 )` — exponential backoff on RateLimitError / 5xx
  - `get_cost_summary() → str`
  - `async close()`

**C.2 — Create `prompts/narrative.py`**

File: `src/cosa/agents/presentation_generator/prompts/narrative.py` (new, ~250 lines)

Contents:
- `NARRATIVE_ANALYSIS_SYSTEM_PROMPT` — System prompt constant instructing Claude to:
  - Analyze document structure and identify the argumentative spine
  - Classify each section into arc positions: `setup`, `argument`, `evidence`, `transition`, `conclusion`, `cta`
  - Propose slide count per section based on content density
  - Return structured JSON response
- `get_narrative_analysis_prompt( source_content, raw_sections, target_duration, slides_per_minute, audience )` — Builds user message with:
  - Full source content (truncated to 30k chars if needed)
  - Pre-parsed section boundaries from Phase 1
  - Target slide budget: `int( target_duration * slides_per_minute )`
  - Audience level for complexity calibration
- `parse_analysis_response( response_content ) → List[dict]` — Parse Claude's JSON response:
  - Handle markdown code block wrapping (` ```json ... ``` `)
  - Extract list of section objects with: `heading`, `content_summary`, `arc_position`, `proposed_slide_count`, `key_points`
  - Fallback: return minimal structure on parse error
- `AUDIENCE_COMPLEXITY_GUIDELINES` — Dict mapping audience levels to analysis depth instructions

**C.3 — Implement `_analyze_async()` in orchestrator**

File: `src/cosa/agents/presentation_generator/orchestrator.py`

Replace stub with real implementation:

1. Build prompt: `get_narrative_analysis_prompt( source_content, raw_sections, config.target_duration_minutes, config.slides_per_minute, config.audience )`
2. Call API: `response = await self.api_client.call_for_analysis( NARRATIVE_ANALYSIS_SYSTEM_PROMPT, prompt )`
3. Increment metrics: `self.metrics[ "api_calls" ] += 1`
4. Parse response: `sections = parse_analysis_response( response.content )`
5. Convert to typed models: `List[ NarrativeSection ]` (Pydantic models from `state.py`)
6. Calculate total proposed slides and compare against budget
7. Store in state: `self._presentation_state[ "narrative_sections" ] = sections`
8. Send notification: `notify( "Narrative analysis complete: {n} sections, {slide_count} proposed slides" )`
9. Error handling: try/except → log + return empty list → orchestrator handles gracefully

**C.4 — Add lazy `api_client` property to orchestrator**

File: `src/cosa/agents/presentation_generator/orchestrator.py`

```python
@property
def api_client( self ):
    if self._api_client is None:
        self._api_client = PresentationAPIClient(
            config=self.config, debug=self.debug, verbose=self.verbose
        )
    return self._api_client
```

---

### Part D: Gate 1 — Narrative Arc Review

**D.1 — Implement `_gate_1_narrative_review()`**

File: `src/cosa/agents/presentation_generator/orchestrator.py`

Replace auto-approve stub with voice I/O interaction:

1. Build summary string: numbered list of sections with arc positions and proposed slide counts
2. Present via `ask_yes_no()` or `ask_multiple_choice()` with options:
   - **Approve** — proceed to outline generation
   - **Revise** — re-run analysis with user feedback (decrement `max_revisions`)
   - **Cancel** — abort job
3. If "Revise": collect feedback via `converse()`, append to prompt, re-call `_analyze_async()`
4. If "Cancel": transition to STOPPED, notify user
5. Track revision count against `config.max_revisions`

---

### Part E: Unit Tests

**E.1 — New test file for API client**

File: `src/tests/unit/test_presentation_api_client.py` (new)

- Test `PresentationAPIClient` construction and config
- Test cost tracking accumulation
- Test `_call_with_retry` exponential backoff (mock httpx)
- Test API key resolution priority chain

**E.2 — New test file for prompts**

File: `src/tests/unit/test_presentation_prompts.py` (new)

- Test `parse_analysis_response()` with valid JSON
- Test `parse_analysis_response()` with markdown-wrapped JSON
- Test `parse_analysis_response()` with malformed input (graceful fallback)
- Test `get_narrative_analysis_prompt()` includes all required context
- Test audience-specific guidelines injection

**E.3 — Extend existing test file**

File: `src/tests/unit/test_presentation_generator_job.py` (modify)

- Test `_parse_markdown_sections()` with real markdown
- Test `_parse_markdown_sections()` with plain text fallback
- Test `_parse_markdown_sections()` with edge cases (no headings, empty doc, frontmatter)
- Test expeditor `--user-visible-args` protocol
- Test registry entry completeness

---

## Files Summary

| File | Action | Lines (est) |
|------|--------|-------------|
| `src/cosa/agents/presentation_generator/__main__.py` | Rewrite | ~120 |
| `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` | Modify | +30 |
| `src/cosa/agents/presentation_generator/api_client.py` | Create | ~200 |
| `src/cosa/agents/presentation_generator/prompts/narrative.py` | Create | ~250 |
| `src/cosa/agents/presentation_generator/orchestrator.py` | Modify | ~150 added |
| `src/tests/unit/test_presentation_api_client.py` | Create | ~100 |
| `src/tests/unit/test_presentation_prompts.py` | Create | ~120 |
| `src/tests/unit/test_presentation_generator_job.py` | Modify | +40 |

---

## Implementation Order

0. **Serialize plan** to `src/rnd/2026.03.14-presentation-generator/04-phase-3-implementation-plan.md` + update `00-index.md` (documentation-first protocol — this step)
1. **A.1-A.3**: Expeditor integration (CLI + registry + tests) — enables voice path
2. **B.1-B.2**: Ingest implementation — prerequisite for analyze
3. **C.1**: API client — needed before any LLM calls
4. **C.2**: Narrative prompts — defines what we ask Claude
5. **C.3-C.4**: Analyze implementation — wires it all together
6. **D.1**: Gate 1 — human-in-the-loop checkpoint
7. **E.1-E.3**: Tests throughout (written alongside each part)

---

## Verification

1. `python -m cosa.agents.presentation_generator --user-visible-args` → prints `["source", "target_duration_minutes", "audience", "audience_context", "theme"]`
2. `python -m cosa.agents.runtime_argument_expeditor.agent_registry` → smoke test passes (6 agents)
3. Feed a markdown document through Phases 1-2 via dry-run REST submission
4. Verify narrative sections are correctly classified into arc positions
5. Verify proposed slide count falls within the 1-slide-per-minute guideline
6. Gate 1 presents sensible arc mapping via voice I/O
7. All existing unit tests still pass (no regressions)
8. New unit tests pass: API client, prompts, ingest parsing, expeditor protocol

---

## Resolved Design Decisions

1. **Source document search paths**: `fuzzy_file_match` will search three locations: `io/deep-research/{user}/` (DR output), `src/rnd/` (planning docs), and `src/docs/` (project documentation).
2. **Audience context**: Yes — add `audience_context` free-text field matching the DR and Podcast Generator pattern. Adds one more arg to CLI, registry, and factory.

## Session TODO

- [ ] Update `~/.claude/skills/agentic-voice-workflow/SKILL.md` to document the Runtime Argument Expeditor and its role in the voice-driven agent pipeline.
