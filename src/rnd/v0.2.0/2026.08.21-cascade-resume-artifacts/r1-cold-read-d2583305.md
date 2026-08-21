# R1 final cold read — `d2583305`

**Tiberius 👑, 2026-08-21.** Read-only. 1,691 lines, read front to back as a stranger would.

## Verdict: the DESIGN has converged. The DOCUMENT is not yet safe to hand an implementer.

Every ruling is now a real step, and the new steps 9–13 are the best-argued material in the plan —
9b names its own placement and its own surprise, 10 checked `/api/v2/resume` rather than assuming it,
11 refuses to guess at external callers, 12 refuses to assert startup ordering it has not read. **No
design defect found.** What follows is all text that rulings have overtaken.

---

## 🔴 1 — The front matter describes last night. It is the first thing anyone reads.

| line | says | actually |
|---|---|---|
| 3 | *"(6 commits held)"* | ~20 |
| 8 | **"🛑 STATE AT STOP … NOTHING IS BUILT"** | still true, but framed as a stop that has since resumed |
| 17 | *"Eleven commits on top of `9fa4283f`"* | ~20 |
| 28 | **"🔴 OPEN — must close before ANY code is written"** | **all five rows now read ✅ RULED.** The heading contradicts its own table |
| 40-46 | **"📏 MEASUREMENTS OWED — none of these may be guessed"** | three of four are **dissolved** — the dump killed the 27-row measurements, the eval is dead. And it still says *"the 27 rows"*, the exact phrasing that split two reviewers this morning |
| 63-77 | **"🔴 THREE RULINGS ARE ORPHANS … sequenced NOWHERE"** | **all three are now steps 0, 2c, 2d** |
| 58 | *"Steps CLEARED to build and are NOT being built"* | superseded |
| 84 | *"Resume tomorrow at: Rick rules on question 1 (mode)"* | ruled |

⇒ A reader who trusts the summary concludes the plan is blocked on five open questions and three
unsequenced orphans. **The summary is now the least accurate part of the document.**

## 🔴 2 — Verification was written for 13 steps. The sequence is 22.

**Nothing in Verification covers steps 9–13** — not the two guards, not `submit`, not the sixteen
410s, not the dump. Those are the observable, hard-to-reverse commits. Specifically missing:
- 9b's own test is stated *inside step 9b* (*"an unconfirmed row is never served, not even once"*) and
  never reaches the section that lists what must pass.
- 11's external-caller count is a **precondition**, not a test — and there is no verification that a
  410 stub returns what it promises.
- 13 has no post-dump check that the cache rebuilds through the guarded path.

Also still open there: **the through-path test is named as owed and never named**, and the **live
check** — *"speak a todo, a math and a weather request"* — assigns itself to nobody, which under this
project's own rule means it lands on Rick.

## 🔴 3 — The step-5 → 7c move left its references behind

- Step 7 lists **7a and 7b and no 7c**; 7c's definition sits ~60 lines earlier inside the slot that
  says *"nothing is built here."* Third fold running.
- The **parity table's disposition column still says "5"** in three rows. Step 5 no longer exists as a
  build step; those rows belong to **7c**.
- The paragraph above it still opens *"step 5 is why"* and *"Step 5 breaks two suites."*

---

## The re-derived tally the document declines to publish

The plan says, correctly, *"I am not publishing a new number — re-derive from the sequence as
written."* Doing that, as auditor:

**Sequence as written**: 0, 1, 2, 2b, 2c, 2d, 3, 4, [5 empty], 6-pre, 6a, 6b, 6c, 7a, 7b, 7c, 8,
9a, 9b, 10, 11, 12, 13 = **22 build steps, 25 commits** (step 0 carries four; slot 5 builds nothing).

**Observable on any live surface — TEN**: 2b · 6-pre · 6a · 6b (`/api/v2/ask`) · 6c · 7b (voice) ·
9b · 10 · 11 · 13.

**Not observable — twelve**: 0 · 1 · 2 · 3 · 4 · 7a · 7c · 8 · 9a · 12, plus 2c and 2d, which change
what is *written* rather than what is *said* — the same "data-visible, not user-visible" category the
tally has never had a name for. **Worth giving it one**, since three steps now sit in it.

⇒ **Ten of twenty-two.** Nearly half the sequence is observable now, against six of thirteen this
morning. **That is a different plan from the one the "lands alone, on a quiet box" discipline was
written for**, and the plan should say which of the ten can share a landing and which cannot.

## Step 8 is still empty

*"Write-back per Rick's ruling — nothing new built."* It was empty when I first flagged it, and 9a
now carries the guarded write. It should be deleted or absorbed, not left as a step number that
builds nothing — slot 5 already does that job once.

---

## What I would tell someone about to build from this

The design is settled and well-argued. **Read the Sequence and skip the front matter** — the steps are
current and the summary is not. Fix the three text items above and the document matches the design;
none of them requires another ruling.
