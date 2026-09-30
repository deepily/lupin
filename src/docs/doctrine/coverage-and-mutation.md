# Doctrine — coverage and mutation

> What a coverage number cannot see, and how a mutation harness lies in both directions.
>
> **What this file is.** These are the RECEIPTS behind rules that live in `CLAUDE.md`.
> Each entry was moved here verbatim on 2026-09-08 (sha `ed653c8b`, row `f1400995`) so the
> combined `CLAUDE.md` would fit under Claude Code's 150,000-char load limit. **Nothing was
> deleted.** The operative rule — the command, the table, the ⇒ ruling — stayed inline where a
> seat acts on it; what moved is the measurement narrative that explains why the rule is believed.
>
> **Read this when** you want to check a rule against its evidence, when you are about to change
> or retire one, or when you doubt a figure. **You do not need to read it to follow the rule.**


---

## Pyc invalidation — the verifier, the purge script, and the three states

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 THE CHECKED-HASH VERIFIER SCANS `$LUPIN_ROOT/src`, NOT WHERE YOU ARE STANDING

Found by Tiberius 👑 while reviewing a peer's mutation pass, 2026-08-30; cleared by Rachel 🕊️.
`migrate-pyc-to-checked-hash.sh` takes its target from **`$LUPIN_ROOT/src`** (`TARGETS=(
"$LUPIN_ROOT/src" )`), never `$PWD`. Run it from a worktree with `LUPIN_ROOT` still naming the main
repo — **the default, since the variable is inherited from your shell** — and it blesses the MAIN
REPO, then prints its checkmark about a tree you are not testing:

```
$ cd <a worktree> && ./src/scripts/migrate-pyc-to-checked-hash.sh --verify
  scanned roots:
      /mnt/DATA01/include/www.deepily.ai/projects/lupin/src      <-- THE MAIN REPO
  every pyc THIS interpreter reads is checked-hash
```

A "checked-hash verified in the worktree" certification was made against the wrong tree this way.

⚠️ **AND `LUPIN_ROOT="$PWD"` ALONE DOES NOT RELIABLY FIX IT — WHAT YOU GET DEPENDS ON THE WORKTREE**
(Rachel 🕊️ caught this contradiction; measured both ways at `3019fed9`):

| worktree | `LUPIN_ROOT="$PWD"` alone |
|---|---|
| **has** its own `.venv` | **exit 1** — the real answer: this tree has timestamp pycs |
| **no** `.venv` (29 of 75) | **exit 2** — `ERROR: no interpreter at …/.venv/bin/python`; nothing was checked |

An earlier cut of this section claimed a flat "exits 1", which **contradicted its own next paragraph**
— the one explaining that `PYTHON` is derived from `LUPIN_ROOT`, so pinning only the root repoints
the interpreter at a venv the worktree does not have. ⇒ **Pin both, as below.**

⇒ **This is worse than an unconverted tree, because it is an unconverted tree wearing a checkmark.**
The script's own output names its scanned roots — **read that line, not the verdict.**

**To diagnose a tree you have already used, pin BOTH the root and the interpreter.** `LUPIN_ROOT`
alone is not enough: `PYTHON` is *derived* from it, so pinning only the root repoints the interpreter
at a venv the worktree does not have.

```bash
LUPIN_ROOT="$PWD" \
PYTHON="$( dirname "$( git rev-parse --path-format=absolute --git-common-dir )" )/.venv/bin/python" \
  ./src/scripts/migrate-pyc-to-checked-hash.sh --verify
```

`git-common-dir` resolves to the MAIN checkout from inside any worktree, so this needs no hardcoded
path and works from every tree.

🔴 **DO NOT QUOTE THE VENV-LESS COUNT — RE-DERIVE IT.** Three figures appeared in one evening
(29/74, 29/75, 30/76) and **all three were correct when taken**; the population changes as seats come
and go, so a quoted ratio is a rumour with a timestamp. Same rule as *a coordinate is not a
reference* — **ship the command, not the number**:

```bash
git worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r w; do
    [ -x "$w/.venv/bin/python" ] || echo "$w"
done | wc -l
```

Snapshot for scale only, **not to be quoted**: **30 of 76** at 2026-08-30 22:44 EDT, excluding the
six `.claude/worktrees/tfe-*` harness trees (82 and 36 including them — say which you mean). The
ratio has stayed near two in five across every measurement, which is why the `PYTHON` pin is not
optional.

⚠️ **Exit 2 at least fails LOUDLY** — it never prints a verdict, so unlike the unpinned run it cannot
certify the wrong tree. The three-way exit-code table is above.

🔴 **AND `purge-pycache.sh` ACCEPTS NO `--verify` — IT IS A DESTRUCTIVE COMMAND WEARING A READ-ONLY
NAME.** It tests only `$1 == "--dry-run"`; anything else is silently ignored and it **purges**. It
also runs under `set -uo pipefail` **without `-e`** and never checks its `rm`, so it can print
`Permission denied` and still **exit 0** — a caller reading `$?` sees success. **The read-only
verifier is `migrate-pyc-to-checked-hash.sh --verify`.** (Fix in review, row `3ac368b4`.)

⚠️ **Never run a mutation harness inside a peer's LIVE worktree** — it writes to their source. Check
the sha out into a detached worktree of your own. Learned in this same review: the peer lost nothing,
but the restore control read a dirty tree.


⇒ Three ways a tree drifts back, all one mechanism: a **new** `.py` file, a **purged**
`__pycache__`, or a module **imported for the first time** since the last conversion. Measured live
2026-08-30 — a verify run minutes after a clean conversion found exactly one offender,
`src/cosa/utils/coverage_contention.py`, which had reached this working tree on a peer's commit and
was imported before the next conversion. The gap is not theoretical; it fired inside the hour.

⇒ **Re-run the script after adding Python files or purging a cache; `--verify` when you want to know
rather than assume.** It exits non-zero if this interpreter would read a timestamp pyc.

🔴 **REVERSED 2026-08-30 — ISOLATE EVERY ARM. A CONVERTED TREE DOES NOT PROTECT A MUTATION LOOP.**
This paragraph used to read *"the per-harness purge is now the FALLBACK, not the instruction"*, on
the reasoning that a checked-hash tree can be trusted. **Four seats disproved it independently in
one evening**, on two different branches, and the reasoning was wrong for a mechanism this page
already documents two paragraphs above.

**CONFIRMED AT THE BYTE LEVEL** (Tiberius 👑). In a fresh worktree the pyc header reads **`flags=0`,
timestamp-based** — a worktree starts with no `__pycache__`, and a pyc written where none existed
has no mode to inherit. Timestamp validation compares whole-second mtime **and size**; swapping two
names inside an f-string changes neither — **6,533 bytes before and after** — so the interpreter
serves the PREVIOUS arm's bytecode against the RESTORED source.

| seat | receipt |
|---|---|
| Tiberius 👑 | byte-identical source: **7 failed** with the stale pyc, **18 passed** after removing one file. One arm read **KILLED** without a per-arm purge and **SURVIVED** with it — and he **retracted an approval** over it |
| Rachel 🕊️ | a test failed **deterministically four times** — under coverage, without it, in isolation — then passed permanently after a purge, **unreproducible** |
| Rio ⚡ | `purge-pycache.sh`'s reconvert needs `$LUPIN_ROOT/.venv/bin/python`; **35 of the repo's 80 worktrees lack it**, so there a purge leaves the tree on timestamp invalidation |
| Krishna 🦚 | corrected the first cut of this rule: **a harness that rebuilds its sandbox per arm is already isolated** and needs no purge |

🔴 **CORRECTED 2026-08-30, THE SAME EVENING IT WAS WRITTEN. "ONE PYTEST RUN UNDOES THE CONVERSION"
IS FALSE — THE REAL HAZARD IS A TREE THAT WAS NEVER CONVERTED.** Four seats measured this from four
directions and the reconciliation is the useful part: **a conversion STICKS; what does not exist
cannot stick.**

**Maya 🌻 disproved the original claim** with a probe module and a two-directional negative control —
a real source module, imported by a real pytest run, then mutated same-size with mtime restored so
neither size nor whole-second mtime moves:

