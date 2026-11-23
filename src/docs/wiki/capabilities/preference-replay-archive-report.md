---
capability: preference-replay-archive-report
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.archive_replay.build_report@6e3feb5d1b
  - cosa.research.preference_replay.archive_replay.render_report@61cae3e538
---
# Preference replay: the archive report

Pairs the arms of an archive run and prints a table with no reading of the verdicts ([[preference-replay-archive-stages]]).

## What it does
- `build_report( records, twin_records, state, floor )` pairs six arms on the same asks. The principles arm is paired with the baseline, the engine and the fixed rules. The baseline is paired with the engine. Each Opus twin is paired with its Haiku twin.
- Each pairing is `replay_loop.summarize` at the floor stated before the run, with coverage and accuracy on the answered asks beside it.
- An Opus pairing covers only the asks both twins have a line for, and its Haiku twin is cut to the same asks.
- A pairing whose arm has no line is reported as not run, with no verdict.
- The report also carries the freeze as stored, the asks with an episode history, the skipped asks and the twin stretch.
- `render_report( report )` writes one markdown row per pairing: asks, wins each way, floor met, the verdict, and coverage and accuracy per arm.
- The verdict names the arm that came out ahead. "engine better" reads as the pairing's first arm label plus "better". "baseline better" reads as its second arm's label plus "better". "no difference" and "not decisive" are unchanged.
- The table shows the fixed rules arm and the engine arm under short labels, taken from the code.
