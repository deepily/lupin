---
capability: presentation-generation
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.presentation_generator.job.PresentationGeneratorJob@4b5a46a0ef
  - cosa.agents.presentation_generator.job.resolve_source_path@f8ce01e248
  - cosa.agents.presentation_generator.job.source_path_is_inside_the_project@8c961318e6
  - cosa.agents.presentation_generator.orchestrator.PresentationOrchestratorAgent@da1062acda
  - cosa.agents.presentation_generator.orchestrator.PresentationOrchestratorAgent.do_all_async@3a74dac461
  - cosa.agents.presentation_generator.orchestrator.PresentationOrchestratorAgent.render_from_yaml_async@ec3c03c31d
  - cosa.agents.presentation_generator.orchestrator.VoiceGateNotAnsweredError@610a429f17
  - cosa.agents.presentation_generator.state.OrchestratorState@73d194de81
  - cosa.agents.presentation_generator.state.PresentationModel@97c44dc98c
  - cosa.agents.presentation_generator.config.PresentationConfig@454dda8807
  - cosa.agents.presentation_generator.deck_verdict.verify_presentation_deck@184b66fe08
---
# Presentation generation

`PresentationGeneratorJob` turns a source document into a slide deck: a YAML file, Marp Markdown and a `.pptx`, written under `io/presentations/{user}`. The job runs `PresentationOrchestratorAgent`; the model calls are in [[generator-sdk-clients]], the visuals in [[presentation-visual-renderers]], the job lifecycle in [[agentic-job-contract]].

## What it does
- Phases, in order: ingest, analyze narrative, outline, elaborate, serialize to YAML, render Marp text, render visuals, deliver, then a `.pptx` export. The state is an `OrchestratorState`, readable with `get_state()`; `request_stop()` stops at the next phase boundary.
- Four review gates (narrative arc, outline, content, rendered output) ask the user by voice ([[agent-voice-io]]). Gates 1 to 3 offer "Revise", which re-runs the analysis, outline or elaboration with the user's feedback, up to `max_revisions` (3) each; gate 4 offers Approve or Cancel.
- `render_only` runs `render_from_yaml_async` on an existing YAML: no generation and no gates 1 to 3; gate 4 still asks, except that it auto-approves a deck with no rendered visuals.
- The job fills `artifacts` with `yaml_path`, `marp_path`, `pptx_path`, `presentation_id`, `slide_count`, `cost_summary`, `abstract` and `report_path`; it ends by rewriting `yaml_path` and `pptx_path` as `io/`-relative paths while `marp_path` stays absolute. `verify_presentation_deck( path )` reads a real `.pptx` and is truthy only if it holds slides and text.

## Invariants
- The job refuses a `source_path` that resolves outside the project root (`ValueError` in `__init__`). A leading slash means project-relative, so `/etc/passwd` becomes `<root>/etc/passwd`.
- A gate that hears nothing within `review_timeout_seconds` (600 by default), or whose ask cannot be delivered or fails, continues as "Approve": `present_choices` returns the declared default, logged as such. An answer payload with no answer for the gate's header, or any other exception inside the gate, raises `VoiceGateNotAnsweredError` and fails the job.
- An empty result from analyze, outline or elaborate raises `ValueError` and fails the job.
- Above `LARGE_DECK_CHUNK_THRESHOLD` (20) slides, elaboration runs in batches: on 2026-08-05 decks of 40 and 60 slides came back as valid JSON with zero slides.
- The `.pptx` export is not fatal: if it fails or `pptx_export_enabled` is off, the YAML and Marp files are still delivered.
- `PresentationGeneratorJob.do_all` (the job is an `AgenticJobBase`) sets `FAILED` and then re-raises, so the agentic pool's `Future` captures the error.

## How to extend
- A new phase gets an `OrchestratorState` value, a step in `do_all_async` with a stop check after it, and an empty-result guard if it produces content.

## Don't
- Don't turn a missing gate answer into approval; read gates with `_read_gate_answer`.
- Don't use the orchestrator's `offline_mode` as a dry run: it writes a real YAML file, and every gate auto-approves in it. The job's `dry_run` is the one that makes no calls.
