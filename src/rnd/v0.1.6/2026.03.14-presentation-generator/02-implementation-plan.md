# Presentation Generator Agent — Implementation Plan

**Created**: 2026-03-14
**Pattern**: Podcast Generator (job + orchestrator + config + voice I/O)
**Reference**: [CJ Flow Bounded Job Packaging Guide](../2026.02.12-cj-flow-bounded-job-packaging-guide.md)

---

## MVP Phasing

| MVP | Scope | Deliverable |
|-----|-------|-------------|
| **MVP-1** | Content Generation (Phases 1-5) | Structured YAML file from source document |
| **MVP-2** | Text Rendering (Phase 6) | Marp Markdown file from YAML |
| **MVP-3** | Visual Rendering (Phase 7) | Slide deck with generated Mermaid diagrams |
| **Future** | AI Visual Generators | NanoBanana, Google image/video renderers |

---

## Phase 1: Foundation — Job, Config, Voice I/O, CJ Flow Packaging

**Goal**: Skeleton job that can be submitted, queued, and executed (dry-run only).

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 1.1 | Create agent directory structure | `src/cosa/agents/presentation_generator/` | `__init__.py`, subdirs |
| 1.2 | Implement `PresentationConfig` dataclass | `config.py` | From INI keys, mirrors PodcastConfig pattern. Fields: `content_model`, `target_duration_minutes`, `slides_per_minute`, `title_style` (assertion/topic), `max_revisions`, `output_dir_template`, `audience`. `from_config(config_mgr)` class method. |
| 1.3 | Implement `PresentationGeneratorJob` | `job.py` | `JOB_TYPE="presentation"`, `JOB_PREFIX="pr"`. Constructor: `source_path`, `user_id`, `user_email`, `session_id`, `target_duration_minutes`, `audience`, `theme`, `dry_run`. Implement `_execute()` and `_execute_dry_run()`. Inline `quick_smoke_test()`. |
| 1.4 | Create `cosa_interface.py` | `cosa_interface.py` | `AGENT_TYPE="presentation.gen"`, dispatcher, async wrappers. Follow Podcast Generator pattern exactly. |
| 1.5 | Create `voice_io.py` wrapper | `voice_io.py` | Thin re-export wrapper with `reconfigure()`. |
| 1.6 | Add INI config keys | `lupin-app.ini`, `lupin-app-splainer.ini` | `presentation generator content model`, `presentation generator target duration minutes`, `presentation generator slides per minute`, `presentation generator title style`, `presentation generator max revisions`, `presentation generator default theme`, `presentation generator templates path` |
| 1.7 | Add factory registration | `agentic_job_factory.py` | `elif command == "agent router go to presentation generator"` |
| 1.8 | Add REST router | `routers/presentation_generator.py` | `/api/presentation/queue/submit` endpoint. Pydantic request/response models. |
| 1.9 | Register router in main.py | `main.py` | `app.include_router( presentation_generator_router )` |
| 1.10 | Write smoke test | `job.py` (`__main__` block) | Module import, job instantiation, ID format, protocol compliance |
| 1.11 | Write unit tests | `src/tests/unit/test_presentation_generator_job.py` | Job construction, dry-run execution, config loading |

### Verification
- `python -m cosa.agents.presentation_generator.job` passes
- Dry-run submission via REST endpoint queues and completes
- Unit tests pass

---

## Phase 2: State Models & Orchestrator Skeleton

