---
capability: research-chained-cli
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research_to_podcast.__main__.main@15226517df
  - cosa.agents.deep_research_to_podcast.__main__.parse_args@bef45cd496
  - cosa.agents.deep_research_to_podcast.__main__.parse_languages@541471daf4
  - cosa.agents.deep_research_to_podcast.__main__.run_pipeline@ff3e840d54
  - cosa.agents.deep_research_to_podcast.__main__.show_dry_run@6b122dce27
  - cosa.agents.deep_research_to_presentation.__main__.main@15226517df
  - cosa.agents.deep_research_to_presentation.__main__.parse_args@4b0f3127dd
  - cosa.agents.deep_research_to_presentation.__main__.run_pipeline@75ae99e310
  - cosa.agents.deep_research_to_presentation.__main__.show_dry_run@5c87617a33
  - cosa.agents.deep_research_to_presentation.state.PipelineState@014a7bab54
---
# Research chained pipelines command line

Terminal entry points for the two chained pipelines in [[research-chained-pipelines]]: research to podcast, and research to presentation. Each is `python -m cosa.agents.<package>`.

## What it does
- `parse_args` reads the query, user email, budget, lead model, audience and the CLI-mode and dry-run switches. Each package adds its own options: languages and segments, or duration, slide count and theme.
- `main` answers `--user-visible-args` first, runs `show_dry_run` for a dry run, and otherwise exits with the code from `run_pipeline`.
- `parse_languages` splits a comma list of language codes. It returns `None` when the string is empty.
- `show_dry_run` prints the settings and the planned phases and output paths. It makes no model calls.
- `run_pipeline` builds the chained agent and awaits `run_async`. It prints the paths and the cost split on success.
- A partial result (research done, second step failed) prints the report path and a retry command and exits 1. Failure, interrupt or error also exits 1.
- The presentation `PipelineState` enum lists the stages from `INITIALIZED` through `COMPLETED`, `FAILED` and `CANCELLED`.

## Don't
- Don't treat exit 0 as "report saved". A partial run saved the report and still exits 1.
