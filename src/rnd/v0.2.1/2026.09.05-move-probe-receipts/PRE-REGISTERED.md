# PRE-REGISTERED — written 2026-09-05T18:47:49-04:00, BEFORE any arm result existed
Arm A was at ~70% and NO failset file existed for any arm when this was written.
Verified at write time: 0 failset files present.

## Sampler identity (maria's point: a GAP and "nothing running" must be distinguishable)
pid=1504007  cadence=20s  log=contention.log  started=2026-09-05T18:46:13-04:00
- The sampler prints `trees=[none]` EXPLICITLY when nothing is running. That is a
  RECORD of absence, not an absence of record.
- A missing sample is therefore detectable as a timestamp gap > 25s. gapcheck.sh reports them.
- ⇒ "nothing was running" and "I was not looking" have different shapes in this log.

## DISCARD RULE — fixed in advance, so it cannot be fitted to a result I dislike
1. An arm whose window contains a sampler GAP > 60s is DISCARDED and re-run.
   Its conditions are unattributable. This is the ONLY contention-based discard.
2. An arm whose window contains a tier from a tree OTHER than
   lupin-wt-tiberius-moveprobe or lupin-wt-rachel-tier-seatscan is NOT discarded.
   The extra tree is NAMED in the report. The failing SET is the observable and it is
   not a timing quantity.
3. Contention is NEVER grounds to discard an arm merely because I dislike its result.
4. The sampler EXPLAINS an arm. It cannot RESCUE one. (maria, 18:47)

## HOW A DETERMINISM-GATE TRIP WILL BE READ — decided now, not after
If S_A1 != S_A2 the driver halts before C, per maria. The report will then say:
- contention record for A and for A2, side by side, and whether the TREE SETS MATCHED.
- If MATCHED  -> the trip is evidence of SUITE NONDETERMINISM. That is a bigger finding
  than the row and I report it as such.
- If DIFFERED -> the trip is AMBIGUOUS between suite nondeterminism and differing box
  conditions. I will say the corruption question is UNANSWERED on this run. I will NOT
  call the suite flaky, and I will NOT call it clean.
