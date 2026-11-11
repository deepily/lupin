---
capability: deep-research-shared-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.deep_research.job.abstract_and_save_report@958c9a1715
  - cosa.agents.deep_research.job.derive_session_name@d6679a5ecd
  - cosa.agents.deep_research.job.resolve_output_settings@82d555cfce
---
# Deep research shared helpers

Three module functions in `deep_research/job.py` serve [[deep-research]] and the research leg of [[research-chained-pipelines]]. Each caller used to carry its own copy.

## What it does
- `resolve_output_settings( config_mgr )` returns `( storage_backend, gcs_bucket, output_dir )`. `output_dir` is absolute under the project root, whether the INI value was relative, rooted at `/` or already under the root.
- `derive_session_name( query )` returns `( session_name, semantic_topic )`. The name is the Gister's gist, lower case and trimmed. An empty or None gist gives `general research query`. The topic is the name with dashes for spaces.
- `abstract_and_save_report( report, query, config, cost_tracker, session_id, semantic_topic, output_settings, user_email )` writes the abstract, then saves the report with its frontmatter. It returns `( abstract, report_path )`.

## Invariants
- A whitespace-only gist gives `general research query` in the chained agents too, as in the plain job.
- `abstract_and_save_report` raises whatever `generate_abstract_for_cli` or `save_report_with_frontmatter` raises, such as `BudgetExceededError`.
