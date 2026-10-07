---
capability: research-chained-pipelines
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob@682eb48c2f
  - cosa.agents.deep_research_to_presentation.job.DeepResearchToPresentationJob@ea4f779747
  - cosa.agents.deep_research_to_podcast.agent.DeepResearchToPodcastAgent@86a17644b5
  - cosa.agents.deep_research_to_presentation.agent.DeepResearchToPresentationAgent@062895fbcb
  - cosa.agents.deep_research_to_podcast.state.ChainedResult@c07a929e14
  - cosa.agents.deep_research_to_presentation.state.ChainedResult@5b5f829ef8
  - cosa.agents.deep_research_to_podcast.state.PipelineState@4b3355bdf0
---
# Research chained pipelines

Two queue jobs run [[deep-research]] and then hand its saved report to [[podcast-generation]] or [[presentation-generation]], as one job. `DeepResearchToPodcastJob` and `DeepResearchToPresentationJob` are `AgenticJobBase` subclasses (see [[agentic-job-contract]]); each builds a chained agent and runs it.

## What it does
- The agent runs research first, then passes the saved report path to the second generator: as `research_doc_path` for the podcast, as `source_path` for the presentation.
- The agent skips the second step if research was cancelled (state `CANCELLED`) or returned no `report_path` (state `FAILED`).
- Any exception after the voice setup ends the run with state `FAILED` and `error` set; the agent returns the result instead of raising. The job then raises on `FAILED`, so the queue records a failure. A cancelled run returns a text answer and does not raise.
- `ChainedResult` carries both legs' cost (`dr_cost`, `pg_cost`) and `total_cost`, their sum. `is_partial()` is true when the state is `DEEP_RESEARCH_DONE` or `FAILED`, `research_path` is set and the final artifact is `None` (`audio_path` for the podcast, `yaml_path` for the presentation). A cancelled run is not partial.
- The agent never sets `PODCAST_GEN_DONE` or `PRESENTATION_GEN_DONE`; a finished run ends at `COMPLETED`.

## How to call it
- Submit through `POST /api/v2/submit` with command `agent router go to research to podcast` or `agent router go to research to presentation`. The factory builds the job from `args`; job ids start `rp-` (podcast) and `rx-` (presentation).
- `dry_run` sends only breadcrumb notifications and mock paths; it builds no agent and reports zero cost.
- `source_document` (a list of absolute paths, or one string; `/api/v2/submit` takes it as `<scope>/<path>`) reaches only the research prompt. It is kept out of the session-name gist, the notifications and the saved report's query field.
- `budget` limits research only. A `BudgetExceededError` is re-raised as a plain exception, which ends the run `FAILED`.
- On success the job stores `artifacts["abstract"]`, a card with links to the report and the generated files.

## What differs between the two
- Podcast options: `target_languages` (default `["en"]`) and `max_segments`. The queue factory passes `languages` but not `max_segments`, so `max_segments` is reachable only by constructing the job or agent directly.
- Presentation options: `target_duration_minutes`, `target_slide_count`, `theme`. The presentation job also takes `lead_model`, which sets the research leg's lead model only; the podcast job does not pass one (its agent accepts it).
- The presentation leg builds its config from the INI file and then overrides it with these options, plus `audience`. The podcast leg uses a default `PodcastConfig()`.
- Results: the podcast has `audio_path` and `script_path`, with per-language maps in `pg_artifacts`; the presentation has `yaml_path`, `marp_path` and `slide_count`.

## When not to use it
- To run just one stage, use [[deep-research]], [[podcast-generation]] or [[presentation-generation]] directly.
- To turn an existing document into a podcast or deck, use the generator on that document; this chain always runs research first.