**Goal**: Define data models and orchestrator with phase state machine (no LLM calls yet).

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 2.1 | Define `OrchestratorState` enum | `state.py` | `INITIALIZED`, `INGESTING`, `ANALYZING`, `OUTLINING`, `ELABORATING`, `SERIALIZING`, `RENDERING_TEXT`, `RENDERING_VISUALS`, `DELIVERING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| 2.2 | Define `SlideModel` (Pydantic) | `state.py` | `number`, `arc_position`, `type`, `title`, `subtitle`, `visual_type`, `visual_description`, `content_bullets`, `presenter_notes` (nested model with `transition`, `talking_points`, `timing_seconds`, `emphasis`) |
| 2.3 | Define `PresentationModel` (Pydantic) | `state.py` | `title`, `speaker`, `date`, `duration_minutes`, `source_document`, `total_slides`, `slides: List[SlideModel]`, `theme`, `theme_overrides` |
| 2.4 | Define `NarrativeSection` model | `state.py` | `heading`, `content`, `arc_position` (enum: setup, argument, evidence, transition, conclusion, cta), `proposed_slides` |
| 2.5 | Implement `PresentationOrchestratorAgent` skeleton | `orchestrator.py` | Constructor, state machine, `do_all_async()` with phase dispatch. Stub each phase method. Follow PodcastOrchestratorAgent pattern. |
| 2.6 | Wire orchestrator into job's `_execute()` | `job.py` | Create config, create orchestrator, await `do_all_async()`, extract results |
| 2.7 | Write unit tests for state models | `test_presentation_generator_job.py` | SlideModel, PresentationModel, NarrativeSection validation |

### Verification
- State models validate with sample data
- Orchestrator progresses through states (stub phases)
- Dry-run with orchestrator wired in still completes

---

## Phase 3: Content Generation — Ingest & Analyze (Phases 1-2)

**Goal**: Read source document and extract narrative structure using Claude.

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 3.1 | Implement `api_client.py` | `api_client.py` | Claude SDK wrapper for content generation. `analyze_narrative()`, `generate_outline()`, `elaborate_slides()` methods. Follow PodcastAPIClient pattern. |
| 3.2 | Implement Phase 1: Ingest | `orchestrator.py` | Read document, detect format (markdown/plain text), extract raw sections by headings/paragraphs. Store in `_presentation_state["source_content"]`. |
| 3.3 | Write narrative extraction prompts | `prompts/narrative.py` | System prompt for classifying document sections into arc positions. Include section classification taxonomy. |
| 3.4 | Implement Phase 2: Analyze | `orchestrator.py` | Call Claude with source content + narrative prompt. Parse response into `List[NarrativeSection]`. Calculate proposed slide count based on `slides_per_minute * target_duration`. |
| 3.5 | Implement Gate 1 checkpoint | `orchestrator.py` | Present narrative arc to user via `voice_io.present_choices()`. Show sections, arc positions, proposed slide count. Allow approve/revise/cancel. |
| 3.6 | Write unit tests | `test_presentation_generator_job.py` | Ingest file reading, narrative parsing, gate interaction |

### Verification
- Feed a markdown document through Phases 1-2
- Narrative sections correctly classified
- Gate 1 presents sensible arc mapping

---

## Phase 4: Content Generation — Outline & Elaborate (Phases 3-4)

**Goal**: Generate slide titles + visual types, then full slide content with notes.

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 4.1 | Write outline generation prompt | `prompts/narrative.py` | Given narrative sections + slide budget, generate slide titles (assertion-style) and visual type per slide. |
| 4.2 | Implement Phase 3: Outline | `orchestrator.py` | Call Claude with narrative sections. Parse into list of `(title, visual_type)` tuples. Apply structural formula (opening + body + closing). |
| 4.3 | Implement Gate 2 checkpoint | `orchestrator.py` | Present numbered slide titles + visual types. The "story spine" review. Allow approve/revise/cancel. |
| 4.4 | Write elaboration prompts | `prompts/elaboration.py` | Given outline + source content, generate full `SlideModel` per slide: content bullets, presenter notes (transition, talking points, timing, emphasis), visual description. |
| 4.5 | Implement Phase 4: Elaborate | `orchestrator.py` | Call Claude with outline + source. Parse into `List[SlideModel]`. |
| 4.6 | Implement Gate 3 checkpoint | `orchestrator.py` | Present full structured content for review. Show slide-by-slide summary. Allow approve/revise/cancel. |
| 4.7 | Write unit tests | `test_presentation_generator_job.py` | Outline generation, elaboration, gate interactions |

### Verification
- Slide titles read as coherent story
- Visual types alternate appropriately (not 5 text-only in a row)
- Presenter notes contain all required fields
- Gate checkpoints work correctly

---

## Phase 5: Content Generation — Serialize (Phase 5)

**Goal**: Write final structured YAML file.

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 5.1 | Implement Phase 5: Serialize | `orchestrator.py` | Build `PresentationModel` from elaborated slides. Write to YAML file using `yaml.dump()`. Path: `io/presentations/{user}/{timestamp}-{topic}.yaml` |
| 5.2 | Add YAML serialization helpers | `state.py` | `PresentationModel.to_yaml()`, `PresentationModel.from_yaml()` methods |
| 5.3 | Wire final results back to job | `job.py` | Extract `yaml_path` from orchestrator. Set `answer_conversational` with summary + path. Build `cost_summary`. |
| 5.4 | End-to-end dry-run test | Manual | Submit dry-run job, verify YAML output is valid and complete |
| 5.5 | Write unit tests | `test_presentation_generator_job.py` | YAML serialization/deserialization round-trip |

### Verification
- YAML file is valid and contains all fields
- `PresentationModel.from_yaml()` round-trips correctly
- Dry-run job completes with YAML path in answer

---

## Phase 6: Text Rendering — Marp Markdown (Phase 6)

**Goal**: Transform YAML into Marp Markdown slide deck.

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 6.1 | Implement `marp_renderer.py` | `marp_renderer.py` | `render(presentation: PresentationModel, theme: ThemeConfig) -> str`. Generate Marp-compatible markdown with `---` slide separators, presenter notes in `<!-- -->` blocks, theme directives in frontmatter. |
| 6.2 | Implement theme loader | `marp_renderer.py` | Load theme YAML from templates directory, apply color/font/layout settings to Marp CSS directives. |
| 6.3 | Create default theme | `templates/themes/default.yaml` | Clean, minimal theme with sensible defaults |
| 6.4 | Implement Phase 6 in orchestrator | `orchestrator.py` | Load YAML, create MarpRenderer, generate Marp markdown, save to `.md` file alongside YAML. |
| 6.5 | Add INI config for Marp | `lupin-app.ini` | `presentation generator marp cli path` (optional, for PDF/PPTX export) |
| 6.6 | Write unit tests | `test_presentation_generator_job.py` | Marp output structure, theme application, presenter notes format |

### Verification
- Marp Markdown renders correctly in Marp preview
- Theme settings apply (colors, fonts, layout)
- Presenter notes visible in Marp presenter view

---

## Phase 7: Visual Rendering — Mermaid + Registry (Phase 7)

**Goal**: Generate Mermaid diagrams from visual descriptions, plug into slide deck.

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 7.1 | Implement `VisualRenderer` ABC | `visual_registry.py` | Abstract base class with `SUPPORTED_TYPES` and `render()` method |
| 7.2 | Implement `MermaidRenderer` | `renderers/mermaid.py` | Call Claude to generate Mermaid syntax from `visual_description`. Validate syntax. Optionally call mermaid-cli for SVG. |
| 7.3 | Implement `PlaceholderRenderer` | `renderers/placeholder.py` | Generate `[TODO: Generate {visual_type} -- {description}]` text |
| 7.4 | Implement visual renderer registry | `visual_registry.py` | Dict mapping `visual_type -> VisualRenderer`. Load from INI config. Fallback to PlaceholderRenderer. |
| 7.5 | Implement Phase 7 in orchestrator | `orchestrator.py` | For each slide with `visual_type != "text_only"`, call appropriate renderer. Embed result into Marp markdown. |
| 7.6 | Implement Gate 4 checkpoint | `orchestrator.py` | Present final rendered output for review. Allow approve/revise. |
| 7.7 | Write unit tests | `test_presentation_generator_job.py` | Registry routing, Mermaid generation, placeholder fallback |

### Verification
- Mermaid diagrams generate from natural-language descriptions
- Registry routes types to correct renderers
- Placeholder renderer produces clear TODO markers
- Gate 4 presents final output for approval

---

## Phase 8: Delivery & Chaining (Phase 8)

**Goal**: Save final artifacts, build Deep Research -> Presentation bridge.

### Tasks

| # | Task | Files | Notes |
|---|------|-------|-------|
| 8.1 | Implement Phase 8: Deliver | `orchestrator.py` | Save all artifacts (YAML, Marp MD, generated visuals). Send completion notification with paths and cost summary. |
| 8.2 | Build `deep_research_to_presentation/` bridge | `src/cosa/agents/deep_research_to_presentation/` | `job.py`, `agent.py`, `state.py`. Follow `deep_research_to_podcast` pattern exactly. |
| 8.3 | Add factory registration for chained job | `agentic_job_factory.py` | `"agent router go to deep research to presentation"` |
| 8.4 | Add REST router for chained job | `routers/deep_research_to_presentation.py` | `/api/research-to-presentation/queue/submit` |
| 8.5 | End-to-end integration test | Manual | Full pipeline: source doc -> YAML -> Marp -> visuals -> delivery |
| 8.6 | Write comprehensive unit tests | Multiple test files | Full coverage of job, orchestrator, renderers, chaining |

### Verification
- Full pipeline produces complete slide deck
- Chained DR -> Presentation works end-to-end
- Cost tracking aggregates correctly
- All artifacts saved to correct paths

---

## File Inventory

### New Files (Phase 1-8)

```
src/cosa/agents/presentation_generator/
    __init__.py
    job.py                          # Phase 1
    config.py                       # Phase 1
    cosa_interface.py               # Phase 1
    voice_io.py                     # Phase 1
    state.py                        # Phase 2
    orchestrator.py                 # Phase 2-7
    api_client.py                   # Phase 3
    marp_renderer.py                # Phase 6
    visual_registry.py              # Phase 7
    renderers/
        __init__.py                 # Phase 7
        mermaid.py                  # Phase 7
        placeholder.py              # Phase 7
    templates/
        themes/
            default.yaml            # Phase 6
    prompts/
        __init__.py                 # Phase 3
        narrative.py                # Phase 3
        elaboration.py              # Phase 4
    __main__.py                     # Phase 1

