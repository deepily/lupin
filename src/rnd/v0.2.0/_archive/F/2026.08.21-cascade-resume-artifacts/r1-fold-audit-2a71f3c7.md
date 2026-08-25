# R1 final audit — `2a71f3c7`

**Tiberius 👑, 2026-08-21.** Read-only. Doc 1,516 lines.

## Fixed count: 2 of 3. **CONVERGED: NO.**

| item | verdict |
|---|---|
| Both stale fragments deleted | ✅ zero occurrences of the either/or |
| `:636` justification corrected | ✅ 7c now names **6b's near-match ask**, with the reasoning |
| Step 5 physically moved | ⚠️ **pointer only — see below** |
| Rick's last three rulings folded | ✅ 7a full deletion + seven tests · 410 naming `/api/v2/submit`, dead end-2026 · catch-up restore via `submit` |

---

## 🔴 Defect 1 — the pointer forwards, the destination isn't where the reader arrives

Slot 5 correctly reads *"MOVED — see step 7c below. Nothing is built here."* **But nothing moved
physically.** The `:541` block, the ruling, the reindent note and the **entire `### Step 7c`
definition** all still sit inside slot 5, between step 4 and step 6.

**Step 7's own block lists 7a and 7b, and no 7c.** A reader working step 7 finishes 7b and never
learns 7c exists — its definition is ~60 lines *earlier*, under the slot that says nothing is built
there.

⇒ Better than the last fold, which would have had it built fifth. Not converged: **7c needs an entry
under step 7, after 7b.**

---

## 🔴 Defect 2 — step 7a announces its own ruling and then re-opens it

At the top of 7a: *"✅ RULED 2026-08-21 — 7a IS NOW A FULL DELETION. Rick: the whole method goes, and
all seven tests."* Nine lines later, in the same step: *"⇒ **Open question for the next pass, not
decided here**: … Does the whole method go, and its seven tests with it? Wider than this plan scoped
— it wants a ruling, not my judgement."*

**The step both records the ruling and asks for it.** Delete the second.

---

## Convergence sweep — four more sections still call something open

| line | text | status |
|---|---|---|
| **1095** | *"What is owed, ahead of the cache guard"* → **"A ruling from Rick: does the flow learn about modes…"** | **STALE** — ruled 2026-08-21, mode stays, queue resolves first. Items 2 and 3 there are still live and should be kept as the test + the 6c precondition |
| **330** | `speech.py:338` *"Which one is undetermined — own row"* | **STALE** — contradicted twice in the same document, at 387 and 569, which say **determined broken** |
| **1208** | *"Rachel is checking whether any store beyond dev and test carries them. That answer is owed"* | **STALE** — dissolved by the dump ruling that closed Q3 |
| **409-413** | *"Flagged, not decided… goes back to Rick"* (third arrival kind) | **STALE** — Rick ruled it: `submit` generalises to *"the command is already decided."* Line 415 in the same section still repeats the door-count guard warning that finding 17 retired |

## Genuinely still open — two, both small and neither Rick's

1. **L909** — *"The section states the through-path rule and then names no through-path test. Naming
   one is owed."* Real, and it is the Verification section's last gap.
2. **L1508** — step 0 item 4, whether `SolutionSnapshotManager` and `FileBasedSolutionManager` are
   deleted outright, since the factory still advertises a `"file_based"` branch. Correctly marked
   Rick's.

---

## Verdict

**Not converged.** Two defects (7c unreachable from step 7; 7a re-opening its own ruling), four stale
open-calls that rulings have already closed, and two genuinely live items. None is a design problem —
every one is text that a ruling has overtaken. The pattern is the same one this audit has tracked all
day: **rulings get appended where they were decided, and the older sentence they replace is left
standing somewhere else.**
