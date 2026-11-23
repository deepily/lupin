---
capability: preference-replay-retune
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.retune.eligible_asks@148d7a005c
  - cosa.research.preference_replay.retune.frozen_settings@b9e88a9667
  - cosa.research.preference_replay.retune.grid@da8968232a
  - cosa.research.preference_replay.retune.report_only_sweep@e66e30473f
  - cosa.research.preference_replay.retune.retune@d6b731bce8
  - cosa.research.preference_replay.retune.split_windows@4bd4c4b7ad
  - cosa.research.preference_replay.retune_run.ControlMismatch@57f484c591
  - cosa.research.preference_replay.retune_run.build_report@e97fd12144
  - cosa.research.preference_replay.retune_run.check_vectors_cover@0ec4d5bc1d
  - cosa.research.preference_replay.retune_run.main@1bbcf37e9d
  - cosa.research.preference_replay.retune_run.read_cohort@d966335b99
  - cosa.research.preference_replay.retune_run.read_id_list@cb6b8c61aa
  - cosa.research.preference_replay.retune_run.restrict_to_ids@873d297f85
  - cosa.research.preference_replay.retune_run.run_report@fd317d8403
  - cosa.research.preference_replay.retune_run.write_control_ids@5acfa74615
---
# Preference replay retune

Retunes the two retrieval settings on a tune window and scores them on a final window ([[preference-replay-core]]).

## The retune
- `grid( thresholds, top_ks )` lists the points in the order tried. The thresholds run from 0.50 to 0.90 and top k is 3, 5, 8 or 10.
- `eligible_asks( asks )` keeps the asks the two settings serve. `split_windows( count, tune_fraction )` splits a time-ordered run by position into the first 70 percent for tuning and the rest as the final window.
- `retune( asks, engine, snapshot_sha256, thresholds, top_ks, tune_fraction )` replays every grid point. It names the one with the most correct per 100 on the tune window. The final window only reports.
- `report_only_sweep` replays thresholds below the grid to show the trade-off. Nothing in it is frozen. `frozen_settings( result )` names the INI values a retune freezes.

## The run
- `read_cohort( session, vectors, response_types )` reads the scored cohort and the facts that date it in a read-only transaction. `check_vectors_cover( asks, header )` refuses an ask with no vector the side file explains.
- `read_id_list( ids_path )` reads a committed id list, one bare id per line or JSON lines (read by `arm_vectors.load_frozen_ids`, which refuses a repeated id). A file that mixes the two is refused. `restrict_to_ids` keeps those asks in cohort order.
- `run_report` replays the grid and the sweep. `build_report` assembles the JSON with settings, cohort checksums, every point and the command and code that made it.
- `write_control_ids` writes the replayable ids only when the run reproduces the committed baseline, else raises `ControlMismatch`. `main` runs it from the command line.
