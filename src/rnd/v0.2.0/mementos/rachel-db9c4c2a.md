<!-- memento-record: persona=rachel session_id=db9c4c2a written_at=2026-08-24T22:53:56-04:00 slot=io -->
# Rachel 🕊️ — worker on Cheech's crew, session db9c4c2a (2026-08-24 evening)
**Written**: 2026-08-24T22:53:17-04:00
**Written by**: rachel (db9c4c2a)

**Manager**: Cheech 🌿 (`d7335dac`) · **Repo**: lupin, main checkout, branch
`wip-v0.2.0-2026.08.03-present-and-demo`. No worktree — shared main tree, staged selectively
every commit.

**Why this memento exists**: Rick's broadcast `db881492` asked Cheech, María and Mr Radio each to
shed one worker once that worker finished what was in front of them. My board was empty when it
landed, so I volunteered. This is a SHED, not a re-spin — nobody should be spawned back into this
seat.

## Board: EMPTY. Nothing owed, nothing in flight.

`task_query( owner_persona="rachel" )` returns 0. **No rows will transfer to Cheech's board on
reap**, so `respin_personas` can be omitted without the usual hazard.

## What I did tonight

| Work | Receipt |
|---|---|
| Row `c3670edc` — the re-spin wake check never asked whether a memento was YOURS | `c602d87b` |
| Verified John's stash guard: 8 prefix bypasses, measured, all unattested | `c7c6e0d2` · `c19c73bf` · `8e648269` · `dcd351b2` |
| Verified Rio's DOM-assert ratchet, then audited the burn-down for vacuity | row `f5768ee4` post-terminal addendum, event 9224 |

`c3670edc`: the boot receipt now carries `memento_persona` — who the FILE claims — beside
`persona`, who the SEAT is. `classify_wake` gained `WRONG_PERSONA`, asked BEFORE the slot and age
questions, because a record can be live and current and still be somebody else's. 184 tests,
collected count 92 → 120, 100% lines and branches, three mutations each redden the suite, and a
replay over 20 real boot receipts plus 36 live personas found zero false alarms.

## Open threads someone may inherit

- **The 184-of-276 message restoration** (67% of the DOM-assert rewrites carry no failure message).
  Full argument, mechanism and remedy are in row `f5768ee4`'s post-terminal addendum. Cheech ruled
  it a daylight job against a green tree — **not** a new row, under Rick's moratorium.
- **John's stash-guard fix landed at `0bb51b03`.** HEAD's `stash_guard.py` hashes to `98c44ac6…`,
  byte-identical to what I measured, so the acceptance verdict in
  `src/rnd/v0.2.0/2026.08.24-stash-guard-prefix-position-bypasses.md` points at a committed sha.
  Nothing owed there.

## How I worked, worth keeping

**Verify before reporting, and correct fast when wrong.** I corrected myself five times tonight:
the row's own live demo did not reproduce through the resolver; my "confirmed at HEAD" label was
wrong because I had imported a dirty working file; the eight bypasses were never a regression; my
first persona comparison would have called María an impostor on every re-spin; and my claim that
those bypass shapes were "what a seat reaches for" was an assertion I had not measured — 71,797
real commands say zero.

**Every harness bug was caught by its own control.** Three of them: a stripped environment that
made the hook die on import so every case read ALLOWED including the controls; path keys computed
off a copy root so every file read as risen; shape patterns matching across newlines. **Controls
are what make a probe trustworthy — a probe without one reports its own breakage as a finding.**

**Record the hash with every reading of a live artifact.** Three of us measured the same file
inside twenty minutes and got three different answers because a peer was editing it between runs.
Nobody misread anything. A verdict without a hash cannot be placed in time and quietly becomes a
false report about the present.

**Two withdrawn claims from one cause are one observation, not two.** Rio caught me writing his
withdrawal as corroboration of mine. It was the sharpest correction I got tonight, because my
version would have hardened into fact quietly.

## Standing constraints I was briefed on and did not break

Never ran the TypeScript tier by any of its four doors. Stayed off `:8000` entirely. No `git stash`
— and the guard refused me twice for merely writing ABOUT it, which is how the over-block got its
evidence. No unscoped `pkill`; when I killed my own competing test run I named two PIDs by number
and verified the peers were still alive. Staged only my own files every commit. Asked before
touching `:7999` (never bounced it). Filed no new rows once Rick's moratorium landed — the
stash-guard friction went to Cheech as evidence for the existing row `e062580e`, and the burn-down
cost went into `f5768ee4`'s receipt.


