---
capability: reuse-stage-two-fit-and-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage2_fit.fit_policy@60a559dd13
  - lupin_mcp.reuse_stage2_fit.fit_old@0766cedfc3
  - lupin_mcp.reuse_stage2_fit.reliability@1fa345a583
  - lupin_mcp.reuse_stage2_fit.report@14b4ee043d
  - lupin_mcp.reuse_stage2_fit.old_report@6b7a5b8c84
  - lupin_mcp.reuse_stage2_fit.render@fa27fcc2bb
  - lupin_mcp.reuse_stage2_fit.main@b485165a3c
---
# Reuse stage-two fit: fitting and reports

Fits the cut-offs of the pair question on the fit half only and reads them on the check half. No model is called. Row handling is on [[reuse-stage-two-fit-rows]].

## Fitting
- The false-reuse rate allowed is a required argument with no default, so nothing is fitted on a number nobody chose.
- `fit_policy` tries every grid point for reuse, threshold, floor and coverage, skipping any whose floor is above its reuse cut. It chooses the point with the most twins on the shortlist among those within the rate.
- A tie goes to the highest reuse cut, then the highest threshold, then the lowest floor and coverage. A bad rate or grid, an empty fit half or a row of the check half raises `ValueError`.
- `fit_old` does the same for the old question's single cut, which serves as reuse cut and shortlist threshold alike. A tie goes to the highest cut.

## Reports
- `report` fits the new question and reads the chosen policy on both halves. It adds the edges, the tie count and whether the rate binds at any cut. `old_report` returns the same keys with a cut.
- `reliability` bins a score from 0 to 1 against the share of rows that are twins. The top bin includes 1.0, and a row with no readable score counts as unusable.
- `render` writes the report as plain text. It warns about a chosen value on a grid edge, a rate that binds nowhere, and a tie. The tie-break rules are stated once in words.

## Command
- `main` takes either a rows file or the old run's results with a manifest, plus a split file and the rate. It exits 2 for a missing or conflicting argument.
- `--placeholder` says in the report that the rate is a placeholder. The command prints the report and writes nothing.
