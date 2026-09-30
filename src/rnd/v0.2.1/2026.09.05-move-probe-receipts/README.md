# Move-probe receipts — read this before you compare anything in here

Row `b97cacb7` (arms A/A2/B/C) and row `8f45897c` (arms RBASE/RTIP). **One harness, two jobs** —
same runner (`arm.sh`), same probe worktree, same pins; the two jobs' shas do not intersect, so
there is no shared data to report over. Report them as two results.

## 🔴 RENAMED FILES — THE OLD NAMES, BECAUSE THEY ARE IN RICK'S RECORD

María 🌸 quoted the arms to Rick all evening as **A / A2 / B / C / RBASE / RTIP**. Those arm NAMES
are unchanged and still correct everywhere. Only two FILENAMES moved:

| old filename | new filename |
|---|---|
| `A.failset` · `A.meta` · `A-tail.log` | `A-PARTIAL-DO-NOT-COMPARE.{failset,meta}` · `A-PARTIAL-DO-NOT-COMPARE-tail.log` |
| `RNEW.failset` | `TIP-MINUS-BASELINE-EMPTY-BY-DESIGN.failset` |

**Arm A is still arm A.** Its pytest numbers are complete and quotable. What is renamed is the FILE,
so that its partial CONTENTION column cannot be picked up by accident.

## 🔴 TWO FILES IN HERE ARE TRAPS. BOTH ARE RENAMED SO THE NAME CARRIES THE WARNING.

| file | what it is | why it was renamed |
|---|---|---|
| `A-PARTIAL-DO-NOT-COMPARE.*` | arm A — **PARTIALLY OBSERVED**, 15 contention samples against ~38 expected | its sampler did not exist until ~7.5 min into the run. Its *pytest* numbers are complete and fine; its **contention column is not**, and the two sit in the same directory looking alike. **Do not use A as a comparator for anything load-related.** Use A2 — same sha, same result, fully observed 38/38 |
| `TIP-MINUS-BASELINE-EMPTY-BY-DESIGN.failset` | the tip-minus-baseline set for `8f45897c` | it is **0 bytes, and that is the correct answer** — no test fails at the tip that did not fail at the baseline. Sitting unlabelled beside five full failsets, an empty file reads as a crashed arm. It is not |

## The six arms

| arm | sha | collected | passed | failed | wall | ms/test | contention samples |
|---|---|---|---|---|---|---|---|
| A | `35590594` | 22527 | 22452 | 3 | 761.33s | 33.80 | ⚠️ **15 / ~38 — PARTIAL** |
| A2 | `35590594` | 22527 | 22452 | 3 | 758.09s | 33.65 | 38 / 38 full |
| B | `be1d58b2` | 22548 | 22473 | 3 | 783.08s | 34.73 | 40 / 40 full |
| C | `35590594`→`be1d58b2` | 22527 | 22452 | 3 | 756.74s | 33.59 | full |
| RBASE | `8bfb1eac` | 22407 | 22332 | 3 | **1017.56s** | **45.41** | 51 / 51 full |
| RTIP | `ac37ea90` | 22592 | 22517 | 3 | 785.15s | 34.75 | full |

**All six failing sets are byte-identical**: md5 `005c2f6db9774e2bada637114a997bc2`, three known reds
(two deliberate `test_secret_scan` rotation holds + one `test_terraform_invariants` worktree
artifact). Six arms, one hash.

## 🔴 The wall-time story, and how it reversed twice

**RBASE is the lone outlier and it is NOT a property of its branch.** Five arms cluster at
**33.59 – 34.75 ms/test**; RBASE alone sits at **45.41**, +31% over the next slowest.

`ac37ea90` **is a descendant of** `8bfb1eac` — `git merge-base --is-ancestor` = YES, 88 commits,
174 files, +9951 / −422 — and it runs at **34.75**, in the pack. So "that branch is slow" is dead:
the same branch, 88 commits later, is normal.

⚠️ **WHY RBASE was slow is UNMEASURED.** It was the first arm run after checking out a tree 188
files and −11,274 lines away from the previous one, so a cold page cache is a *candidate*. Nobody
measured it. **Do not write the `because`.** The discriminating run is cheap — re-run `8bfb1eac`
now that its tree is warm — and it has not been done.

⚠️ Note also that **RBASE had the LOWEST load of any arm** (mean 4.03, min 1.95) and was still the
slowest. A contention story has to explain that, and cannot.

## Contention means, re-derived from `contention.log`

| arm | mean load1 | min | max | n |
|---|---|---|---|---|
| A | 5.15 | 3.92 | 6.37 | ⚠️ 15 (partial) |
| A2 | 4.23 | 3.30 | 5.75 | 38 |
| RBASE | 4.03 | 1.95 | 5.93 | 51 |

## What was NOT run, and why

🔴 **THE DISCRIMINATING ARM WAS NOT NEEDED BECAUSE THE SET WAS EMPTY — which is a different
statement from "we did not run it", and only the first one closes the question.**

Measured, `comm` run in BOTH directions over the two sorted failsets:

| | count | members |
|---|---|---|
| NEW at the tip, absent at the baseline | **0** | *(none)* |
| present at the baseline, GONE at the tip | **0** | *(none)* |

⇒ The conditional third tier (`82241ff8` → `297d710c`) had **nothing to attribute**. Mr. Radio's
standing authorisation was **declined on its own condition**, not skipped for convenience, not
skipped for box time, and not skipped because anyone disliked the answer. Had the set been
non-empty, the arm would have run under that standing authorisation without re-asking.
