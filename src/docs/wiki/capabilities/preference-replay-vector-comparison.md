---
capability: preference-replay-vector-comparison
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.vector_comparison.ControlFailed@2c3e9df680
  - cosa.research.preference_replay.vector_comparison.band_counts@595a028a00
  - cosa.research.preference_replay.vector_comparison.compare@a88c38581a
  - cosa.research.preference_replay.vector_comparison.cosine@cd69e77f08
  - cosa.research.preference_replay.vector_comparison.main@57a1c38f8b
  - cosa.research.preference_replay.vector_comparison.negative_control@0614b4060b
  - cosa.research.preference_replay.vector_comparison.parse_vector@f2f73e3b3c
  - cosa.research.preference_replay.vector_comparison.positive_control@6ab4f3e6f6
  - cosa.research.preference_replay.vector_comparison.read_stored@2a4a77f57f
  - cosa.research.preference_replay.vector_comparison.report@140b6ea0a1
  - cosa.research.preference_replay.vector_comparison.summarize@c667a038b5
---
# Preference replay vector comparison

Checks whether the stored question vectors and the fresh ones in the side file came from one model ([[preference-replay-vectors]]). The same text and model give a cosine of 1.0 up to float noise.

## What it does
- `read_stored( session, ids )` reads each stored vector with its question. `parse_vector` turns a driver value into floats. `cosine` and `l2_norm` (read from `cosa.rest.db.embedding_regeneration`) are the two measures. `compare( stored, fresh )` gives cosine and norm ratio per ask. `band_counts` counts cosines by band, highest first. `summarize` gives count, minimum, median and maximum.
- Both controls run first. `positive_control` embeds the same texts twice and compares. `negative_control` pairs each stored vector with the next ask's fresh vector. Either failing raises `ControlFailed`, and no verdict is given. `report` builds the comparison, `main` runs it.