| | |
|---|---|
| source pyc after convert | checked-hash |
| source pyc **after an ordinary pytest run** | **checked-hash — UNCHANGED** |
| convert → pytest → mutate → fresh import | **returns the mutated value — protection HOLDS** |
| negative control on a timestamp pyc | serves **stale** bytecode — so the probe *can* see the failure |

**Pytest's rewriting is a DISJOINT set**, which is what made two honest counts look contradictory:
it writes `…cpython-313-pytest-8.4.2.pyc`, which never replaces `…cpython-313.pyc` and is not read on
a normal import. One seat counted the population that matters for mutation and found it unchanged;
another counted a set that starts empty and grows. **Both were right.**

**And yet Clayton 😎 and Tiberius 👑 really did see a fresh worktree go `--verify` 0 → 1 after one
ordinary run**, with `src/scripts/__pycache__/bounce_dev_warn.cpython-313.pyc` heading the offender
list. Not a contradiction — **their trees had never been converted.** Measured across three real
trees the same night, `src/` only, `cpython-313` normal-import pycs, vendored trees excluded:

| tree | checked-hash | TIMESTAMP |
|---|---|---|
| **main checkout** (converted with `-f`) | **2452** | **0** |
| a converted worktree | 2434 | 1 |
| **an unconverted worktree** | **0** | **724** |

⇒ **THERE ARE THREE STATES, NOT TWO** (Pocholo 📣 — a two-state headline hides the middle one,
which is where people are actually standing):

| tree | `--verify` | what it MEANS |
|---|---|---|
| **fresh, never used** | **0** | 🔴 **VACUOUS — nothing there to judge.** Not a conversion |
| **fresh, then one ordinary run** | **1** | timestamp pycs, written where none existed — no mode to inherit |
| **converted AND populated** | **0** | ✅ genuine — an ordinary run does **not** undo it |

**The first and third both print `0` and mean opposite things.** That is why *"I verified, then
mutated"* protected nobody: the reader saw state 1, believed state 3, and mutated in state 2.

⚠️ **A live residual survives in state 3** (Clayton 😎): a module **imported for the first time since
the last conversion** arrives timestamp-based even in a converted tree, because it too has no prior
pyc to inherit from. Conversion is not a permanent property of a tree; it is a property of the pycs
that existed when you ran it.

⇒ **CONVERT A NEW WORKTREE BEFORE YOU TRUST IT.** Use it once, then purge-and-reconvert, *then*
verify. A verify on an unused tree is not evidence.

🔴🔴 **HISTORICAL — `purge-pycache.sh` USED TO MUTATE THE MAIN REPO FROM INSIDE A WORKTREE. FIXED;
DO NOT PIN `LUPIN_ROOT` FOR IT ANY MORE.** Kept because the diagnosis below is the durable half and
the stale remedy is still in people's fingers. **Found and documented by Pocholo 📣 at ~17:52 EDT**
(`TODO.md` § *purges the wrong tree … and prints its success banner anyway*); independently re-derived
by Rachel 🕊️ five hours later, who then **declined the credit and pointed at his entry**. The script
*then* read `LUPIN_ROOT="${LUPIN_ROOT:-<derived from BASH_SOURCE>}"` — the fallback was right, but **a
set variable wins**, and every seat's shell has `LUPIN_ROOT` pointing at the MAIN checkout. The `find
"$LUPIN_ROOT/src"` below it, and the reconvert it chains to, inherited that resolution.

⇒ Run it from a worktree and it purges and reconverts `/…/lupin`, **prints its success banner**, and
leaves your worktree exactly as poisoned as it found it.

⚠️ **THE SUCCESS BANNER IS THE WHOLE PROBLEM** — this is the wrong-tree family's signature: not a
crash, a **confident verdict about a tree you were not asking about.**

🔴 **THE FIX LANDED — `5e7f74e8` (with `0c0d0d15`, `ee91fefc`, `9fbe8f19`). THE TARGET CANNOT BE
STEERED, AND THE `LUPIN_ROOT` PIN IS NOW A NO-OP.** The paragraph above described a real defect and
predicted its own expiry; this is the re-cut it asked for. `purge-pycache.sh:48` now derives the root
from `BASH_SOURCE` **unconditionally**, and the script's own header says `$LUPIN_ROOT IS NOT
CONSULTED`. Verified 2026-09-01 by reading the shipped script, not by running it.

⇒ **THE ONE WAY TO AIM THIS SCRIPT IS TO RUN THE COPY THAT LIVES IN THE TREE YOU MEAN.** The remedy
that circulated while this was broken — `LUPIN_ROOT="$PWD" src/scripts/purge-pycache.sh` — still gives
the right answer, but **for the wrong reason**: the prefix does nothing at all now, and what made it
correct was that you were standing in the tree whose copy you ran. **Harmless to keep typing;
misleading to keep believing.** That distinction is the whole point — a reader who believes the prefix
aims the script will run the MAIN repo's copy from a worktree and purge the main repo, which is the
exact defect this section exists to prevent, reached by obeying its own stale remedy.

⚠️ **`PYTHON` IS STILL LOAD-BEARING AND THE FIX DOES NOT COVER IT.** It defaults to
`$LUPIN_ROOT/.venv/bin/python` — now the *script's own* tree — so in a worktree with no `.venv` (Rachel
🕊️ measured 30 of 76) the **purge half succeeds and the reconvert half exits 2**:

```
Purging 1 __pycache__ directories under src/ …
Reconverting to checked-hash — WITHOUT THIS STEP THE PURGE SILENTLY REVERTS THE TREE …
ERROR: no interpreter at …/headwt/.venv/bin/python
EXIT=2
```

The caches are **gone and unreconverted** — precisely the half-done state the script exists to
prevent. **Read the exit code**, and pin the interpreter when the tree lacks one:

```bash
# from a worktree with no .venv — pin the INTERPRETER only. LUPIN_ROOT is inert here.
PYTHON="$( dirname "$( git rev-parse --path-format=absolute --git-common-dir )" )/.venv/bin/python" \
  src/scripts/purge-pycache.sh
