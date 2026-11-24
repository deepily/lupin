---
capability: preference-replay-calibration-scores
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.calibration_fit.binary_brier@fda0621096
  - cosa.research.preference_replay.calibration_fit.band_calibration@8a6fb0e0e4
  - cosa.research.preference_replay.calibration_fit.multiclass_brier@9c86d54398
  - cosa.research.preference_replay.calibration_fit.neither_recall_precision@61d63bd50f
---
# Preference replay: calibration scores

The scoring helpers beside the calibration fit ([[preference-replay-core]], [[prediction-calibration]]). Reports call them; none of them chooses a threshold.

## Binary
- `binary_brier( confidences, correct )` scores confidences against whether each forecast was right. It is the same scikit-learn call `fit_and_evaluate` stores as `brier_raw`.
- `band_calibration( confidences, correct )` reports `n`, `mean_confidence` and `accuracy` in four fixed confidence bands, keyed by band lower edge.
- A band with no rows is absent. A confidence outside 0 to 1, or NaN, belongs to no band and is left out.

## Yes, no, neither
- `multiclass_brier( probabilities, actual )` is the mean summed squared gap between each stance probability and the answer. A perfect forecast scores 0.0 and a certain wrong one 2.0.
- `neither_recall_precision( probabilities, actual, threshold )` calls a row neither when its neither probability reaches the frozen threshold.
- It returns `recall`, `precision`, `called` and `actual`. Recall is None with no actual neither, and precision is None with no row called.
