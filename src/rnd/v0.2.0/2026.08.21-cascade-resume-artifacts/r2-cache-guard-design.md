# Open question 2 — a cache guard that survives the exact-hit rows

Reviewer 2 (Krishna), 2026-08-21. Design only. Nothing implemented, nothing committed.

## What the exposure actually is (measured, not reasoned)

`lupin_db_test`: 64 snapshots, 28 CRUD-backed (27 `TodoListAgent`, 1 `CalendaringAgent`).
Nine of those 28 are stored under a question that is a plain non-CRUD utterance — mode
routing put them there. Each has a `canonical_synonyms` verbatim AND normalized key.

Asking one of those questions again reaches `two_tier_question_search.pg_hierarchical_search`
**Level 1**, which short-circuits at **100.0** and never consults a threshold
(`two_tier_question_search.py:456-462`).

⇒ **The exposure sits ABOVE the threshold, not near it.** Any guard written as a
threshold rule — a floor, a tighter floor, a confirmation band — does not run on these
rows at all. That is the placement mistake the design has to avoid, and it is why the
reorder alone does not close it.

## The guard: command agreement, evaluated on the lookup RESULT

**Replay only when the matched snapshot's `routing_command` resolves to the same
`AgentSpec` as the command the CURRENT question just routed to.**

Placement, and this is the load-bearing part: the check runs on **whatever the lookup
returns, from whichever tier produced it**, before any replay decision — not inside the
similarity comparison. One site, and it covers Level 1, Level 2 and the vector tier alike.

```
command_now  = <the command route-first already resolved>   # always present
spec_now     = resolve( command_now )
spec_matched = resolve( snapshot.routing_command )           # may be None

replay iff spec_matched is not None and spec_matched is spec_now
```

## Why this shape

- **It fails CLOSED on the nullable column.** `routing_command` is
  `Mapped[Optional[str]]` (`src/cosa/rest/db/vector_store_models.py:279`), defaults to
  `""` (`solution_snapshot.py:177`) and is coerced `or ""` (`cache.py:252`). Here that
  is harmless: `resolve("")` returns `None`, `None` is not equal to any live spec, so
  an unprovenanced row is refused rather than allowed. The author's earlier guard asked
  "is the matched row CRUD?" and read the same nullable field — same column, opposite
  failure direction.
- **It never reads a column that can be absent on the deciding side.** The current
  command always exists, which is exactly Rick's argument for route-first.
- **It catches more than CRUD.** A math row matched by a weather question is refused for
  the same reason a todo row matched by a general question is. The defect class is
  "the cached answer was produced by a different agent than this question needs",
  and CRUD is only its most common instance.
- **It compares specs, not strings.** `solution_snapshot.py:897` still tests
  `routing_command == "agent router go to todo list"` while every writer stores
  `"agent router go to todo"` — a stale literal that has been silently false for a
  while. A guard built on string equality inherits that trap; a guard built on the
  single CRUD-aware resolver (step 2b) does not.

## The nine rows, checked against it

Current question routes to a non-CRUD command → `spec_now` is not the todo spec →
matched row says `agent router go to todo` → mismatch → refuse → run the agent.
All nine closed, by the tier they actually arrive on.

Legitimate repeats are unaffected: "what is 2+2" routes to calculator and matches a
calculator row → agree → replays. A genuine todo repeat never reaches the lookup at all,
because route-first's registry-derived CRUD skip fired first.

## What it costs, said plainly

Two registry lookups per cache hit, in-process, no model call.

The real cost is **false negatives**: if the router sends the same question to different
commands on different days, the second ask misses the cache instead of replaying. That
converts router flakiness into a slower answer rather than a wrong one, which is the
direction to fail in — but it is a cost, not a free win, and it should be **counted, not
assumed**. Emit a counter for "refused: command mismatch" so a cache that quietly stops
working announces itself. That is this plan's own recurring lesson applied to its own guard.

## Sequencing — the guard is decorative for one commit unless this is fixed

The plan lands 6c (wire `push_job` to `AskFlow`) and only then 7b (remove
`running_fifo_queue`'s cache stage), on the reasoning that overlapping caches is the safe
direction. It is the safe direction for latency. It is **not** safe for this exposure.

In that window: the brain's guard refuses the replay and hands the job to the queue as
`waiting`. `running_fifo_queue._process_job` then runs its **own** lookup at `:306`, whose
only CRUD test is on the CURRENT job's class at `:291` — nothing looks at the matched row —
and the `score >= 100.0` branch at `:311` replays the same todo row the guard just refused.

⇒ **The stage below defeats the guard above it.** The guard and the removal of
`running_fifo_queue`'s accept/exact-hit branches belong in the same commit, or 7b must
precede 6c for the cache path specifically.

## The guard is necessary and NOT sufficient — the pump is still open

The plan treats these rows as a bounded legacy population: *"written before
`running_fifo_queue:291` began excluding `CrudForDataFramesAgent`; the write side is
closed now, so no new ones are being made."* Measured, that is false.

| fact | evidence |
|---|---|
| the write-side exclusion landed | commit `53fef419`, **2026-06-19** |
| all 28 CRUD-backed rows were created | **2026-08-20, 21:44:45 – 22:13:58 EDT** |

Two months after, not before — and during the review evening itself.

The mechanism is a class-hierarchy gap. `running_fifo_queue.py:1563` tests
`isinstance( running_job, CrudForDataFramesAgent )`, but `TodoListAgent( AgentBase )`
(`todo_list_agent.py:8`) and `CrudForDataFramesAgent( AgentBase )`
(`crud_for_dataframes/agent.py:30`) are **siblings**. Anything that builds a
`TodoListAgent` snapshots normally and the exclusion never fires.

⇒ A read-time guard refuses these rows but does not bound them. Closing the write side
means the exclusion has to key on something the todo path actually satisfies — or the
todo path has to stop building `TodoListAgent`. That is a separate decision from the
guard, and it belongs with question 3.

## Implementation note, free of charge

`flow.py:99-101` already reads the matched snapshot's `routing_command` on the replay
path — it passes it to `_finish` as `command=`. So the guard's second input is already in
hand at the exact line where the decision is made. Worth noting the side effect that
exists today: a replay reports `command=<the snapshot's command>` even though the router
never ran, so a replay of one of the nine rows is traced as having routed to todo when it
routed nowhere.
