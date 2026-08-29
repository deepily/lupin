# R1 rebase pass — the plan at `16c6dc2b`

**Reviewer 1 (Tiberius 👑), 2026-08-21.** Read-only. Whole 284-line fold read before anything below.
**Doc**: `src/rnd/v0.2.0/2026.08.20-brain-integration-cascade-review-plan.md`, now 1,173 lines.

---

## 1. Are my findings correctly represented in the fold?

**Verdict: 5 of 14 are recorded. ZERO are fixed in place. Every defective line I reported survives
verbatim.**

The fold is `+284 / −7`, and all seven deletions are in the STATE AT STOP question table. The Files
table, the Sequence, the Verification section and the observability tally were **not touched**.

| finding | recorded in the fold? | defect fixed in the section that carries it? | still reads |
|---|---|---|---|
| 1 — reuse list names `resolve_voice()` that 2b deletes | ❌ no | ❌ | L449 |
| 2 — observability tally | ✅ Orphans section | ❌ | L551 "Three observable commits out of ten" |
| 3 — step 5 is a ~330-line reindent of the live path | ❌ no | ❌ | step 5 |
| 4 — `snapshotable=False` orphan + empty step 8 | ✅ Orphans section | ❌ still unsequenced | — |
| 5 — nullable `routing_command` feeds replay reporting | ❌ no | ❌ | `flow.py:100-101` |
| 6 — Files table "in scope, not conditional" vs open Q4 | ❌ no | ❌ **and Q4 is still open** | L446 |
| 7 — "stay green **unchanged**" is unsatisfiable | ❌ no | ❌ | L566 |
| 8 — Verification names no through-path test; no bridge guard | ❌ no | ❌ | L570 |
| 9 — 2b changes `resolve()`'s signature; `flow.py` call sites unlisted | ❌ no | ❌ | — |
| 10 — `fifo_queue.py` absent from Files table; its smoke block breaks | ❌ no | ❌ | — |
| **11 — Files table inverts Rick's `parked` ruling** | ❌ no | ❌ | **L444 "rename the needs-input `parked`"** |
| 12 — Files table misses five files | ❌ no | ❌ | L444-446 |
| 13 — `user_id` fail-loud orphan | ✅ Orphans section | ❌ still unsequenced | — |
| 14 — replay branch drops `primary_error` | ✅ own section, fold instruction written | ❌ | `flow.py:102` |
| index: 27-vs-28 drift | ✅ resolved cleanly | ✅ | — |
| index: step 0 orphan | ✅ Orphans section | ❌ still not in the Sequence | — |

**🔴 The one that matters most is finding 11.** Mr Radio reported it made Rick's escalation, and
line 444 still instructs the implementer to rename the needs-input `parked` — the exact state Rick
ruled keeps its name, and the value documented on the live endpoint at `v2_ask.py:57`. **An
escalated finding that never reached the line it was about is not folded.**

**The pattern is the one this review keeps finding.** The document grew by 284 lines of correct new
prose while the summary structures that instruct the implementer kept their defects. It now contains
both the correction and the error — the Orphans section says *"re-derive the tally"* while line 551
still states the wrong tally forty lines away.

---

## 2. The observability tally, re-derived from the sequence as written

Sequence as written: **13 steps** (1, 2, 2b, 3, 4, 5, 6-pre, 6a, 6b, 6c, 7a, 7b, 8) **plus step 0's
four commits = 17 commits.**

