---
capability: research-chained-cli
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.deep_research_to_podcast.__main__.main@b4c655a2b5
  - cosa.agents.deep_research_to_podcast.__main__.parse_args@85d916d281
  - cosa.agents.deep_research_to_podcast.__main__.run_pipeline@8cb93b607a
  - cosa.agents.deep_research_to_podcast.__main__.show_dry_run@86b85b571d
  - cosa.agents.deep_research_to_presentation.__main__.main@b4c655a2b5
  - cosa.agents.deep_research_to_presentation.__main__.parse_args@3cfb850589
  - cosa.agents.deep_research_to_presentation.__main__.run_pipeline@f1e8811b80
  - cosa.agents.deep_research_to_presentation.__main__.show_dry_run@5c87617a33
  - cosa.agents.deep_research_to_presentation.state.PipelineState@014a7bab54
  - cosa.agents.utils.chained_cli.add_deep_research_arguments@3d3dc35c79
  - cosa.agents.utils.chained_cli.add_mode_arguments@ab8382cd2a
  - cosa.agents.utils.chained_cli.run_chained_cli@cfcf6bff6c
  - cosa.agents.utils.chained_cli.run_agent_and_report@225bc810a4
---
# Research chained pipelines command line

Terminal entry points for the two chained pipelines in [[research-chained-pipelines]]: research to podcast, and research to presentation. Each is `python -m cosa.agents.<package>`.

## What it does
- `parse_args` reads the query, user email, budget, lead model, audience, audience context and the CLI-mode and dry-run switches. `add_deep_research_arguments` adds the first seven and `add_mode_arguments` adds the mode and debug switches, for both packages. Each package adds its own options: languages and segments, or duration, slide count and theme.
- `main` calls `run_chained_cli`. That answers `--user-visible-args` first, before argparse checks the required options. It runs `show_dry_run` for a dry run, and otherwise exits with the code from `run_pipeline`.
- The language list is read with `parse_languages_arg` from the podcast generator's CLI, which returns `None` when the string is empty.
- `show_dry_run` prints the settings and the planned phases and output paths. It makes no model calls.
- `run_pipeline` builds the chained agent and hands it to `run_agent_and_report`, with the package's own success lines and retry command.
- `run_agent_and_report` awaits `run_async`. On success it prints the report, the abstract, the package's artifact lines and cost split, and the duration.
- A partial result (research done, second step failed) prints the report path and a retry command and exits 1. Failure, interrupt or error also exits 1.
- The presentation `PipelineState` enum lists the stages from `INITIALIZED` through `COMPLETED`, `FAILED` and `CANCELLED`.

## Don't
- Don't treat exit 0 as "report saved". A partial run saved the report and still exits 1.
