---
capability: preference-replay-archive-inputs
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.archive_replay.load_archive@b6bbbea759
  - cosa.research.preference_replay.archive_replay.fixture_ids@94a3549c48
  - cosa.research.preference_replay.archive_replay.evaluation_ids@de1a916142
  - cosa.research.preference_replay.archive_replay.extractor_settings@acf79b0826
  - cosa.research.preference_replay.archive_replay.fixed_rules_arm@d04dfa7deb
  - cosa.research.preference_replay.archive_replay.scratch_topk@f0b62d5779
  - cosa.research.preference_replay.archive_replay.locked_sessions@a458fcfd00
  - cosa.research.preference_replay.archive_replay.ModelArms@307cbabefb
  - cosa.research.preference_replay.archive_replay.ModelArms.run@2e9793c55b
  - cosa.research.preference_replay.archive_replay.ModelArms.reader@4c1493feba
  - cosa.research.preference_replay.archive_replay.ModelArms.discard_bound_failures@46ea753209
  - cosa.research.preference_replay.archive_replay.default_models@0c5ad6c2d4
---
# Preference replay: archive inputs and model arms

What the archive replay loads and which arms it runs ([[preference-replay-archive-stages]]). It uses `replay_loop.replay` as its one harness ([[preference-replay-core]]).

## Inputs
- `load_archive( session, asks_path, nonasks_path )` inserts every archived notification into the scratch copy. A row with no priority gets a stand-in, which no forecast reads. A copy that already holds notifications is left alone and the call returns 0.
- `fixture_ids( export_path )` names the development fixture's asks.
- `evaluation_ids( asks, fixture, window_start )` lists yes/no and multiple-choice asks outside the fixture, asked at or after the window start, in replay order. Other asks still serve as cases and extractor inputs.
- `extractor_settings()` reads the extractor's model id and timeout from the INI file, as the live job does. A missing key raises.
- `fixed_rules_arm( ask, visible_rows )` forecasts yes for a yes/no ask. For a multiple-choice ask it picks, per field, the one recommended label, else the first. A multi-select field gets a one-item list.
It returns None for a card with no option to pick, and for any other type.
- `scratch_topk` is the live cosine search done in Python, because SQLite has no vector operator. It returns at most `limit` pairs of cosine times 100 and row, best first.
- `locked_sessions( bind )` makes the session factory the arms' jobs use. It holds a lock for the whole block, so two threads never share the one connection.

## ModelArms
- `ModelArms` runs the baseline, the principles forecast and the two Opus twins through their own jobs, each with its switch forced on. Its `limits` go to every principles forecast.
- `run( ask_id, arms )` runs the arms for one ask at once, with the live search swapped for `scratch_topk`. It reads each row back as a forecast and reason. A missing row reads `no_row`.
- `reader( arm )` gives the harness a baseline function that returns that arm's stored forecast.
- `discard_bound_failures` deletes only rows whose reason is the principle-limit failure, and returns how many.
- `default_models( session, embed, encoder, extractor, work )` builds the arms from the INI model, timeout, layers and caps. The baseline's ledger goes in the work folder.
