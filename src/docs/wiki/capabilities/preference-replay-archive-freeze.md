---
capability: preference-replay-archive-freeze
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.archive_replay.tree_state@afa6989ed8
  - cosa.research.preference_replay.archive_replay.current_freeze@bebc3294ed
  - cosa.research.preference_replay.archive_replay.check_freeze@07bb6ab27a
  - cosa.research.preference_replay.archive_replay.FreezeMismatch@71f89f82e8
  - cosa.research.preference_replay.archive_replay.freeze_limits@cd5812bf65
  - cosa.research.preference_replay.archive_replay.BoundStop@bcb4cf5768
  - cosa.research.preference_replay.archive_replay.bound_failed@b679a235dc
  - cosa.research.preference_replay.archive_replay.replace_arms@3f732dd1e6
  - cosa.research.preference_replay.archive_replay.rerun_bound_failures@58fefd7e03
---
# Preference replay: the freeze and the principle limit

Keeps one archive run honest across stops and restarts ([[preference-replay-archive-stages]]). The limit is read in `principle_retrieval.retrieval_limits` ([[principle-retrieval]]).

## The freeze
- `tree_state( folder )` names the git commit of a folder and whether a tracked file has an uncommitted change.
- `current_freeze( models, code, scored_against )` lists every setting that must not change inside one window. These are the code commit, the versions, the encoder, neighbours and k. They also include the limit and multiplier from the INI file, the lag, the window start, the floor and both model ids. It also names the checkpoint the run is scored against, so a work folder started under one checkpoint is refused under the other. A freeze written before that key existed reads as the 18 Nov checkpoint.
- `check_freeze( state, current, accept_code_change, now )` records the freeze on the first start. A later start under other settings raises `FreezeMismatch` naming each difference.
- Two changes are allowed. A higher limit is allowed when the old multiplier was 0 and the multiplier is unchanged. A code change is allowed when `accept_code_change` names the old and new sha as written and the tree is clean.
- An allowed change replaces the freeze and appends an entry to `freeze_history`. A freeze written before the multiplier existed reads it as 0.
- `freeze_limits( models, state )` hands the frozen limit and multiplier to the arms and returns the limit. No forecast then rereads the INI file.

## The stop
- `BoundStop` carries the ask id, the principles held and the limit. Its message names the INI key to raise and says finished work is kept.
- `bound_failed( counts )` is True when any job result carries the limit-failure reason.
- `replace_arms( path, replacements )` rewrites named arm entries in a records file through a temporary file. Line count and every other entry stay as read.
- `rerun_bound_failures` runs again only the lines whose arm failed on the limit. It deletes the stored failure first, then runs that arm alone, and scores the new forecast as the harness does.
- The file is rewritten every `chunk` asks and at the end. A second failure on the limit deletes that row, writes the finished entries and raises `BoundStop`.
