---
capability: research-chained-cli
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research_to_podcast.__main__.main@b4c655a2b5
  - cosa.agents.deep_research_to_podcast.__main__.parse_args@85d916d281
  - cosa.agents.deep_research_to_podcast.__main__.parse_languages@541471daf4
  - cosa.agents.deep_research_to_podcast.__main__.run_pipeline@ff3e840d54
  - cosa.agents.deep_research_to_podcast.__main__.show_dry_run@6b122dce27
  - cosa.agents.deep_research_to_presentation.__main__.main@b4c655a2b5
  - cosa.agents.deep_research_to_presentation.__main__.parse_args@3cfb850589
  - cosa.agents.deep_research_to_presentation.__main__.run_pipeline@75ae99e310
  - cosa.agents.deep_research_to_presentation.__main__.show_dry_run@5c87617a33
  - cosa.agents.deep_research_to_presentation.state.PipelineState@014a7bab54
  - cosa.agents.utils.chained_cli.add_deep_research_arguments@3d3dc35c79
  - cosa.agents.utils.chained_cli.add_mode_arguments@ab8382cd2a
  - cosa.agents.utils.chained_cli.run_chained_cli@cfcf6bff6c
---
# Research chained pipelines command line

Terminal entry points for the two chained pipelines in [[research-chained-pipelines]]: research to podcast, and research to presentation. Each is `python -m cosa.agents.<package>`.

## What it does
- `parse_args` reads the query, user email, budget, lead model, audience and the CLI-mode and dry-run switches. `add_deep_research_arguments` adds the first six and `add_mode_arguments` adds the mode and debug switches, for both packages. Each package adds its own options: languages and segments, or duration, slide count and theme.
- `main` calls `run_chained_cli`. That answers `--user-visible-args` first, before argparse checks the required options. It runs `show_dry_run` for a dry run, and otherwise exits with the code from `run_pipeline`.
- `parse_languages` splits a comma list of language codes. It returns `None` when the string is empty.
- `show_dry_run` prints the settings and the planned phases and output paths. It makes no model calls.
- `run_pipeline` builds the chained agent and awaits `run_async`. It prints the paths and the cost split on success.
- A partial result (research done, second step failed) prints the report path and a retry command and exits 1. Failure, interrupt or error also exits 1.
- The presentation `PipelineState` enum lists the stages from `INITIALIZED` through `COMPLETED`, `FAILED` and `CANCELLED`.

## Don't
- Don't treat exit 0 as "report saved". A partial run saved the report and still exits 1.
