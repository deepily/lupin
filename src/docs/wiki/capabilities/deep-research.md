---
capability: deep-research
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.deep_research.job.DeepResearchJob@63c44ef6c1
  - cosa.agents.deep_research.cli.run_research@e6898c5902
  - cosa.agents.deep_research.cli.generate_abstract_for_cli@802bfc04b2
  - cosa.agents.deep_research.cli.save_report_with_frontmatter@3805e7087f
  - cosa.agents.deep_research.config.ResearchConfig@fcd3ee4805
  - cosa.agents.deep_research.cost_tracker.CostTracker@acea766158
  - cosa.agents.deep_research.cost_tracker.BudgetExceededError@d9783d68d7
  - cosa.agents.deep_research.search_cache.normalize_query@68ff568bca
  - cosa.agents.deep_research.seed_context.query_with_seed_context@f833906de5
  - cosa.agents.deep_research.orchestrator.ResearchOrchestratorAgent@b8e1e66f07
---
# Deep research

`DeepResearchJob` answers a question from the web and saves a markdown report with YAML frontmatter under `io/deep-research/{user}`. Its `_execute` calls `cli.run_research`; the Claude calls are `ResearchAPIClient` in [[generator-sdk-clients]]. The job lifecycle is in [[agentic-job-contract]]. The chained jobs in [[research-chained-pipelines]] call `run_research` themselves.

## What it does
- `run_research` runs four steps inline: clarify the query, plan sub-topics, research each topic, synthesize one report. The job then makes an abstract (`generate_abstract_for_cli`) and saves the report (`save_report_with_frontmatter`, local or GCS).
- Topics are researched one after another, not in parallel. Each result is cached for the day under `io/deep-research/{user_email}/cache/{date}`; the key is the topic's six alphabetically-first words (`normalize_query`).
- The `ResearchConfig` code default is `claude-opus-4-6` for the lead, but the shipped INI (`[Lupin: Baseline]`, every section inherits it) sets `deep research lead model` to `claude-opus-5`. Subagents run `claude-sonnet-4-6` and at most 20 turns per call in both. The job's `lead_model`, `audience` and `audience_context` override.
- `source_document` paths are already validated by the v2 door; `query_with_seed_context` puts them in front of the question for this job and for the chained ones.

## Invariants
- `ResearchOrchestratorAgent` is not on this path: its docstring says it is reserved and not wired into production, and outside its own file only `cli.py` imports it (unused) and `__init__.py` exports it.
- The job defaults to `no_confirm=True`: no clarification question and no plan yes/no. With `confirm_topics` (set for a document run) the user ticks topics; no answer in 600 seconds cancels with nothing spent, unless the INI key `deep research cancel when no topics ticked` is false.
- Cancellation is polled after clarification, after planning, before each topic and before synthesis.
- A `CostTracker` raises `BudgetExceededError` when a recorded call would pass `budget`. `run_research` catches it, notifies and returns `None`, so the job answers "Research was cancelled by the user" and ends `COMPLETED` (bug row 2911d2a2). The abstract step also swallows every exception, so the job's own `BudgetExceededError` handler is not reached in practice.
- `DeepResearchJob` does not pass `user_email` to `run_research`, so its cache folder has an empty user segment and is shared by all users (bug row 20827e36). The chained agents pass theirs.

## How to extend
- Add a step inside `run_research` with a cancel check before it; keep JSON steps on `call_with_json_output`.

## Don't
- Don't wire a change into `ResearchOrchestratorAgent` expecting it to take effect in production.
- Don't assume two different topics never share a cache entry: the key is only six sorted words.