```

⚠️ **The two variables answered different questions and only one survives** — *which tree do I clean*
is now settled by the script's own location; *what do I run `compileall` with* is still yours to pin.

⇒ **Two harms, and the second is the quiet one.** It reaches into a shared tree other seats are
working in; and it leaves you **believing you isolated a mutation arm that you did not**. A seat
reported exactly that tonight — repeated per-arm purges from inside worktrees, every one of them
landing on the main repo.

⇒ **The wrong-tree family now has three members** (verifier, purge script, and the tier itself, see
§ TESTING VENUES). Anything that resolves `$LUPIN_ROOT` is asking about *your shell*, not *your
location*.

**The proper fix is Pocholo's and it is one sentence**: these scripts should derive their root from
`BASH_SOURCE` **unconditionally**, because *a script shipped INSIDE the tree it cleans can only be
disagreed with by the environment, never informed by it.* Row `3ac368b4`.

🔴 **AND NOTE HOW LONG IT SAT.** It was written down, correctly and in detail, at 17:52 — and the
whole crew walked into it anyway for five hours, including a reviewer whose per-arm isolations all
went to the wrong tree. **A defect recorded in `TODO.md` is not a control**; only the code is. That
is the same conclusion three separate rows reached tonight from three directions.

⇒ **A clean verify in the MAIN repo says nothing about your worktree** — the verifier scans
`$LUPIN_ROOT/src`, not where you stand. See the wrong-tree section below.

⚠️ **STILL EXPOSED, unchanged**: editing a **TEST** file inside a test. Use
`tests.helpers.pyc_freshness` there.

⚠️ **Do not count `.pyc` files to check this** — Tiberius tried and corrected himself: the count
moves for ordinary reasons and tells you nothing about invalidation mode. **The verify status flip
is the measurement**; the file count is not.

⇒ **Isolate every arm.** The requirement is that **nothing carries between arms** — not that you run
a particular command:

| form | strength |
|---|---|
| **rebuild the sandbox per arm** — tree, scripts and caches together | ✅ strongest: nothing survives *by construction*, so there is no cache to forget |
| `src/scripts/purge-pycache.sh` between arms | good, and the practical choice in a working tree |
| a raw `find … __pycache__ -delete` between arms | 🔴 **RE-OPENS THE DEFECT** — see below |

🔴 **A RAW PURGE INSIDE A MUTATION HARNESS MANUFACTURES THE BUG IT IS THERE TO PREVENT** — measured
by Pocholo 📣, 2026-08-30, as a **false survivor**. His harness isolated arms with
`find … __pycache__ -delete`, which deletes the *checked-hash* caches; the next import rebuilds them
**timestamp-based**, because a pyc written where none exists has no mode to inherit. **The isolation
step put the tree back into exactly the state the isolation existed to prevent**, and nothing in the
output said so. ⇒ **Use the script — it purges AND reconverts, so the halves cannot come apart.**

⚠️ **Do not read this as requiring a purge you do not need.** Krishna's arms rebuild from scratch
each time and are already isolated; demanding a purge there would be cargo cult.

🔴 **AND IT IS A REVIEWER'S OBLIGATION, NOT ONLY AN AUTHOR'S** (Rachel 🕊️). An author can isolate
every arm perfectly and a reviewer re-running the suite in a shared tree still gets served stale
bytecode — which is exactly how both of tonight's sightings reached a reviewer rather than an
author. ⇒ **Before you approve on a green you watched turn, or red you cannot explain, isolate and
re-run.** A deterministic failure that vanishes after a purge is not flaky and is not fixed; it is
the instrument, and saying so is a finding rather than a shrug.

⇒ **`--verify` before a pass is necessary and NOT sufficient** — it describes the tree you started
with, not the one you are measuring in.
⇒ **`-B` / `PYTHONDONTWRITEBYTECODE` still buys the appearance of safety, not safety** — it
suppresses *writing*, never *trusting*, and a repo that has run its tests already has the cache.
⇒ ⚠️ **Rio's finding makes the purge remedy conditional**: in a worktree with no `.venv` the purge
half succeeds and the reconvert half does not. **Check the purge's exit code** rather than assuming
it did both.

**What the retraction cost and what it bought.** Two mutation passes reported earlier that evening —
a 7-for-7 and a 10-for-10 — became **UNREADABLE, which is not the same as WRONG** (Tiberius's
distinction, and it is the one to defend): a number taken in a tree whose bytecode can serve the
previous arm establishes nothing **in either direction**. It is not evidence the tests are weak, and
it is not evidence they are strong.

⇒ **Re-run such a pass WITH EVERY ARM ISOLATED — never simply re-run it.** The failure was not bad
luck that a second attempt averages out; re-running in the same tree reproduces the same instrument.
**That is why the remedy is isolation and not repetition**, and it is the whole reason this rule
names a property rather than a command.

See row `d18ce9ef` and Pocholo's write-up
`src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md` for the six priced remedies.
⚠️ **That write-up's "+3.3% import cost" is an ANALYTIC figure and did not survive measurement on the
real tier** — see `866f43ce` for the observed numbers. Quote the row, not the 3.3%.

⚠️ **THE HAZARD IS NOT LIMITED TO MUTATION HARNESSES, AND IT IS CROSS-PROCESS.** A *fresh* pytest
reads the stale pyc off disk, so any edit-then-run loop is exposed — including one an agent types by
hand. Mutation testing is merely where it lands hardest, because mutate-and-restore are both
same-size edits inside one second and **the failure points the wrong way**: you restore the file,
read it back to confirm, and the interpreter keeps running the mutant.

**Provenance, because three seats measured this independently and the numbers must be comparable**:
found by Pocholo 📣 while mutation-proving AC-G4, filed and reproduced by Tiffany 💍 on row
`d18ce9ef`, and reproduced a third time from the ramp (rows above). ⚠️ **The two published
reproductions run OPPOSITE POLARITY** — one edits `"todo"` → `"dead"`, the other `"dead"` → `"todo"`
— so the "wrong" answer is a different word in each. They agree completely: in both, the flag serves
the pre-edit value. Do not read the mirrored tables as a conflict.

⚠️ **THE BYTECODE FAILURE IS SELECTIVE, WHICH IS WHAT MAKES IT DANGEROUS.** A length-changing swap
invalidates the cache on its own, so most mutations in a pass are unaffected — 11 of 12 in the
measured case. **A harness looks healthy while lying about exactly the mutations that leave mtime
and size unchanged.** Re-verification is cheap and worth doing on any pass that predates this rule:
re-running an unpurged 10/10 with the purge in place reproduced 10/10 with identical mutated shas,
so that pass held — but it was not KNOWN to hold until it was re-run.

⇒ **A SURVIVING MUTANT HAS THREE EXPLANATIONS, NOT ONE.** Separate them before writing a line of
test code:

| Explanation | How to tell | Cost of getting it wrong |
|---|---|---|
| **A weak test** | the other two are ruled out | the only one that earns a new test |
| **A broken harness** | re-run that ONE mutant by hand — if it reddens, the harness lied | you accept a lower kill count as the file's ceiling |
| **An equivalent mutant** | read the edit: did it repair its own damage? | you write a test to kill something that was never a defect |
| **A fixture that cannot discriminate** | read the DATA, not the assertions | you audit correct assertions, find nothing, and conclude the code is fine |

Measured example of the third: an edit that dropped an `if row.get( "id" )` guard **and** swapped
`row[ "id" ]` for `row.get( "id" )` in the same change turned a `KeyError` into a harmless `None`
key. The mutation was wrong, not the test. **Reaching for "weak test" first is how a seat rewrites
tests that were already fine.**

🔴 **THE FOURTH IS THE ONE YOU CANNOT REACH BY READING THE TEST** (Krishna, row `9ad838d6`). The
assertions can be present, correct, and named for exactly the thing that broke, while the FIXTURE
cannot tell the difference: **values that are interchangeable in the data cannot reveal a swap
between them.** Measured — `migrated=1` and `skipped=1` made a counter swap invisible, because
swapping two equal numbers changes nothing; `2 / 1 / 1` kills it. The generalisation is worth more
than the case: **if two quantities can be exchanged without changing the expected output, the test
asserts their SUM, not their identity — whatever its name says.** The remedy is the fixture, never
the assertions, and an assertion audit passes it clean every time.

**TWO MORE WORKED EXAMPLES from the same evening**, both found by mutations surviving a suite whose
assertions read correctly, and both fixed in the FIXTURE rather than the assertions. They are
written out in full because the abstraction above is the part a reader skips; the shape is what
gets recognised.

**(a) The fixture agrees with the environment.** Testing that an empty `LUPIN_ROOT` falls through
to the file-relative fallback rather than becoming `Path( "" )`:

```python
# SURVIVED a mutation that returned Path( "" ) instead of the real root
assert ( root / "src" / "scripts" / "watch-hook-events.py" ).exists()

# KILLS it — Path( "" ) is RELATIVE, and only resolves right from the repo root
assert root.is_absolute()
assert root == Path( whe.__file__ ).resolve().parents[ 2 ]
```

`Path( "" ) / "src" / …` is a relative path, and pytest runs from the repo root, so **the wrong
answer and the right answer named the same file.** The assertion was measuring the CWD.

**(b) The fixture already sits at the boundary it is testing.** Testing that a one-digit seconds
field is zero-padded:

```python
# SURVIVED a mutation removing .zfill( 2 ) — "abc" has no digits, so ss is already "00",
# two characters, and the padding is a no-op either way
assert whe._hhmmss( "2026.06.06 @ 01:45 abc" ) == "01:45:00"

