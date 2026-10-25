---
capability: reuse-stage-one-analysis-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1_analysis.request_stats@a9edbeacb5
  - lupin_mcp.reuse_stage1_analysis.cost_per_search@2de0279a82
  - lupin_mcp.reuse_stage1_analysis.build_report@7ff5c8924c
  - lupin_mcp.reuse_stage1_analysis.render@b55bf8fe96
  - lupin_mcp.reuse_stage1_analysis.main@681a972f02
---
# Reuse stage-one analysis: report

Builds and prints the full report of the packing measurement from a folder of arm files. The rules it applies are on [[reuse-stage-one-analysis-passes]].

## Request and cost figures
- `request_stats` summarises, per arm, the requests sent, tokens in and out per request, tokens out per entry, retried calls and extra attempts. It also counts missing usage and attempts that ended in 429 or 529.
- Only rows with an attempt count as sent. A sent row with no usage counts as missing and stays out of the means.
- `cost_per_search` prices one search at the default pack size: the entries asked in packs plus the page asks packed. Input and output tokens count at the same rate.
- It returns `None` when there is no default size, and the dollar figure uses the pinned price per million tokens.

## The report
- `build_report` runs every part of the analysis on the arm records and the canaries. It returns the decision, the next step and each block, with a lost count beside its limit for every arm.
- An arm another model answered replaces the decision with a stop naming the arm and the model. A failing page arm turns a decision that did not stop into a stop.
- An arm that asked an id more than once stops the decision. Unclean and superseded arms are listed apart.
- `render` writes the report as plain text, from the decision and next step to the cost per question.
- `main` reads a folder of arm and canary files and prints the report. It skips probe plan files and returns 2 when the folder has no arm file. A canary with no arm file beside it raises `ValueError`.
