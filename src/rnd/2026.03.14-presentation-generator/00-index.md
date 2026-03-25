# Presentation Generator Agent — R&D Documentation

**Created**: 2026-03-14
**Status**: Planning & Design Complete, Implementation Pending
**Agent Type**: AgenticJobBase (Bounded, Single Orchestrator)
**Job Prefix**: `pr` (presentation)
**Pattern**: Follows Podcast Generator architecture (job + orchestrator + config)

## Document Index

| # | Document | Purpose | Status |
|---|----------|---------|--------|
| 01 | [Strategy & Design](01-strategy-and-design.md) | Presentation design theory, narrative arc decomposition, structural decisions, theme/visual architecture | Complete |
| 02 | [Implementation Plan](02-implementation-plan.md) | Phase-by-phase implementation breakdown with tasks, file lists, dependencies | Complete |
| 03 | [Implementation Tracking](03-implementation-tracking.md) | Phase/task completion tracking with checkboxes | Active |
| 04 | [Phase 3 Implementation Plan](04-phase-3-implementation-plan.md) | Expeditor integration + Ingest + Narrative Analysis + Gate 1 | Complete |
| 05 | [Phase 4 Implementation Plan](05-phase-4-implementation-plan.md) | Outline & Elaborate + fuzzy_file_match config | Complete |
| 06 | [Phase 4-5 Verification Plan](06-phase-4-5-verification-plan.md) | Test & verify strategy: smoke → dry-run → UI → live E2E | Active |

## Future Documents (Added as Work Progresses)

| # | Document | Purpose | Status |
|---|----------|---------|--------|
| 06 | Theme Template Spec | Theme YAML schema, examples, default theme | Planned |
| 07 | Visual Renderer Protocol | Renderer interface specification, registry design | Planned |
| 08 | Prompt Engineering | LLM prompts for narrative extraction, title generation, elaboration | Planned |
| 09 | Lessons Learned | Post-implementation notes, design pivots, gotchas | Planned |

## Architecture Summary

```mermaid
graph LR
    A[Source Document] --> B[Phase 1: Ingest]
    B --> C[Phase 2: Analyze]
    C -->|Gate 1| D[Phase 3: Outline]
    D -->|Gate 2| E[Phase 4: Elaborate]
    E -->|Gate 3| F[Phase 5: Serialize]
    F --> G[YAML Intermediate File]
    G --> H[Phase 6: Render Text]
    H --> I[Phase 7: Render Visuals]
    I -->|Gate 4| J[Phase 8: Deliver]
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Single orchestrator (like Podcast Generator) | Sequential phases, no parallelizable subtasks |
| Intermediate format | YAML | Structured, machine-parseable, human-editable |
| Output format | Marp Markdown (MVP) | Markdown syntax, exports to PDF/PPTX/HTML |
| Visual rendering | Mermaid (MVP), pluggable registry (future) | LLM generates Mermaid from descriptions |
| Chaining | Deep Research → Presentation bridge | Same pattern as DR → Podcast |
| MVP scope | Content generation first (Phases 1-5), rendering second (Phases 6-8) | Deliver reviewable YAML before rendering |

## Related Files (Post-Implementation)

```
src/cosa/agents/presentation_generator/
    job.py                  # PresentationGeneratorJob (AgenticJobBase)
    orchestrator.py         # PresentationOrchestratorAgent (async multi-phase)
    config.py               # PresentationConfig (dataclass from INI)
    state.py                # OrchestratorState, SlideModel, PresentationModel
    voice_io.py             # Voice-first I/O wrapper
    cosa_interface.py       # COSA notification dispatcher
    api_client.py           # Claude SDK wrapper for content generation
    marp_renderer.py        # YAML → Marp Markdown renderer
    visual_registry.py      # Pluggable visual renderer registry
    renderers/
        mermaid.py          # MermaidRenderer
        placeholder.py      # PlaceholderRenderer (fallback)
    templates/
        themes/
            default.yaml    # Default theme
    prompts/
        narrative.py        # Narrative extraction prompts
        elaboration.py      # Content generation prompts
    __main__.py             # CLI entry point
```