| step | observable? | why |
|---|---|---|
| 1 rename | no | internal enum value (as *ruled*; the Files table's version would break `/api/v2/ask` — finding 11) |
| 2 `QueueExecutor` | no | nothing wired |
| **2b one resolver** | **YES — `/api/v2/ask`** | `flow.py:111` calls `resolve()`; folding the fork changes which agent class answers todo/calendar |
| 3 accept `waiting` | no | nothing returns `waiting` until 6c |
| 4 agent parity | **data-visible** | changes `question_gist`, `push_counter`, debug flags for every flow-built agent ⇒ every query-log row changes. A third category the tally does not have |
| 5 delete two-turn confirmation | **no** | 🔴 the tally calls this "observable most of all"; **the plan itself proves the branch never fires** — zero production callers of `push_blocking_object`. The prompt Rick hears is at `:636`, which **7b** removes |
| **6-pre reorder** | **YES — `/api/v2/ask`** | the plan says so in as many words |
| **6a gist tier** | **YES — `/api/v2/ask`** | filed invisible as "not yet reachable from voice"; it changes what the live endpoint replays |
| **6b near-match ask** | **YES — `/api/v2/ask`** | introduces a user-facing prompt on the live endpoint |
| **6c the switch** | **YES — voice** | |
| 7a `:953` | no | dead method |
| **7b `:313` + search-and-ask** | **YES — voice** | removes the confirmation prompt Rick hears |
| 8 write-back | no | the step has no content |
| step 0 (×4) | no | unreachable in production; it does redden tests |

### ⇒ SIX observable, of 13 steps / 17 commits. Not three of ten.

**🔴 And the error is a category error, not arithmetic — which is why re-counting will not fix it.**
The tally equates *user-visible* with *voice-visible*. Three of the six (2b, 6a, 6b) were filed as
invisible using the phrase **"not yet reachable from voice"**, while `/api/v2/ask` is live, mounted
(`main.py:1335`) and documented. The plan's own 6-pre section already knows this — *"observable there
the moment it lands — it is not a free refactor"*. **The document contradicts itself rather than
miscounting.** A re-derivation that keeps the same definition lands on three again. The definition
has to be fixed first: *observable = visible on any live surface*, and the plan has two.

---

## 3. Sequence coherence on the NEW material

### 3a. Two new findings the rulings create

**🔴 FINDING 15 — the read guard fails OPEN on rows the user marked WRONG.**
`answer_is_correct` is **`Mapped[Optional[str]]` on a `Text` column** (`vector_store_models.py:299`),
and `cache.py:272` writes it as `json.dumps( … )`. So the stored values are the **strings**
`"true"` / `"false"` / `"null"` — while the v1 path assigns a Python bool at
`running_fifo_queue.py:1787`. A guard written as a truthiness check admits every row the user
explicitly answered **no** to, because `bool( "false" )` is `True`; a guard written as equality
against one literal misses the other writer's representation. **This is the identical defect class as
my finding 5** — a guard leaning on a loosely-typed nullable column — and the plan condemned that one
in writing. The three-state fail-closed design is right; the column it reads is not typed to support
it.

**🔴 FINDING 16 — the read guard and the cache's reason to exist are in tension, unmeasured.**
A row becomes servable only if the user answers a prompt that fires **after** completion on a daemon
thread, 60s timeout (`_fire_correctness_check_async`, `:1751`), leaving `None` on timeout. So the
cache hit rate becomes a function of **how often a human answers a prompt**, and nobody has measured
that rate. Two consequences the plan should state before this is built:
- **Every non-interactive caller can never build a servable cache.** The paired eval runs
  `interactive: false` and answers nothing ⇒ the v2 arm returns to **0% cache hit**, which is exactly
  the condition that was just fixed and that made this run the first to measure v2 with replay live.
  The instrument that decides go/no-go would be measuring v2 without its cache again.
- **6a and 6b lose most of their value** — a gist tier and a near-match ask over a table that only
  holds human-confirmed rows.

### 3b. Steps the rulings imply that do not exist, and the order they force

Ordering constraints only — the sequence is María's to write.

**Gates (artifacts, not commits) — these come before anything in the 6-series:**
- **The entry-coverage audit**, both directions: what `push_job` does that the flow will not
  (mode, agentic contracts, control commands, the CRUD fork, receptionist/none, unknown), **and**
  what enters the queue without touching `push_job` (doors 6 and 7 use raw `push`). The doc requires
  the first and names the second; neither is written.
- **Rick's disposition ruling on the seven doors.** It gates guard *placement*: a read guard "at the
  head end" inside `push_job` does not cover doors 6 and 7. Placing it in the cache instead covers
  every door that goes through `AskFlow` — which is a different answer, and it is a design fork.

**Then, in this order, because each is a precondition of the next:**
1. **Step 0's four commits** — into the Sequence at the front, where the document already argues they belong.
2. **`user_id` fail-loud** (63 of 64 rows ownerless) — **before the dump**, or the fresh cache refills ownerless. The fold states this and sequences it nowhere.
3. **Write guard** (the router must have chosen the agent, plus v2's missing CRUD exclusion) and **read guard** — **both before the dump**, for the reason the fold gives: *"a fresh cache re-poisons itself without them."*
4. **Write-back quality**: the two causes behind finding 14 — codeless snapshots beyond `CalculatorAgent`, and the long-form/short-form command-string mismatch — are write-side defects the dump does not fix.
5. **The dump.** Last of this group, and only once 2, 3 and 4 have landed.
6. **`snapshotable=False` travels with the fork** — belongs with 2b, still unsequenced.
7. **`primary_error` + the spoken failure on the replay branch** — **before 6c**, not after. After 6c every spoken question rides that branch, and shipping a path that failed 42 of 100 with no recorded cause is the opposite of the fail-loud ruling.
8. **The mode-resolution step**: `push_job` resolves mode and hands `AskFlow.run()` an already-resolved command. ⚠️ This **collides with 6-pre**: route-first assumes the flow always routes, and a pre-resolved command is an exception to it. Same lines, two steps — they must be adjacent, and 6-pre's premise needs restating.
9. **The agentic-preservation step** (`JOB_ARG_CONTRACTS` early return) — before or with 6c.

**And one consequence of the scope expansion nobody has stated: 6c is no longer "the switch."**
It is one of up to six. Doors 1, 2, 5, 6 and 7 each become their own hand-over, and the plan's
"lands alone, on a quiet box, first thing to revert" discipline was written for a single switch.
Either that discipline now applies six times, or the plan says which doors move together and why.

---

## What I did not do

No code changed, no server touched, no store write, no measurement run. The `answer_is_correct`
representation is read from the model and the two writers at HEAD; I did **not** query the database
to see which representations are actually present — that is a SELECT somebody should run before the
read guard is designed.
