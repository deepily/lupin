---
capability: preference-replay-extractor-replay
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.extractor_replay.ExtractorReplay@c1ff165f05
  - cosa.research.preference_replay.extractor_replay.LeakageError@de8e47e769
  - cosa.research.preference_replay.extractor_replay.stand_in_vector@13bf1e6f0f
  - cosa.research.preference_replay.extractor_replay.canned_model@88104c58df
  - cosa.research.preference_replay.extractor_replay.asks_from_session@059da399f8
  - cosa.research.preference_replay.extractor_replay.principles_as_of@b7855c110d
  - cosa.research.preference_replay.extractor_replay.make_recorder@d1cae4acf0
  - cosa.research.preference_replay.extractor_replay.check_no_leakage@0f75561045
  - cosa.research.preference_replay.extractor_replay.principle_list@eacd09aa11
  - cosa.research.preference_replay.extractor_replay.run_replay@599e1ebc39
  - cosa.research.preference_replay.extractor_replay.main@b10042cc42
---
# Preference replay: the extractor replay

Replays a context export through the principle extractor in the order the asks were made. It uses `replay_loop.replay` as its one harness ([[preference-replay-core]]). The output is plumbing and a principle list for the owner to read. It makes no accuracy claim.

## What it does
- `ExtractorReplay` runs the extractor over answers in time order from inside the replay's providers. An answer is extracted at most once, and only once `responded_at` plus the lag has been reached.
- The evidence's `extracted_at` is exactly `responded_at + lag`. `catch_up( until )` extracts every pending answer usable by then. `episode_provider` and `principles_provider` feed the arms.
- `principles_provider` runs `catch_up` first. Then it returns `principles_as_of` for the ask's owner, with only evidence usable at the ask.
- `principles_as_of` lists each principle with its derived status and evidence. A principle with no usable evidence is absent.
- `make_recorder( seen )` builds a recording arm that forecasts like always-yes and keeps deep copies of what it was handed. `check_no_leakage( seen )` raises `LeakageError` for evidence dated after its ask.
- `asks_from_session` builds the ask dicts from the scratch copy. `stand_in_vector` gives a text a stable 20-wide vector, so the replay never calls the embedding service.
- `canned_model` stands in for the model: one grounded hypothesis per field, and none for a bare yes.
- `run_replay` replays the loaded asks and keeps extracting past the last ask. Its `encoder` argument names the encoder version principles are stored and searched under. It returns the run, the seen list, the extractions, the table counts and the leakage count.
- `principle_list` lists every principle with its heading, status and evidence counts.
- `main` replays an export for each `--lag-seconds` value, 0 and 300 by default, and writes the last variant's list to `--out`. Each variant also prints the extractor's totals: principles created, reused, off-vocabulary and rejected. A live run needs `--model`, else it exits with a usage error.
- With `--embeddings service`, vectors come from the embedding service through a side cache ([[preference-replay-service-embeddings]]). `--neighbour-cosines-out` writes the cosine of every neighbour shown to the model.
