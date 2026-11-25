---
capability: preference-replay-archive-stages
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.archive_replay.WorkFolder@6a5fba0068
  - cosa.research.preference_replay.archive_replay.load_state@2204be7068
  - cosa.research.preference_replay.archive_replay.save_state@a290779123
  - cosa.research.preference_replay.archive_replay.append_lines@0cd8c0850a
  - cosa.research.preference_replay.archive_replay.extracted_in_db@7f0d2c8685
  - cosa.research.preference_replay.archive_replay.PeriodicFlush@5f087a051d
  - cosa.research.preference_replay.archive_replay.PeriodicFlush.flush@d338856d94
  - cosa.research.preference_replay.archive_replay.checkpoint_line@2724b71a61
  - cosa.research.preference_replay.archive_replay.principle_progress@bf3abb5db9
  - cosa.research.preference_replay.archive_replay.warning_text@e9a80093eb
  - cosa.research.preference_replay.archive_replay.run_first_stage@19463edfac
  - cosa.research.preference_replay.archive_replay.run_twin_stage@91f0716db0
  - cosa.research.preference_replay.archive_replay.main@8f53b08fa5
---
# Preference replay: archive stages and checkpoints

Runs the archive of asks through every arm in stages, each able to stop and resume ([[preference-replay-archive-inputs]], [[preference-replay-archive-freeze]]).

## Work folder and checkpoints
- `WorkFolder( root )` names the run's files: scratch database, state, records, twin records, checkpoint log, embedding cache, ledger and report.
- `load_state` reads the checkpoint, or an empty one. `save_state` writes through a temporary file, so a cut write keeps the old file. `append_lines` adds one JSON line per object.
- `extracted_in_db( session, version )` names the answers whose evidence is already stored, so none is extracted twice.
- `PeriodicFlush` wraps the embedder and writes its side file every 500 service calls and on `flush`. A cached text makes no call and no write.
- `checkpoint_line` gives asks done, principles against the limit, evidence held and job results by reason. `principle_progress` shows `<count>/<limit> (<percent>%)`. `warning_text` warns from 80% of the limit.

## The two stages
- `run_first_stage` predicts the evaluation asks in time order with the engine, the fixed rules and the two Haiku arms. Principles are extracted from each answer as time reaches it. Each chunk is replayed, leak-checked, written to the records file and checkpointed.
- A chunk already done is skipped, and a line already recorded is never written twice. An ask with no vector is counted once and skipped from then on.
- `run_twin_stage` runs the Opus twins only on asks the first stage has recorded, so they never set its pace. With `follow` it waits for more asks.
- Each stage first calls `discard_unrecorded_limit_failures`, which deletes limit failures stored for asks its record file does not hold. It then re-forecasts the recorded asks whose principles forecast failed on the limit.
- Both stages raise `FreezeMismatch` and `BoundStop` as described on the freeze page. On a stop the work is saved and a named line is logged.

## Command line
- `main( argv )` takes the stage `first`, `twins` or `report`, with `--work`, `--asks`, `--non-asks` and `--fixture`. It also takes `--follow`, `--chunk`, `--accept-code-change`, `--checkpoint` and `--limit N`, which cuts the evaluation to N asks for a short trial. `--checkpoint` names the freeze file the run is scored against (default: the 18 Nov checkpoint). Every run prints which one first.
- A stop on the limit returns exit 3 with the work saved. Any other return is 0.
- The report stage is on [[preference-replay-archive-report]].
