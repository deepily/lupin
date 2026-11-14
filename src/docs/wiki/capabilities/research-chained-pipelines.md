---
capability: research-chained-pipelines
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob@07297bd4b4
  - cosa.agents.deep_research_to_presentation.job.DeepResearchToPresentationJob@1b18bbe364
  - cosa.agents.deep_research_to_podcast.agent.DeepResearchToPodcastAgent@bb8f62612b
  - cosa.agents.deep_research_to_presentation.agent.DeepResearchToPresentationAgent@16f1a98147
  - cosa.agents.deep_research_to_podcast.state.ChainedResult@69c6756c1a
  - cosa.agents.deep_research_to_presentation.state.ChainedResult@5d8d002f2d
  - cosa.agents.deep_research_to_podcast.state.PipelineState@4b3355bdf0
  - cosa.agents.chained_pipeline_state.ChainedResultMixin@043deeda1d
  - cosa.agents.chained_pipeline_state.ChainedDeepResearchAgent@78d23d01c0
  - cosa.agents.chained_pipeline_state.skipped_topic_names@fef01aebad
---
# Research chained pipelines

Two queue jobs run [[deep-research]] and then hand its saved report to [[podcast-generation]] or [[presentation-generation]], as one job. `DeepResearchToPodcastJob` and `DeepResearchToPresentationJob` are `AgenticJobBase` subclasses (see [[agentic-job-contract]]); each builds a chained agent and runs it.

## What it does
- The agent runs research first, then passes the saved report path to the second generator: as `research_doc_path` for the podcast, as `source_path` for the presentation. Both chains set `TARGET_USER` and the per-task dispatch context, so concurrent jobs do not cross notifications ([[agent-voice-io]]).
- The agent skips the second step if research was cancelled (state `CANCELLED`) or returned no `report_path` (state `FAILED`). Topics that research skipped (read by `skipped_topic_names`, which the podcast agent and `AgenticJobBase` both call) show as a "Skipped topics" line on the cards ([[deep-research]]). A finished run ends at `COMPLETED`; the `*_GEN_DONE` states are never set.
- Any exception after the voice setup ends the run with state `FAILED` and `error` set; the agent returns the result instead of raising. The job then raises on `FAILED`, so the queue records a failure. A cancelled run returns a text answer and does not raise.
- `ChainedResult` carries both legs' cost (`dr_cost`, `pg_cost`) and `total_cost`, their sum. `is_partial()`, shared through `ChainedResultMixin`, is true when the state is `DEEP_RESEARCH_DONE` or `FAILED`, `research_path` is set and the final artifact is `None`. The final artifact is `audio_path` for the podcast and `yaml_path` for the presentation. A cancelled run is not partial.

## How to call it
- Submit through `POST /api/v2/submit` with command `agent router go to research to podcast` or `agent router go to research to presentation`. The factory builds the job from `args`; job ids start `rp-` (podcast) and `rx-` (presentation).
- `dry_run` sends only breadcrumb notifications and mock paths; it builds no agent and reports zero cost. The jobs share one frame, `_run_chained_pipeline` and `_run_chained_dry_run` in `AgenticJobBase`, and the agents share one base, `ChainedDeepResearchAgent`. It holds the research leg, the options, the voice setup and the `run_async` frame. Each agent supplies its second stage and the artifacts it keeps.
- `source_document` (a list of absolute paths, or one string; `/api/v2/submit` takes it as `<scope>/<path>`) reaches only the research prompt. It is kept out of the session-name gist, the notifications and the saved report's query field.
- `budget` limits research only. A `BudgetExceededError` is re-raised as a plain exception, which ends the run `FAILED`.
- On success the job stores `artifacts["abstract"]`, a card with links to the report and the generated files. A language whose translation failed has no files and no links. The agent passes the generator's `failed_translations` through `pg_artifacts`. The card names each one as "Translation failed (not produced)", with its reason.

## What differs between the two
- Podcast options: `target_languages` (default `["en"]`), `script_type`, `review` and `max_segments` ([[podcast-script-types]]). The queue factory passes `languages` but not `max_segments`, so `max_segments` is reachable only by constructing the job or agent directly.
- Presentation options: `target_duration_minutes`, `target_slide_count`, `theme`. The presentation job also takes `lead_model`, which sets the research leg's lead model only; the podcast job does not pass one (its agent accepts it).
- The presentation leg builds its config from the INI file and overrides it with these options and `audience`, through `apply_job_overrides`, which the presentation job shares. The podcast leg builds its config with `resolve_podcast_config`: request, then script type, then INI.
- Results: the podcast has `audio_path` and `script_path`, with per-language maps in `pg_artifacts`; the presentation has `yaml_path`, `marp_path` and `slide_count`. The podcast job can also copy to Google Drive ([[podcast-drive-publishing]]). It passes the job's `user_email` but no config. So the hook loads the Drive settings from the INI, and `podcast drive upload users` decides whether this user is uploaded.

## When not to use it
- To run just one stage, use [[deep-research]], [[podcast-generation]] or [[presentation-generation]] directly. To turn an existing document into a podcast or deck, use the generator on that document; this chain always runs research first.
