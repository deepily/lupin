---
capability: reuse-stage-two-fit-rows
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage2_fit.NoFeasiblePolicy@694acf19b5
  - lupin_mcp.reuse_stage2_fit.twin_map_from_manifest@06e2124ff6
  - lupin_mcp.reuse_stage2_fit.rows_from_old@711cea9b7f
  - lupin_mcp.reuse_stage2_fit.check_rows@ecfd601b34
  - lupin_mcp.reuse_stage2_fit.split_rows@ffe4b0c3db
  - lupin_mcp.reuse_stage2_fit.usable@2756245a6d
  - lupin_mcp.reuse_stage2_fit.shortlist@29359ac76d
  - lupin_mcp.reuse_stage2_fit.evaluate@bd81214db7
  - lupin_mcp.reuse_stage2_fit.edges@9a288209df
---
# Reuse stage-two fit: rows and shortlists

The row handling and policy scoring behind the threshold fit. Fitting and reporting are on [[reuse-stage-two-fit-and-report]].

## Rows
- `twin_map_from_manifest` maps each id to the ids it shares an exact or near cluster with. An id is never its own twin.
- `rows_from_old` turns the old run's rows into labelled-run rows. Provides, coverage and score are `None`, and a candidate is labelled true when it is a twin.
- `check_rows` raises `ValueError` naming the row and key when a key is missing or a score is outside 0 to 1.
- `split_rows` cuts rows into a fit half and a check half by member. A member the split does not know raises `ValueError`.
- `usable` is true when the run answered the pair and the answer was readable.

## Shortlist under a policy
- `shortlist` ranks usable rows by provides, then candidate id, and keeps at most ten. The causal rows are the reuse rows, else the extend rows, and there are none when any row was unusable.
- The pool is the causal rows plus every usable row at or above the threshold. Causal rows keep their place first and the best others fill what is left.
- `evaluate` counts twins on the shortlist, hit at ten, twin recall, false reuse and unusable rows. A false reuse is a usable non-twin row at or above the reuse cut, and its rate is over all non-twin rows.
- An unusable twin row counts as a twin and as a miss. A ratio with nothing to divide by is `None`.

## Grid edges
- `edges` names each chosen value that sits at the lowest or highest end of its grid. A grid with one value has no edge.
- `NoFeasiblePolicy` is raised when no grid point keeps false reuse within the allowed rate.
