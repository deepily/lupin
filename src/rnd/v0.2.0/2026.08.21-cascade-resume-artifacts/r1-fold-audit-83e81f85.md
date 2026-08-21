# R1 fold audit — `83e81f85`

**Tiberius 👑, 2026-08-21.** Read-only. Second fold audit; same method as `16c6dc2b`.
Fold: `16c6dc2b..83e81f85`, two commits (`7cedd853`, `83e81f85`), **+110 / −19**, doc now 1,264 lines.

---

## Headline: 0 of 13 carrying-line findings fixed. Second consecutive fold.

**Where the 19 deletions landed**: all of them in the author's own new material — the 7-door table
(15 lines), the sibling-class refutation paragraph (4), and the open-question-5 row. **Not one
deletion touched a line I reported.**

| finding | carrying line at `83e81f85` | fixed? |
|---|---|---|
| 11 — Files table inverts Rick's `parked` ruling | **L535** — still *"rename the needs-input `parked`"* | ❌ |
| 12 — stale Files-table row | **L536** — still *"whichever cache stage Rick's ruling removes"* | ❌ |
| 6 — scope asserted and disclaimed | **L537** — still *"in scope, not conditional"*, Q4 still open | ❌ |
| 1 — reuse list names a deleted function | **L540** — still `registry.resolve_voice()` | ❌ |
| 2 — observability tally | **L642** — still *"Three observable commits out of ten"* | ❌ |
| 7 — "stay green **unchanged**" unsatisfiable | **L657** | ❌ |
| 8 — no through-path test, no bridge guard | **L661** — still *"unit + cosa"* | ❌ |
| 3 · 5 · 9 · 10 · 13 | unchanged | ❌ |
| **14 — replay branch drops `primary_error`** | recorded at **L270-271**; the *"What lands"* section at **L900** still reads only *"Wrap the routing call"* | ❌ |
| **15 — guard on a loosely-typed column** | — | ✅ **folded correctly** |

**Finding 15 is the one success, and it is worth naming as the template**: it had no carrying line —
it was a caution about a guard not yet written — and the fold writes the guard *with the caution as a
named constraint* (`snapshot.answer_is_correct is True`, hydrated object never raw column, typing
optional hardening, fails safe toward over-refusal). **That is what folding a finding looks like.**

**Finding 14 is the counter-example, and it has now happened twice in a row**: the correct instruction
is written at L270 and the section it corrects, forty lines further on at L900, still carries the old
narrower text. The Sequence section is byte-identical to two folds ago.

**The author's own corrections DO land in place** — the 7→18 door count, the refutation-of-a-refutation,
the Q5 status. Reviewer findings are appended as prose; author findings are edited into the text.
**That asymmetry is the fold-discipline defect, stated precisely.**

---

## The new material is good, and one of its conclusions is wrong

### 🔴 FINDING 17 — door-counting is the wrong frame for a read guard. 18 doors, ONE lookup.

The fold closes with: *"a read guard at the head of `push_job` misses doors 6, 7 and 9–18, plus
internal callers i2–i7 — twelve endpoints and six callers, not two."* The count is right and the
inference does not follow: **a read guard only matters where something reads the cache**, and almost
none of those doors do.

**Every production cache-read site, measured** (`get_snapshots_by_question`, excluding tests and the
manager internals):

| # | site | reachable from | status |
|---|---|---|---|
| 1 | `todo_fifo_queue.py:556` | `push_job` — v1 stage 1 | **step 7b deletes it** |
| 2 | `running_fifo_queue.py:302` | `_process_job`, **`AgentBase` non-CRUD only** | **step 7b deletes it** |
| 3 | `running_fifo_queue.py:946` | `_process_fast_lane` | **dead — no production callers** |
| 4 | `v2/cache.py` → `TwoTierQuestionSearch` | `AskFlow` | **the survivor** |
| — | `admin.py:810` | admin search endpoint | reporting, not a replay path |

**Doors 9–18 cannot reach any of them.** `_process_job` dispatches `AgenticJobBase` at
`running_fifo_queue.py:281` straight into `_submit_agentic_job` and returns; the cache block at
`:290-325` sits inside the `elif isinstance( running_job, AgentBase )` branch. Every `/submit`
endpoint raw-pushes an already-built agentic job, so **it never performs a lookup at all** — there is
nothing there for an unconfirmed row to be served into. Doors 6 and 7 raw-push already-built jobs the
same way.

⇒ **The guard has exactly one home after this plan's own steps land: the brain's lookup.** Stating it
as *"twelve endpoints and six callers"* sends the implementer to install a guard on eighteen doors
when the exposure lives at one call site. **The door inventory is the right answer to Rick's
one-front-door question and the wrong instrument for guard placement — two different questions that
the fold currently answers with one table.**

### 🔴 FINDING 18 — door 8 is now *determined broken* and still has no owner

The fold upgrades `speech.py:338` from *"undetermined — own row"* to determined: `push_job` takes four
required parameters, the call passes one, so `POST /api/upload-and-transcribe-mp3` **raises
`TypeError` every time `munger.is_agent()` is true**. It is a live HTTP handler. The document now
states a production defect as fact and assigns it no row, no step and no owner — the same orphan
shape as the `user_id` fail-loud and the `snapshotable` fix.

---

## What is genuinely improved in this fold

- **The 7→18 correction, with its own method note** (*"I grepped three router files I already had
  open and presented the result as an inventory"*). Chloé measured repo-wide; the disposition column
  is deliberately left for Rick.
- **The refutation-of-a-refutation is right and matters**: `TodoListAgent`/`CalendaringAgent` are
  **siblings** of `CrudForDataFramesAgent`, not subclasses, so they sail through the `isinstance`
  check at `running_fifo_queue.py:1563`. v1 is protected by **routing**, not by the class test — a
  weaker guarantee, correctly downgraded.
- **The third arrival kind is flagged, not decided**: a new job that names its command and carries
  args is neither a question nor a resume. Correctly sent back to Rick because his two-way ruling was
  given against the 7-row table.
- **Read-A guard section** — finding 15 folded as described above.

---

## Method note

Deletion-location first (one command), then the carrying lines, then the new material. The deletion
map answers the audit's main question before any prose is read: a fold whose deletions all sit inside
its own new sections has not corrected anything an implementer reads.
