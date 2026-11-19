---
capability: prediction-evidence-recorder
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.evidence_recorder.begin@40ec3c8070
  - cosa.agents.prediction_engine.evidence_recorder.collect@2d6e8704cb
  - cosa.agents.prediction_engine.evidence_recorder.note@a6c89d9c82
---
# Prediction evidence recorder

A per-thread list of the cases one forecast retrieved, so the forecast row stores that ask's ids and scores and no other ask's. `predict` runs on one worker thread per ask ([[prediction-engine]]).

## What it does
- `begin()` starts an empty list for the calling thread. `predict` calls it first.
- `note( similar_cases )` adds the retrieved cases to the calling thread's list. Each retrieval path calls it after a search.
- `collect()` returns the calling thread's list and clears it. `predict` calls it last.
