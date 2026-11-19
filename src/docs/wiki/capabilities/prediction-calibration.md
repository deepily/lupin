---
capability: prediction-calibration
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.calibration.calibrate@f03cd87455
  - cosa.agents.prediction_engine.calibration.cell_key@9178e96dcf
  - cosa.agents.prediction_engine.calibration.empty_document@5a30ab828e
  - cosa.agents.prediction_engine.calibration.fit_calibration@60703b7b13
  - cosa.agents.prediction_engine.calibration.fit_cell@4cf833a545
  - cosa.agents.prediction_engine.calibration.group_by_cell@0642d67b03
  - cosa.agents.prediction_engine.calibration.load_calibration@71eb80b595
  - cosa.agents.prediction_engine.calibration.reliability_report@4f6282c956
  - cosa.agents.prediction_engine.calibration.write_calibration@08634fc041
---
# Prediction confidence calibration

Fits, stores, loads and applies a map from the engine's raw confidence to the chance it was right, one map per cell ([[prediction-engine]]).

## Fitting
- `cell_key( response_type, strategy )` returns `"<response_type>|<strategy>"`, the key in the stored map. Neither part may hold a pipe.
- `group_by_cell( rows )` takes `( response_type, strategy, confidence, correct )` rows and returns cell key to its confidences and correct flags, in row order.
- `fit_cell( confidences, correct )` returns a refusal `{ status: "insufficient data", n, needed }` below `MIN_ROWS_PER_CELL` rows. Otherwise it returns `{ status: "fit", n, x, y }`, an isotonic step map. It raises `ValueError` when the two lists differ in length.
- `fit_calibration( rows, cohort_sha, fit_time )` returns the stored document: version, cohort sha, fit time and every cell seen, fitted or refused. Pass scored rows only.

## Using it
- `calibrate( cell, confidence )` returns the step value, clipped to the fitted range at both ends. A missing or refused cell gives `None`, so the caller decides what to show.
- `reliability_report( confidences, correct, n_bins )` gives each non-empty bin's mean confidence and observed rate, low to high.

## The file
- `empty_document()` is the shape committed before the first fit. `write_calibration` writes sorted, indented JSON and returns the path. `load_calibration` raises `FileNotFoundError` for a missing file and `ValueError` for a version other than `FORMAT_VERSION`.