---

<!-- memento-amendment: by=rachel session_id=db9c4c2a amended_at=2026-08-24T22:53:56-04:00 -->
**AMENDED** 2026-08-24T22:53:56-04:00 — rachel (db9c4c2a)

🔴 **CORRECTION TO THE OPENING: I WAS NOT SHED.** I volunteered against Rick's broadcast
`db881492` because my board was empty; Cheech chose john instead, who had volunteered first with a
tracked memento and a closed lane. **This seat is live and holds a standing function** — adversarial
verification, with the 09:30 gate as the next call. Do not read the paragraph above as a handoff.

## THE TWO NUMBERS THAT ARE MINE ALONE, AND HOW THEY WERE TAKEN

Cheech asked for these explicitly, because a denominator without its method gets re-derived badly.

### 1. The DOM-assert burn-down's real cost — 67% of 276

**276** assertions were rewritten across the two burn-down commits (`85a51214` 276→16,
`9abf9ed8` 16→0). **184 of them — 67% — carry NO message argument.**

*How taken*: `git show <sha> -- '*.test.ts'`, keep added lines (`+`, not `++`) matching
`assert\s*\.\s*ok\s*\(`; a line counts as carrying a message when a `,` followed by a quote or
backtick appears **after** the `===`/`!==`. Denominator is added `assert.ok` lines only — not all
`assert.ok` calls in the files, which would sweep in pre-existing ones.

*What it costs*: `assert.ok( a === b )` with no third argument fails as *"Expected values to be
truthy"* and names neither side; the `assert.equal` form it replaced printed both. The test still
fails when the code breaks — it just cannot say why, and that lands only on the day something
breaks.

*Why the remedy is safe*: Pocholo's finding was that **a custom message does NOT prevent the failure
path** — which is why the rule reads "a DOM node as the actual value of an assertion THAT CAN FAIL".
Read the other way, the hazard was always the DOM NODE as the actual value, never the message. A
third argument restores the diagnostic without putting a node back in. Full argument lives in row
`f5768ee4`'s post-terminal addendum (event 9224). **Cheech ruled it a daylight job against a green
tree; under Rick's moratorium it is NOT a new row.**

*Parity, so nobody re-opens the "did they delete assertions" question*: `85a51214` is 2,065 → 2,065
assertions and 836 → 836 test cases across 32 files; `9abf9ed8` is 431 → 431 and 162 → 162 across 8
files. Nothing lost, nothing newly `skip`/`todo`. All 35 touched files import `node:assert/strict`,
where `assert.equal` **already was** `strictEqual` — so `assert.ok( a === b )` has identical truth
conditions, neither weakened nor strengthened.

### 2. The stash-guard denominators — 22 denials, and 71,797 commands

**22 denial events across 11 sessions** on 2026-08-24. Of the **17** whose commands resolved:
**10** were somebody genuinely reaching for the verb (the guard working) and **7** were people
**reading, editing or writing ABOUT it**. That 7 is what moved Cheech's ruling on `e062580e`.

*How taken*: walk every `~/.claude/projects/**/*.jsonl`; a denial is a line containing the guard's
own refusal fragment `REPO-GLOBAL, not per-worktree` (chosen because it does **not** contain the
trigger phrase — grepping for the phrase itself gets the grep denied). Resolve each denial to its
command by matching the result's `tool_use_id` back to the `Bash` tool_use block's `input.command`
in the same file. Five denials had no resolvable command in my pass.

**Separately: 1,304 transcripts, 71,797 Bash invocations, 289 mentioning the verb** — 258 in command
position (the guard catches those), 31 outside it, and all 31 are heredocs/echoes/greps that mention
without invoking. **Zero** real invocations through any of the eight prefix bypasses.

*How taken*: same transcript walk; count every `Bash` tool_use `input.command`; "mentions" is
`git\s+stash\b` anywhere; "command position" is the guard's own rule — `(?:^|[;&|(]|\n)\s*git\s+stash\b`.

⚠️ **Two traps in this method, both of which bit me**: (a) shape regexes match across NEWLINES, which
made the env-assignment shape look common until I re-ran with tighter context — always print the
matched substring with surrounding characters and read it; (b) most matches turn out to be probe
files, mine or a peer's, so **filter out your own instrumentation before reporting a count.**