# KILLS it — only a ONE-digit value separates 01:45:07 from 01:45:7
assert whe._hhmmss( "2026.06.06 @ 01:45 7ms" ) == "01:45:07"
```

Both tests were named for the thing that broke. Neither could see it.

⇒ **When a mutant survives, look at the DATA before the assertions.** Three of the four readings
are invisible to a careful re-read of the test body.

**Still the floor, unchanged**: every mutation asserts it APPLIED before its result is trusted — the
anchor matched EXACTLY once, and the on-disk sha CHANGED — plus a restore control at the end that is
actually READ, since `git checkout` cannot restore an untracked file (row `c0a829a3`).

🔴 **AND `cp` FROM YOUR OWN BACKUP CARRIES THE SAME RACE AS THE `git checkout` YOU WERE TOLD TO
AVOID — IN A SHARED TREE, SWAPPING THE COMMAND KEEPS THE HAZARD.** Krishna 🦚, 2026-09-01, on his own
arm. The `git checkout` ban exists because a path-level restore silently reverts a peer's uncommitted
work to HEAD. A `cp` restore reverts it to **your backup** instead, which is better only in that your
backup already contained whatever the peer had written **before** you took it. **Anything they write
between your backup and your restore is reverted just the same, and leaves no reflog entry either.**

⇒ **The window is the mechanism, not the command.** Mine was ~90 seconds and the check afterwards
came back clean — 69 insertions, **0 deletions**, so nothing committed was lost, and two peers
confirmed no intersection. ⚠️ **But "no known loss" is not a control**: a clobbered *uncommitted*
edit is invisible to git, so that check can only ever exonerate the committed half.

⇒ **So the remedy is not a shorter window or more care — it is not mutating in the shared tree at
all.** Check the sha out into a **detached worktree of your own** (this file already says so one
section down, for a peer's tree; it applies to the MAIN tree too, which is where the whole fleet is
standing). That removes the race by construction rather than shrinking it, and it is the same
"a rule that depends on remembering is not installed" doctrine this page applies everywhere else.


---

## A mutation harness can lie in both directions — the receipts

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A MUTATION HARNESS CAN LIE IN BOTH DIRECTIONS — READ A SURVIVOR THREE WAYS

Measured 2026-08-29 on the coverage ramp (rows `ba6df71e`, `3b78bc8a`). Two instrument defects in
one evening, both the same failure: **the harness reporting on an execution that never happened.**

**OVER-REPORT — a non-zero exit is not a red test.** pytest's rc 4/5 mean it could not RUN the node
(usage error / nothing collected). A harness counting any non-zero rc as a kill scores its own
misses as hits. Receipt: an rc=4 was recorded as a caught mutation; the test had been appended into
the wrong class and never ran. ⇒ **Accept only `rc == 1`.**

🔴 **AND `rc == 1` ITSELF FAILS ON A BRANCH THAT CARRIES A DELIBERATE RED — measured
2026-08-30.** The rule above assumes a GREEN baseline. `src/tests/unit/test_secret_scan.py`
holds two intentional reds (the rotation hold), so **the suite exits 1 before a single
mutation is applied**: under `rc == 1` every mutant scores as KILLED and the pass reports a
perfect result while measuring nothing at all. A 14-arm pass run that way would have read
14/14; judged properly it was **9/14**.

⇒ **The kill signal is the FAILING SET, not the exit code: killed iff a NAMED test that was
PASSING at baseline now fails.** `rc` 4/5 still means could-not-run and is never a kill.
This is not a departure from the rule — the exit code was only ever a *proxy* for "a test
that passed now fails", and the proxy breaks the moment anything is red on purpose.

⇒ **TAKE THE BASELINE FIRST, ALWAYS, AND RECORD THE NAMES.** It costs one run, it is the
only way to tell a mutant's red from a red that was already there, and a harness that
skips it cannot distinguish a perfect score from a broken instrument. Two of tonight's
five survivors were **deliberate design decisions with their reasons in the file** —
readable only because the baseline said which reds were expected.

**STALE BYTECODE — a mutant can run as some OTHER revision of itself, and this one lies BOTH ways.**
CPython validates a cached `.pyc` on the source's whole-second mtime and size. A mutation changing
NEITHER — single-character and digit swaps, `return 3` → `return 0`, `<` → `>` — landing in the same
second as the cached compile is judged unchanged, so the cached bytecode runs instead.

- **False SURVIVOR**: the ORIGINAL bytecode runs, the test passes because the original is correct,
  and the mutation reports SURVIVED. Receipt: the same mutated sha `ab030e258b72` gave rc=0 through
  a harness and rc=1 run by hand seconds later, the only variable being bytecode caching.
- **False KILL**: in a SEQUENTIAL harness over one file, run N+1 can load run N's bytecode. The
  suite then fails on the PREVIOUS mutant and the harness records a kill the CURRENT mutant never
  earned. Mechanism and retraction on row `cfe0b15d` — the narrower "only fakes survivors, so an
  all-killed pass is safe" was believed briefly and is WRONG for the loop shape every ramp harness
  uses. ⇒ **Purge on EVERY pass, not only one that reports a survivor.** An all-green pass is
  exactly the one that looks like it needs no checking.

🔴 **`python -B` / `PYTHONDONTWRITEBYTECODE=1` DOES NOT FIX THIS.** It suppresses *writing* a
`.pyc`, never *trusting* one — and any repo that has ever run its tests already has the cache on
disk. **The structural remedy is checked-hash invalidation** (`py_compile.PycInvalidationMode.CHECKED_HASH`
/ `compileall --invalidation-mode checked-hash`), which hashes the source instead of comparing
whole-second mtime and size, and is therefore immune to a same-size same-second edit by
construction.

🔨 **RICK RULED YES — 2026-08-30, decision `866f43ce`. Checked-hash goes repo-wide.** Convert your
tree with `src/scripts/migrate-pyc-to-checked-hash.sh`; `--verify` reports without changing anything.

🔴 **"EXITS NON-ZERO" WAS WRONG — READ THE CODE, THERE ARE THREE** (Rachel 🕊️ and Tiberius 👑,
2026-08-30). This line used to say `--verify` "exits non-zero if any pyc is still timestamp-based",
which welds a real answer to a failure-to-answer:

| exit | meaning |
|---|---|
| **0** | every pyc this interpreter reads is checked-hash |
| **1** | ⚠️ **the real finding** — timestamp pycs are present |
| **2** | **it never ran** — **three** conditions share this code: unknown option · root is not a directory · no interpreter at `$PYTHON`. Each prints a distinct message to **stderr**, so the message is the only discriminator — capture stderr, or you cannot tell them apart |

**Exit 2 is common, not exotic**: `PYTHON` defaults to `$LUPIN_ROOT/.venv/bin/python`, and **roughly
two in five worktrees have no `.venv`** — so a reader treating any non-zero as "vulnerable tree"
mis-reads a script that never started. **Re-derive the ratio rather than quoting one; see below.**

```bash
# in a worktree without its own .venv — name the interpreter
PYTHON=/path/to/a/real/python src/scripts/migrate-pyc-to-checked-hash.sh --verify
```

⚠️ **And a `1` from that form is the CORRECT answer, not a failure** — it means the tree genuinely
holds timestamp pycs, which is the question you asked.

⇒ **Same defect as `purge-pycache.sh`'s exit 2** (Krishna 🦚, same evening, other script): *two
failure modes sharing one exit code, wanting opposite remedies* — fix your command line versus build
a venv. Where a script can distinguish them, **distinct exit codes beat distinct messages**: a code
is a contract, a message drifts.

🔴 **THE `-f` IS THE WHOLE MIGRATION, AND WITHOUT IT THE COMMAND CONVERTS NOTHING WHILE REPORTING
SUCCESS.** Measured 2026-08-30 — do not retype the command from memory without it:

```
python -m compileall    --invalidation-mode checked-hash .   ->  pyc stays TIMESTAMP
python -m compileall -f --invalidation-mode checked-hash .   ->  pyc becomes checked-hash
```

compileall treats an existing up-to-date `.pyc` as needing no work. **Any tree that has ever run its
tests is already full of timestamp pycs**, so the un-forced command leaves every one of them exactly
as it found it — the setting "changed" and the tree is still vulnerable. The script passes `-f`.

⚠️ **NOT CONVERT-ONCE-AND-FORGET, and the two halves pull opposite ways** (both measured):
an **existing** checked-hash pyc **stays** checked-hash — edit the source, re-import, and CPython
regenerates it in the same mode, so no build step is needed on every run. But **a pyc written when
no prior pyc exists is TIMESTAMP-based**, because there is nothing to inherit a mode from.

🔴 **WHICH MEANS THE OLD PURGE HABIT NOW RE-OPENS THE HOLE IT USED TO PLUG.** A raw
`find src -name __pycache__ -exec rm -rf {} +` deletes the checked-hash caches, and the next import
silently rebuilds them as **timestamp**. The tree is then back to the original defect with nothing in
any output saying so. This is the most likely way a converted tree regresses — the instruction people
already have in their fingers is now the thing that breaks it.

⇒ **THE FIX IS A SCRIPT, NOT A RULE: use `src/scripts/purge-pycache.sh`.** It purges *and*
reconverts in one command (~3.5s), **refusing up front if it cannot reconvert** rather than
discovering that after the delete. "Remember to reconvert after
purging" would be a habit, and this fleet's own doctrine is that a habit is not a control — the raw
command has been replaced everywhere it was documented (CLAUDE.md, `src/tests/README.md`, the three
`pyc_freshness` failure messages, and the mobile-parity test's remedy line) so the thing people copy
is safe by construction. Measured, both ways: after a raw purge plus one import the verifier reports
`timestamp=3`; after the script it reports every pyc checked-hash.


---

## Absorbed into the consolidated mutation rule — "I REPAIRED A FIXTURE" IS NOT

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 "I REPAIRED A FIXTURE" IS NOT "I PROVED THE REPAIR DISCRIMINATES" — TWO ARMS, ONE SHA

Ratified fleet-wide by Mr. Radio 🦉, 2026-08-30, after three seats produced it independently in
one evening. **A repaired fixture whose suite goes green has established NOTHING** — the suite was
green before, for a different reason. What establishes the repair is **two arms driven from ONE
mutated sha**:

| arm | required result | what it proves |
|---|---|---|
| the **OLD** fixture + the mutation | **SURVIVES** | the test genuinely could not see the behaviour it was named for |
| the **NEW** fixture + the *same* mutation | **KILLED**, by the named test | the repair is what closed it |

**One sha across both arms**, so the only variable is the fixture. **Neither arm alone counts**: a
lone red proves only that a test can fail, and a lone green proves nothing at all.

**Three clean instances, same evening**: Krishna 🦚 `88631dc1` (sha `7c8faf911d84`, SURVIVED before
the fixture reorder, KILLED after) · Chloé 🗼 `e23ef98c` (sha `914b6d4c0411`, 20 passed both ways on
the old fixture, killed by `test_a_vendored_path_under_src_is_still_rejected` on the new) · the
password-length repair on `migrate_mock_users.py` (sha `f83f1b901ade`).


---

## Absorbed into the consolidated mutation rule — AND `rc == 1` IS A KILL

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 AND `rc == 1` IS A KILL **ONLY ON A SUITE THAT IS GREEN AT BASELINE**

The rule above this one says to accept only `rc == 1`. **That is necessary and not sufficient**, and
the gap produced a false kill the same evening. A mutation returned `rc=1`, reddening
`test_the_flash_lite_arm_really_reaches_vertex` and `test_a_crossed_pair_is_refused` — it was nearly
recorded as KILLED. Run **unmutated**, the same two failed: they are two of the ten known worktree
artifacts from the gitignored `cloud-run.env`. **The failing SETS were byte-identical with and
without the mutation. It had SURVIVED, and the exit code said the opposite.**

⇒ **Assert the baseline is green BEFORE the mutation.** Comparing the failing SETS is the
FALLBACK for when you cannot get a green baseline, not an equal alternative to one — see the
next subsection for why a set comparison alone is not enough. 🔴 **A RESTORE CONTROL AT THE END IS NOT A BASELINE** (Rio ⚡, 2026-08-30, correcting
the first cut of this section). The floor rule above asks for a trailing unmutated run, and it is
easy to read that as discharging this one — it does not. A control that proves greenness only
*afterwards* cannot separate a false kill from a real one *during* the pass: every verdict was
already recorded by the time it runs. The baseline has to be taken **first**, or per-mutant. This is §TESTING VENUES' *"same SET beats same COUNT"* arriving in the mutation lane,
and it bites hardest **in a worktree** — which is where this fleet does all of its mutation work,
and where ten failures are present before anybody edits anything. ⚠️ It is not only a worktree
hazard: this branch's own unit tier was **RED for roughly four hours** on 2026-08-30 while several
seats mutated against it.


---

## Absorbed into the consolidated mutation rule — AND A FAILING SET COMPARES TEST IDS

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 AND A FAILING SET COMPARES TEST IDS — COMPARE THE ASSERTION THAT FIRED

Raised by Rachel 🕊️ and Mr Radio 🦉 independently, 2026-08-30, against the first cut of the
subsection above. That cut offered *"compare the failing SETS"* as an equal alternative to a green
baseline. **It is not one, because a failing set is a set of test IDs and a test id says nothing
about WHY the test went red.** The two errors point opposite ways and both are live:

| what you see | what you conclude | what may actually be true |
|---|---|---|
| mutated set = baseline set | **SURVIVED** | the mutation really did break a test that was ALREADY red for an unrelated reason — a false survivor |
| mutated set = baseline set + one | **KILLED** | the extra red is a flake or a second artifact — a false kill |

⇒ **Compare the assertion that fired, not only the test that failed** — the message, the line, the
short-summary line, anything that distinguishes one red from another red in the same test.

🔴 **AND THE SAME MECHANIC DECIDES WHETHER A NEW GUARD RUNS AT ALL.** A test's assertions execute in
sequence, so an assertion added BEHIND one that is currently failing is **present in the file and
absent from the run** — and the test id in the failing set is byte-identical whether the new guard
passed, failed, or never executed. **A guard placed behind a red is carried, not exercised.**
**Worked instance, this reviewer's own, with the fix and both measurements.** The counts guard added
to `test_a_detector_change_forces_a_full_rescan` at `503000fe` sat after that test's fingerprint
assertion, and the fingerprint is red in this tree (row `8202d795`). The commit reported the file as
*"1 failed, 60 passed — byte-identical failing SET to the baseline"*, which was true and told nobody
the new assertion had not run. The counts were stale the whole time — recorded 239/116 against a
scan measuring 240/117 — so the guard would have fired on its first execution and never got one.

| placement, same record, same scan | result | what the failing set says |
|---|---|---|
| guard INLINE, behind the fingerprint assert | 1 failed, 60 passed | one id — the stale counts are invisible |
| guard in its OWN test | **2 failed, 60 passed** | two ids — the second NAMES the counts |

⇒ **Before claiming a new assertion guards anything, prove it is REACHED** — force the assertions
ahead of it green, or **move it into a test of its own**, which is the durable form: a separate test
is what lets a failing SET carry information instead of collapsing several reasons into one id.


---

## Absorbed into the consolidated mutation rule —  AND A CLEAN PASS IS A SAMPLE

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### ⚠️ AND A CLEAN PASS IS A SAMPLE OF THE MUTATION SPACE, NOT A VERDICT ON IT

Six mutations against four files were run and reported as a pass. Clayton 😎's independent harness
then posed **40** against the same files and found **four survivors nobody had posed** — including
the one that mattered, a `site-packages` clause whose deletion left every test green. **The reviewer
had mutated that exact line and picked a different clause of it.**

⇒ A mutation pass reports on the mutations you thought of. **Two harnesses aimed at one file find
different things**, and that — not a matching sha — is the real argument for a second harness. A
cross-harness sha match establishes only **edit identity**: the same anchor and replacement against
the same source bytes is deterministic, so two correct harnesses *must* agree, and the match says
nothing about either verdict (Krishna 🦚, correcting this reviewer). **Exchange shas to catch a
DISAGREEMENT, never to manufacture a confirmation.**

Full derivation, with what each claim does NOT establish:
`src/rnd/v0.2.1/2026.08.30-two-harnesses-one-file-cross-reproduced-shas.md`.


---

## Absorbed into the consolidated mutation rule — A BREAK THAT DESTROYS ITS OWN SUBJECT

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A BREAK THAT DESTROYS ITS OWN SUBJECT REPORTS ZERO PASSED — AND ZERO PASSED IS THE MOST FLATTERING NUMBER A MUTATION ARM CAN RETURN

Pocholo 📣, 2026-09-02, on his own arm, caught before he banked it. **He deleted a dispatch line to
prove 32 re-pointed fixtures still guarded the route. The deletion left a dangling `else if`, the
file stopped parsing, and all three suites reported `0 passed`:**

```
holding_area   0 / 48        task_list   0 / 176        epic_board   0 / 71
```

⇒ **295 tests, every one of them "reddened", and the mutation measured nothing at all.** A
`SyntaxError` takes the whole file out, so no test ran — and a suite that never runs looks exactly
like a suite that unanimously caught you.

🔴 **HE CAUGHT IT BECAUSE THE NUMBER WAS TOO GOOD, NOT BECAUSE ANYTHING WARNED HIM.** Nothing in the
output says *the file did not parse*. The runner reports a count, the count is the best possible
count, and a seat looking for confirmation that its arm landed has just been handed it.

⚠️ **THIS IS THE NO-OP BREAK ARRIVING FROM THE OPPOSITE DIRECTION.** A no-op break changes nothing
and reports SURVIVED — flattering to the *code*. A subject-destroying break runs nothing and reports
killed-everywhere — flattering to the *test suite*. **Both hand you the answer you were hoping for,
and neither carries a warning.**

⇒ **SO PUT A CEILING ON A KILL COUNT, NOT ONLY A FLOOR ON IT.** A break aimed at one dispatch line
should redden the tests that reach that line — not every test in the file, and never every test in
three files. **A kill count at or near 100% of the corpus is a syntax error until proven otherwise.**
The cheap discharge: check the suite still COLLECTS — compare the RUN count against the baseline's,
not just the failure count.

⚠️ **And note which number discriminates.** `0 passed / 48 failed` and `0 passed / 0 failed` are
different worlds and both begin `0 passed`. **Read the denominator.**


---

## A fixture defect wearing the costume of the defect under test

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A FIXTURE DEFECT CAN WEAR THE COSTUME OF THE DEFECT UNDER TEST

Same pass, same author — and this one was caught by the suite rather than by him.

His bulk rewrite lost scope on `_controlScope`'s two-rows-one-id case: the new selector was
document-wide, so it found the **first** Submit on the page and sent the **first row's** text, which
is *precisely the failure that test exists to detect*. The test failed. It was right to fail. **And
what it was reporting was his fixture, not the code under test.**

⇒ **The wrong reading was available and comfortable: "my re-pointed fixture reddens ⇒ I have found a
defect in the implementation."** He had every reason to publish it as a finding about a peer's code.
**A weaker test — one asserting on rendered shape without clicking — would have let him.**

⚠️ **THE TELL IS THAT THE SYMPTOM MATCHES THE TEST'S OWN NAME TOO WELL.** When a fixture change
produces exactly the failure a test was written for, suspect the FIXTURE first: you have just
introduced a second cause for one observable, and § *UNGUARDED IS A THIRD STATE* says an assertion
satisfied by more than one path cannot tell you which one fired.

⚠️ **AND THE HONEST ARM SPLIT IS WHY THE REST OF THE PASS IS BELIEVABLE**: of the 32 re-pointed
fixtures, **20 redden on the break and 12 do not** — the 12 assert on rendered shape and never
click. He said so. **"All 32 guard the route" was available, unfalsifiable, and would have made the
whole number worthless.**


---

## A hand-written fixture is better-formed than reality — the porcelain receipt

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A HAND-WRITTEN FIXTURE IS NOT MERELY SIMPLER THAN REALITY — IT IS SYSTEMATICALLY BETTER-FORMED THAN IT, EXACTLY WHERE A PARSER DEPENDS ON THE MESS

Tiberius 👑, 2026-09-03, on his own parser. **Every synthetic fixture passed. The real input
failed. Nothing was wrong with the assertions, the coverage, or the fixtures — they were simply
tidier than the thing they stood in for, and the tidiness was the whole variable.**

**The receipt.** A `line[3:]` slice over `git status --porcelain` printed
`rc/cosa/utils/tree_state.py` — three characters eaten off `src/`. Porcelain lines begin with a
two-character status field and a space, so `line[3:]` is right. But `_git_reader` **strips the
whole output**, which removes the leading space from the **first line only**. That line then needs
`line[2:]`, and every other line needs `line[3:]`.

⇒ **A hand-built fixture keeps the leading space, because a person writing a fixture writes a
well-formed line.** The defect lives in exactly one place — the boundary between the reader and
the parser — and a fixture is authored on the parser's side of it.

🔴 **THE TELL IS THAT THE FIXTURE NEVER WENT THROUGH THE PIPE.** A test that constructs its input
is testing the parser against your *model* of the producer, not against the producer. Where the
two differ, the test agrees with your model — and your model is what was wrong, or there would be
no bug.

⇒ **So for any parser, capture at least one fixture FROM THE REAL PRODUCER, THROUGH THE REAL
READER**, and commit it. Not all of them — one is enough to catch a whitespace, encoding,
line-ending or ordering assumption that no hand-written line will ever carry.

⚠️ **AND NOTE WHERE THE DEFECT ACTUALLY SAT: NOT IN THE PARSER.** `line[3:]` is correct for
porcelain. The `strip()` is reasonable for a command reader. **Each half is right and the pair is
wrong** — which is why reading either file in isolation exonerates it, and why a fixture authored
from either half's point of view cannot see it.

⇒ Same family as § *COVERAGE MEASURES WHETHER A LINE RAN, NEVER WHETHER THE TEST COULD HAVE
NOTICED IT RUNNING WRONG* — there a fake ignores its input; here a fixture honours it, and is
simply a cleaner input than the world produces. **Both are green suites measuring the harness.**


---

## A number that describes a gate must ask the gate — the ratio-gate build

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A NUMBER THAT DESCRIBES A GATE MUST ASK THE GATE, NOT RESTATE ITS RULE — AND THE RESTATEMENT IS OFF BY ONE

> 🔨 **AMENDED 2026-09-05 — RICK OVERRULED THE PROJECTION FOR THIS BADGE, BY KEYPRESS AT
> 13:11:13 EDT.** Everything below is still the right default and still describes the code.
> What changed is that the **display** now deliberately reports **one less** than the gate
> admits, on the option labelled verbatim *"Keep your three states — badge under-reports by
> one."* A real keypress, not a timeout default; four options were put to him on row
> `307943fb`.
>
> ⇒ **The mechanism below is unchanged and is what makes the exception safe.** There is
> still exactly ONE comparison — inside `ratio_gate_advisory`. `ratio_loop_headroom`
> **subtracts from the gate's own answer** rather than re-deriving one, so the two cannot
> drift; the offset is a stated constant, not a second opinion. `ratio_gate_headroom` still
> exists, is still exact, and is still on the payload as `headroom`.
>
> 🔴 **AND THE REASON IT WAS WORTH ONE:** building to the gate **deleted a state he had
> ratified.** `FULL` means *N == 0, at capacity, still legal*; under the gate's framing
> headroom is 0 exactly when the gate already refuses, which is the `CLOSE N` state — so
> `FULL` had no inputs and would never once have appeared. **The exact number and the word
> `FULL` are one choice, not two.** A reader who "fixes" the off-by-one deletes `FULL`
> again, which is why both files say so where the fix would be typed.
>
> ⚠️ **So the rule below is not weakened — it is bounded.** A projection may differ from
> its gate **only** by an offset a human ruled, applied to the gate's own answer, and
> written where somebody would go to undo it. It may never differ because a second piece
> of code reached its own verdict.


Rio ⚡, 2026-09-05, on a ruling by Mr. Radio 🦉: **"headroom is a PROJECTION of the gate, never a
second gate. If your number ever disagrees with what the gate actually does, the number is wrong.
Build it so that is structurally true."**

**The shape.** A gate decides something. Somebody wants to DISPLAY how much room is left before it
refuses. The obvious implementation restates the gate's comparison in a second place — often in a
second language, across an HTTP boundary. **That is two pieces of code deciding one rule**, and the
two sections above name how it fails: they share inputs and coincide until the day they do not.

🔴 **AND THE RESTATEMENT WAS ALREADY WRONG BEFORE ANYTHING DRIFTED, WHICH IS THE PART TO CARRY.** The
ratio gate admits a create when `created / closed < allow_below`. The natural headroom algebra is
`(created + N) / closed < allow_below` — *after N more creates, is the ratio still under?* **It yields
one less than the gate admits**, because the gate judges each create against the counts **BEFORE** it
lands: the router reads the counts, asks the advisory, and only then writes the row.

| created 10, closed 13, allow_below 1.00 | judged at | |
|---|---|---|
| create #1 | 10/13 = 0.77 | ADMITTED |
| create #2 | 11/13 = 0.85 | ADMITTED |
| create #3 | 12/13 = 0.92 | **ADMITTED** — the ratio is now exactly 1.00 |
| create #4 | 13/13 = 1.00 | REFUSED |

⚠️ **AND WRITING THE ALGEBRA AS A LOOP DOES NOT ESCAPE IT — THIS WAS MEASURED, AFTER BEING GUESSED
WRONG.** The spec asked for an explicit loop: *"probe created+1, created+2, … stop at the LAST
increment that still PASSES."* A manager reasoned that a loop probing the real gate cannot have the
algebra's boundary problem. **It has exactly the same one**, because it probes the STATE AFTER k
creates rather than the create itself. Measured against the gate: `10/13 → 2 vs 3` · `9/10 → 0 vs 1`
· `0/10 → 9 vs 10` · idle `0/0 → 0 vs 1`. **They agree only where the answer is zero both ways.**
⇒ *Iterating is not the same as asking. A loop over your own restatement is still your restatement.*

⇒ **THE FIX IS TO HOLD NO COMPARISON OF YOUR OWN.** The shipped function contains no ratio
arithmetic and no threshold: it calls the gate advisory and counts. Raising `created` raises the
ratio, so the answer is monotone and a search over it is **exact rather than a sample**. Agreement
stops being something an editor maintains in two places and becomes a property of there being one
decider.

⚠️ **AND THE PROJECTION MUST BORROW THE CALLER'S INPUTS, NOT RE-READ THEM.** The threshold is a live
operator dial; two reads a second apart can differ, and then the number and the gate describe
different worlds while both are "correct". The handler reads counts and threshold ONCE and passes
them down. A test booby-traps every settings getter — with a second test proving the trap fires,
because a monkeypatch that silently fails to bind makes a purity test pass for the wrong reason.

🔴 **THE COST OF THIS IS NOT THE NUMBER — IT IS THAT A PROJECTION CAN DELETE A RATIFIED STATE.** The
display had three states, one of them ratified by keypress: `FULL` for *at capacity, still legal*.
**Built to the gate, `FULL` is unreachable**: headroom is 0 exactly when the gate already refuses,
which is a different state, so if the gate admits at all then at least one more gets in. Nobody
decided to remove it and nobody would have noticed — it simply has no inputs any more. ⇒ **When a
projection replaces a sketch, enumerate the sketch's states and check each one is still REACHABLE.**
A state that quietly loses its last input is not a simplification; it is a ratified decision
disappearing without a ruling.

⚠️ **BOUND IT — A PROJECTION DESCRIBES THE PATH IT WATCHES AND NOTHING ELSE.** This number is about
ORDINARY creates: the gate exempts P0 and the harness mirror lane unconditionally, so it does not
describe those. And it describes the gate's VERDICT, not today's blocking — while enforcement is off
the router logs the refusal and lets the write through, so 0 means *"the gate would refuse"*, never
*"your create will fail"*. **A displayed number that quietly widens its own scope is this section's
defect arriving in the caption instead of the arithmetic.**

🔴 **AND THE SECOND INSTRUMENT EARNED ITS KEEP TWICE, WHICH IS WHY IT IS NOT CEREMONY.** A
brute-force walk of the gate, one create at a time, ran beside the real implementation.
(1) It settled the loop-versus-gate question above. (2) It caught a live bug in the mirror direction:
a probe that stepped `+1` to 64 and then **doubled** jumped 65 → 130 and skipped the answer —
returning **130 where the truth was 91**. **Every hand-written case sat below the jump and passed
clean.** A second opinion would not have found that; a second INSTRUMENT did, and re-reading the code
would not have either.

⚠️ **HOW THE GUARD WAS PROVEN, because a test file is not a guard until something has watched it
fail.** Two mutation arms, detached worktree, green baseline first: making the projection a second
gate reddened **79 of 193** — including the grid-agreement test, and NOT the two positive controls,
which is what shows it discriminates rather than merely reddening. Making the BROWSER compute it
reddened **6 of 9**. ⚠️ Three survived, named rather than rounded away: one because the wrong
implementation **coincidentally agrees** at those counts, two because the clause is never reached.
**That coincidence is why the load-bearing test feeds counts under which every plausible local formula
gives a different answer** — a fixture where the right and wrong implementations agree measures
nothing.


---

## Unguarded is a third state — the demote guards and the two-blind-leg wiring check

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 UNGUARDED IS A THIRD STATE, AND A BINARY THAT EXCLUDES IT IS STILL WORTH ASKING

Measured 2026-08-31 (rows `f3230576`, `9dbffefb`). A manager asked whether a flag was **FIXED**
or only **DETECTED**. Both were false. The predicate had always been correct; what was missing
was a test that could have noticed if it weren't. **A field can be right and untestable-if-wrong
at the same time**, and neither word in the question fits that.

| state | the code | a test that could see it break |
|---|---|---|
| broken | wrong | — |
| **UNGUARDED** | **right** | **absent** |
| guarded | right | present |

⇒ **Say which one you are in, and prove it.** Here the proof was a byte-identical diff of the
serializer's return block across the two shas — the fix commit added declarations and tests and
changed no projection value. *"Detected"* would have asserted a live defect that never shipped.

🔴 **AND THE FORCED CHOICE WAS NOT THE ERROR — IT WAS THE INSTRUMENT.** Being made to pick
between two wrong words is what sent the answerer to the diff instead of to the nearer-sounding
one. **A binary that excludes the true answer earns its place when it is answered with a
MEASUREMENT, and manufactures a durable false claim when it is answered with a preference.**
Same question either way; the whole difference is what the answerer does next.

⇒ So neither party should soften the question. **Ask the sharp binary — and when neither box
fits, name the third state and show the evidence, never tick the closer box and move on.**

⚠️ **AND THE THIRD STATE HAS A SIGNATURE ON GUARDS, WHICH IS WHERE IT IS HARDEST TO SEE** (maria
🌸 and Mr. Radio 🦉, 2026-09-02, on a report of client-side guards). Asked *"are these three
blank-reason guards MISSING or merely UNWATCHED?"* — a false pair, and the answer was the third
state again. **A guard that is present, correct, and untestable-if-wrong reads as PRESENT to a
code reader and as ABSENT to a mutation run**, so the two instruments disagree and neither is
malfunctioning. That is § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE* arriving
on guards rather than on searches.

⇒ **Separate them mechanically, never by reading the guard**: delete it, and watch whether a
NAMED test that was PASSING at baseline goes red. Nothing reddens ⇒ present-and-unwatched, which
wants a test. Something reddens ⇒ it was watched all along. **A break list proves UNWATCHED; it
never proves ABSENT** — and the two want opposite fixes.

🔴 **AND HERE IS WHY THE THIRD STATE EXISTS AT ALL — THE MECHANISM, NOT THE SYMPTOM** (Rio ⚡,
2026-09-02, explaining his own blind guard): **a test whose assertion can be satisfied by more
than one path cannot tell you which path ran.** That is the whole of it, and everything above is
a consequence.

**His worked case.** Demote had two guards, and its test asserted *"the server was not called"*
with **both fields left blank**. Either guard alone satisfies that. So deleting one changed
**nothing observable** — the assertion was true before, true after, and true for a reason the
test never named. The guard was present and correct; the assertion simply could not see which of
two sufficient causes produced it.

⇒ **Ask of every assertion: how many different states make this true?** More than one, and the
test measures their DISJUNCTION, never the member you meant. **Name the path in the assertion** —
assert the field the guard populates, the branch it takes, the specific refusal it raises — not
the shared downstream effect that several paths share.

🔴 **AND THE CONSTRUCTIVE HALF, WHICH THIS FILE HAD NOT WRITTEN DOWN** (maria 🌸, 2026-09-02):
**the fix for a multi-cause observable is not a better assertion — it is a SECOND MEASUREMENT that
kills one branch.** Measured the same evening: *"zero `wont_fix` events store-wide"* could not
discriminate between a click swallowed by a lookup collision and a pane with no listener. Adding
one independent reading — that `parked → wont_fix` is a legal edge the validator **accepts**, so
the server would have taken the write — killed the server branch and converted an ambiguous
observable into a located one: **the click never became a request.**

⇒ **So when you find an assertion with several sufficient causes, do not go looking for sharper
words. Go and eliminate a cause.** The rule above tells you the reading is worthless; this tells
you what to do next.

⚠️ **This is the same defect as § *A COMPARISON WHOSE TWO SIDES COME FROM ONE SOURCE*, one level
in.** There, two sides move together so the comparison cannot fail. Here, two causes converge so
the assertion cannot discriminate. **Both are an `assert` that is true by construction rather
than by behaviour**, and neither shows up in a coverage number or an assertion audit.

🔴 **AND A SECOND RECEIPT, IN PRODUCTION CODE, WHERE ONE TEST CARRIED *TWO* SUFFICIENT CAUSES —
SO FIXING THE ONE YOU SPOT LEAVES IT BLIND** (Rachel 🕊️, 2026-09-02). The approval gate's wiring
check, `test_the_gate_is_wired_into_the_transition_door_at_all`, has been reporting on a gate it
never touches. **Measured**: delete the gate's call site — `routers/tasks.py:1014-1020`, the
`refusal_for_admission` call and its 403, inside `transition_task` — and the whole unit tier comes
back with a **byte-identical failing set**, 18 failed / 21,819 passed both arms, sha
`83839149a659` → `cf07112aac90`, anchor 1x, restore verified.

**Its two legs go blind for DIFFERENT reasons, and that is the part this section did not yet say:**

| the leg | why it cannot see a wiring revert |
|---|---|
| `tasks_router.approval is approval` | the module is **also** used at `tasks.py:775` for `default_mint_status` — so the import survives a full revert. Two sufficient causes, one assertion |
| a **PATCH** task route is mounted | the transition door is **POST** `/tasks/{task_id}/transition`. The PATCH routes it finds are the edit door and the flow-ratio door — **it is checking a different door** |

⇒ **A reader who notices either one and fixes it still has a blind test**, because the other leg
keeps the whole test green on its own. The first leg is this section's multi-cause defect; the
second is § *YOUR MATCH KEY IS SHORTER THAN THE ROUTER'S KEY* — **two different failures wearing
one green check**, and neither is visible from re-reading the assertions.

⇒ **So count the SUFFICIENT CAUSES PER LEG, not per test.** A test with two legs can have two
independent reasons to be unfalsifiable, and a single fix reads like a repair while changing
nothing about what the test can observe.

**Closed the way this section prescribes — a second measurement, at the layer the incident enters
at**: five tests driving the real handler over HTTP (`test_the_transition_door_calls_the_approval_gate.py`,
landed `8b79dc55`). Proven, two arms off ONE mutated sha: the old suite **SURVIVED** across 21,837
tests; the new guard **KILLED** it by two named tests **while its other three stayed green** — so
it discriminates rather than merely reddening.


---

## A coverage list goes stale from a merge — the retracted assignment and the scoped frame

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A COVERAGE LIST GOES STALE FROM A **MERGE**, NOT FROM A COMMIT

**Measured 2026-08-29** (row `9595aaef`). A manager spent an evening assigning coverage work off a zero-coverage census, then retracted an assignment when the worker showed the file already at 100% with 61 tests by his own commit hours earlier. **The retraction was the error.** Checked by merge-base: that commit — and three others like it — are **not ancestors of HEAD**. They live on the workers' own branches. At HEAD no test imports that module at all, so the file is still at 0% on the branch.

**Nobody was wrong. They measured different trees.**

| question | answer |
|---|---|
| "Is my work done?" | ask the **worktree** — the tests exist and pass there |
| "Is the branch covered?" | ask **HEAD** — and it is not, until the merge lands |

⇒ **Work in an unmerged worktree moves nobody's coverage but its author's.** A seat that re-measures "in my own tree" will contradict a HEAD-derived list every single time, and both parties will have correct numbers for different propositions. That is what every tree-versus-tree argument on this epic has actually been.

**Two obligations follow:**
1. **State the sha with the list.** A coverage list without the sha it was taken at is not a measurement, it is a rumour with a timestamp. Say `at ef6e2bdc`, not "as of tonight".

   ⚠️ **AND IT IS NOT ONLY COVERAGE LISTS — IT COVERS EVERY LINE-NUMBER CITATION YOU SEND A PEER.** Measured 2026-08-30: two seats quoted different `CLAUDE.md` line numbers for the same two sections and spent a round trip finding out why — one was reading numbers from his own branch, uncommitted, where the section had already moved. **A bare `file.py:482` is a pointer into whichever tree the reader happens to be standing in**, and on this fleet that is never reliably yours: peers work in worktrees, branches sit unmerged for hours, and one section can carry three different line numbers before dinner. Write `file.py:482 @ 8bf71a64` — the sha costs eight characters and turns a pointer into a fact. **Better still, cite the section heading or the symbol name: a heading survives an edit above it and a line number does not.**
2. **Report "done" and "landed" as separate columns.** A worker's file can be finished and still be at zero on the branch. Collapsing the two is what turns an honest commit into a phantom reassignment.

**And the durable fix is a command, not a list** — anyone can re-derive the current zero set at HEAD, and a list anyone can quote will outlive the tree it described:

```bash
# from your own worktree, checked out at the sha you mean to describe
COVERAGE_FILE=/tmp/cov-$USER-$$.data LUPIN_ROOT="$PWD" \
  .venv/bin/python -m pytest src/tests/unit/ -q --cov=src/scripts --cov-branch \
  --cov-report=term-missing --cov-fail-under=0
