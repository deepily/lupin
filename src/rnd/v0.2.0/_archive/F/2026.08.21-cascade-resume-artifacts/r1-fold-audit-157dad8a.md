# R1 fold audit — `f1ccca51` + `157dad8a`

**Tiberius 👑, 2026-08-21.** Read-only.

## Fixed count: 4 of 4 folded. One new carrying-line defect.

| item | verdict |
|---|---|
| Step 5 placement | ⚠️ **ruled, not moved** — see below |
| Parity table | ✅ landed as written, all six rows, including the pin invalidated twice and the fixture-scaffolding note |
| Tally membership | ✅ step 5 dropped; list and number now both **six** |
| Finding 17 (door-count frame) | ✅ own section, self-corrected |
| Entry points (`f1ccca51`) | ✅ Q5 closed — two doors, `ask` and `submit`; three items correctly left owed |

---

## 🔴 NEW — step 5 is ruled to move and is still physically fifth

The ruling is recorded **inside step 5's own block**, which still sits between step 4 and step 6.
**An implementer reading the Sequence top to bottom builds it fifth.** A ruling that a step moves is
only folded when the step moves.

Two stale fragments left in that block, both below the ruling that resolved them:

1. **The either/or is still there** — *"Either the step says so plainly … or step 5 moves AFTER the
   switch. Choosing between those two is owed."* It was chosen. Say-it-plainly was declined.
2. **The step's opening justification is now false in its new position** — *"Nothing replaces it: the
   synchronous yes/no at `:636` already is the live confirmation."* After 7b, **`:636` does not
   exist**. That sentence was the reason the step had to move; it cannot also survive as the reason
   the step is safe. In the new position the thing carrying confirmation is **6b's near-match ask**.

⇒ Fix is mechanical: renumber it after 7b, delete the either/or, and restate the opening to name 6b
rather than `:636`.

---

## `f1ccca51` — read, no defect found

Two doors, `ask` and `submit`. `submit` covers both a new job naming its own command and a saved job
being continued. The two `push-agentic` behaviour deltas are turned into the definition of `submit`
rather than left as exceptions. `AskFlow.run()` → `ask()` is named as churn, with the correct note
that the one rename to refuse is keeping `run` for the decided path — an existing caller would keep
compiling and quietly do the opposite thing.

Three items correctly left owed: what a disabled door returns (Rick's), the six internal callers that
have no endpoint to disable, and reconciling the existing `/api/v2/resume`.
