---
capability: preference-replay-vectors
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.question_vectors.EngineChanged@3e88eea1d6
  - cosa.research.preference_replay.question_vectors.cohort_texts@e6423591c5
  - cosa.research.preference_replay.question_vectors.engine_stamp@b884bda88b
  - cosa.research.preference_replay.question_vectors.generate@aa9be885ce
  - cosa.research.preference_replay.question_vectors.load_side_file@9a16f09821
  - cosa.research.preference_replay.question_vectors.main@543b7cc051
  - cosa.research.preference_replay.question_vectors.norm_band@9905fc7552
  - cosa.research.preference_replay.question_vectors.read_side_records@eec1324abd
  - cosa.research.preference_replay.question_vectors.write_side_file@883716aaef
  - cosa.research.preference_replay.arm_vectors.load_frozen_ids@4c2565d40f
  - cosa.research.preference_replay.arm_vectors.main@bca02a350a
  - cosa.research.preference_replay.arm_vectors.positive_int@b9352759de
  - cosa.research.preference_replay.arm_vectors.restamp_text_rule@ca346cb555
---
# Preference replay vectors

Makes fresh question vectors in a side file and checks them against the stored ones. The embedding service answers over HTTP; nothing here loads a model or touches a GPU ([[preference-replay-core]]).

## Side file
- `cohort_texts( session, response_types )` lists ( ask id, question text ) pairs in cohort order. The text is `message.strip()`, what the live store path embeds.
- `generate( pairs, provider, probe_size, batch_size, clock, probe_only )` embeds, validates each vector and stamps the run with its engine. `engine_stamp( provider )` reads model, revision, dtype and dimensions. `EngineChanged` is raised when that block differs between the first read and the last.
- `write_side_file` writes JSON lines in one move, so a reader never sees half. `read_side_records( path, refuse, expected_version )` reads the header and the records and checks them against each other, raising the caller's own refusal class. `load_side_file` reads the header and a vector per id through it; the backfill script reads the records through it too. `norm_band( vectors )` gives the smallest and largest length. `main` runs it.

## Context arms
- `arm_vectors.main` makes one arm's side file over the frozen cohort. `load_frozen_ids` reads the ask ids in file order through `read_jsonl`, and refuses a file with no id or a repeated id. `positive_int` reads a count of at least one. `restamp_text_rule` names the arm's own text rule in the header.