```

⚠️ **Run the WHOLE tier, not a scoped subset.** A subset manufactures false zeros for any file whose only coverage comes from a test you excluded — which is the exact defect a zero list exists to find.

⚠️ **AND NEVER SCOPE A RUN WHOSE OUTPUT YOU INTEND TO READ AS A LIST** — do not pass `--cov=<path>` when the config already defines `source`. Measured 2026-08-29: a census run carried `--cov=src/scripts` out of habit, which **silently overrode** the `source` list in `pyproject.toml` and produced a **61-file** frame instead of **73**. (⚠️ **"Seven" and "thirteen" both describe that list correctly and count different things** — Rachel 🕊️, 2026-08-30: **seven top-level roots**, of which `src/scripts` carries **six non-package subdirectories listed separately**, so the `source` array holds **thirteen entries**. Neither figure is stale; say which you mean. The durable check is neither number — `src/tests/unit/test_coverage_frame_completeness.py` asserts `unreachable_subdirs( … ) == []`, derived from the tree, so it stays true however the list grows.) The twelve subdirectory files were not reported as `0%` — they were **never instrumented at all**, and the report says nothing about a file it never traced. Re-reporting the same `.coverage` data through `--rcfile` cannot recover them either; the data simply is not there.

⇒ **A scoped override does not narrow the REPORT, it narrows what was ever MEASURED — and the difference is invisible in the output.** Both produce a clean table with a plausible total.

⚠️ **NARROWED 2026-08-30, measured by Maya — the ban is on the LIST, not on scoping.** Per-file counts are **scope-invariant**: the same file reads the same statement/branch numbers under two different `--cov` scopes (measured at 163/0 and 44/0 in both frames). So a scoped run is **safe** for *"what is this one file's coverage"* and unsafe **only** for *"which files are at zero"* — because a file's **absence from a scoped report means never-measured, not zero**. Drop the flag when you are producing a list and let the config's `source` govern; if you must scope, say in the same breath which files fell outside the frame, because "not listed" and "at zero" are different facts and only one of them is safe to act on.
