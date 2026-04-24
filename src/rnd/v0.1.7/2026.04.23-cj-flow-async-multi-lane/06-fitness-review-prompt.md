# Fitness-to-Implement Review Prompt (second-pass gate before Phase 1 implementation)

**When to use**: AFTER `05-adversarial-review-prompt.md` has been run and its findings resolved. This is the SECOND of two review passes.

**Goal**: Enforce design quality. Hunt places where the design isn't yet detailed enough for a competent-but-unfamiliar engineer to implement without asking clarifying questions. Fill in the design gaps before any code is written.

**Expected outputs**:
- A findings table (File / Line or section / Deficiency type / What's missing / Proposed fix)
- Explicit answers to the 5 enumerated TBD questions in the design docs
- Raw output from the two greps
- A "Design concerns" section for anything that would warrant challenging a Q1–Q7 decision (surface, don't silently override)

**What to do with the findings**: Review them with the user. Apply agreed design clarifications. Only then begin Phase 1 implementation.

---

## The prompt (copy the code block verbatim)

Paste this AFTER the adversarial-review pass has been resolved, as your next message. You do not need to re-read the docs — use the context from the previous pass.

```
Now do a FITNESS-TO-IMPLEMENT REVIEW of the same 9 docs you read in the
previous pass. Goal: find places where the design is not yet detailed
enough that a competent but unfamiliar engineer could implement it
without asking clarifying questions.

For each finding, output one row:

| File | Line or section | Deficiency type | What's missing / ambiguous | Proposed fix |

Deficiency types to look for:

- AMBIGUITY — a step that requires a judgment call the design doesn't
  specify (e.g., "handle errors" without saying how)
- COMPLETENESS — a sub-step mentioned in passing but not enumerated
  (e.g., "also update tests" without listing which)
- TESTABILITY — a step where you can't tell how success would be verified
- ORDERING — a step implicitly dependent on something earlier that
  the docs don't state
- REUSE — a place where existing code / utilities should be referenced
  but aren't. Actively grep src/cosa/ for existing patterns (notification
  helpers, queue primitives, auth utilities, rate-limit code, websocket
  emitters) before flagging something as "new". If you find existing code
  that the design should reuse, name the file and function.
- DECISION TRACEABILITY — a design choice that doesn't trace back to a
  Q1–Q7 decision (in 01-design-review.md §3) or to an anchor statement
- SCOPE — something declared in-scope but not designed, or designed but
  unclear whether it belongs to this phase vs a later phase
- RISK SURFACE — behavior the design is silent on that will matter at
  implementation time (error paths, edge cases, concurrency races beyond
  the ones already addressed)
- EXTERNAL DEPENDENCIES — a step that depends on an external
  system / API / file whose contract the design doesn't specify

Also explicitly propose an answer for each of these TBDs currently
flagged in the design docs (do not leave them open):

1. ApiResourceManager exact file location (`src/cosa/utils/` vs
   `src/cosa/rest/` vs new location) — which and why?
2. ApiResourceManager.acquire() sync vs async signature — which, and
   how do sync callers (if any remain in Phase 1) use it?
3. Ghost-job watchdog placement — new `_ghost_job_sweeper_thread` in
   RunningFifoQueue vs tick inside an existing watchdog. Which, and why?
4. `/api/queue/pool-status` endpoint home — which existing router file,
   or a new router?
5. `_transition_to_done` / `_transition_to_dead` extraction — what's
   the exact current code being extracted? (Point at file + line range
   in src/cosa/rest/running_fifo_queue.py so the impl is grounded.)

Run these greps and include them in your report:

    grep -rn "TBD\|confirm during impl\|decide at impl time\|tbd" \
        src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/
    grep -rn "Open sub-question" \
        src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/

DO NOT fix anything yet. Deliver:
(a) the findings table
(b) explicit answers to the five TBD questions above
(c) a "Design concerns" section for anything that would warrant
    challenging a Q1–Q7 decision (surface, don't silently override)

I'll review and decide which findings to resolve before Phase 1
implementation begins.
```

---

## After pass 2 completes

- Review findings with the user
- Apply agreed design clarifications (fill TBDs, resolve ambiguities, document reuse targets)
- Any Q1–Q7 challenges surfaced need explicit user sign-off to accept or reject
- THEN Phase 1 implementation begins, reading `02-phase-1-rlock-config-and-resource-manager.md` + `90-phase-1-execution-log.md` as the implementation contract

Only when both passes are resolved AND the user has greenlit Phase 1 does any code get touched.