src/cosa/agents/deep_research_to_presentation/
    __init__.py                     # Phase 8
    job.py                          # Phase 8
    agent.py                        # Phase 8
    state.py                        # Phase 8
    __main__.py                     # Phase 8

src/cosa/rest/routers/
    presentation_generator.py       # Phase 1
    deep_research_to_presentation.py # Phase 8

src/tests/unit/
    test_presentation_generator_job.py  # Phase 1+
```

### Modified Files

```
src/conf/lupin-app.ini              # Phase 1 (config keys)
src/conf/lupin-app-splainer.ini     # Phase 1 (config explanations)
src/cosa/rest/agentic_job_factory.py # Phase 1, Phase 8 (factory registration)
src/fastapi_app/main.py             # Phase 1, Phase 8 (router registration)
src/rnd/README.md                   # Phase 1 (R&D index update)
```

---

## Dependencies

| Dependency | Purpose | Phase | Install |
|-----------|---------|-------|---------|
| `pyyaml` | YAML serialization | Phase 5 | Already in requirements |
| `marp-cli` | Marp -> PDF/PPTX/HTML export | Phase 6 (optional) | `npm install -g @marp-team/marp-cli` |
| `mermaid-cli` | Mermaid -> SVG rendering | Phase 7 (optional) | `npm install -g @mermaid-js/mermaid-cli` |

**Note**: marp-cli and mermaid-cli are optional for MVP. The pipeline produces valid Marp Markdown that can be rendered externally. These tools enable automated export.
