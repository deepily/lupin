---
capability: reuse-stage-one-analysis-pages
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1_analysis.analyze_pages@66e471b628
  - lupin_mcp.reuse_stage1_analysis.page_arm@624f70c6a9
  - lupin_mcp.reuse_stage1_analysis.other_boundaries@680199ff95
  - lupin_mcp.reuse_stage1_analysis.old_shape_report@67ac1ea179
  - lupin_mcp.reuse_stage1_analysis.old_shape_arm@49ea56cbb6
---
# Reuse stage-one analysis: page arms and old shape

The parts of the analysis that read the page arms, the other policy boundaries and the old-shape comparison. Reported figures, not passes, unless said otherwise. The report is on [[reuse-stage-one-analysis-report]].

## Page arms
- `analyze_pages` reads the page arm of each question. The chosen pages are those the tool itself chooses at the policy floor, capped at five. Only pages answered in all three arms are read.
- A question fails when packing changes the set of chosen pages. A change between the two single runs is reported as noise only.
- `page_arm` judges packing of the page asks. The set rule fails when packing changes the set more often than noise does.
- The overlap rule fails when the packed 99th percentile passes the noise floor. It is reported and never changes the state.
- The state is `inconclusive` instead of `pass` when no page lies within 0.05 of the floor in any question.

## Other boundaries
- `other_boundaries` counts flips at the policy's floor and confidence bar. It compares the pack arm and single run 2 with single run 1, and records no pass or fail.

## Old shape
- `old_shape_arm` reads the old three-way answers for entries from the cache, as an arm record named `old`. It makes no live call, lists entries with no hit as not reached, and is complete only when every entry was a hit.
- `old_shape_report` compares that arm with single run 1 on the cache hits only. It reports the 99th percentile, the maximum and the boundary flips.
