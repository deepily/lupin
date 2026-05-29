# [DONE, DO NOT REEXECUTE] Adversarial Review Prompt (first-pass gate before Phase 1 implementation)

**When to use**: After a fresh context clear, before any code is written. This is the FIRST of two review passes (the second is `06-fitness-review-prompt.md`). Paste the code block below as your opening message to Claude Code.

**Goal**: Enforce the "user is never a tester" mandate (`00-working-contract.md` + `CLAUDE.local.md`) by hunting every residual place in the design + execution-log docs where "done" could be claimed without the AI having actually executed verification.

**Expected outputs**:
- A findings table with File / Line / Problem / Proposed fix rows
- Raw output from the three greps
- (Optional) a "Design concerns" section if the adversarial read surfaces anything that would warrant challenging a Q1–Q7 decision rather than a wording/tagging fix

**What to do with the findings**: Review them with the user. Apply fixes. Only then proceed to pass 2 (fitness-to-implement).

---

## The prompt (copy the code block verbatim)

```
We are resuming work on the CJ Flow async multi-lane milestone on branch
wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe.

Before you do anything, read these files IN ORDER. Do not skip. Do not skim.

1. CLAUDE.local.md — focus on the "THE USER IS NEVER A TESTER" section at top.
2. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/00-working-contract.md
3. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/01-design-review.md
4. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/02-phase-1-rlock-config-and-resource-manager.md
5. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/03-phase-2-dispatcher-pool-and-pool-status.md
6. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/04-phase-3-ghost-watchdog-and-e2e.md
7. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/90-phase-1-execution-log.md
8. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/91-phase-2-execution-log.md
9. src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/92-phase-3-execution-log.md

Your first task is NOT to implement. It is an ADVERSARIAL REVIEW of those
docs. Read them as a hostile outsider whose goal is to find every place
where you could plausibly claim "done" without having actually executed
verification yourself, or where a reader would default to thinking "the
user will do this step." The working contract (#2 above) is the
authoritative rule; every other doc must conform to it.

For each finding, output one row in this table:

| File | Line | Problem | Proposed fix |

Specifically flag:

- Any verification/test step lacking an explicit `EXECUTOR: AI` or
  `EXECUTOR: HUMAN` tag (bare checkboxes and numbered items both count)
- Any `EXECUTOR: HUMAN` line without a same-line justification for why a
  human is required
- Any verb implying human action without a clear subject ("verify,"
  "confirm," "observe," "check," "inspect," "ensure") — each should be
  reframed as an AI assertion or an explicitly justified HUMAN step
- Any "Expected:" / "Confirm:" clause that reads like a user checklist
  rather than an AI assertion with a specific pass/fail criterion
- Any verification step the AI couldn't actually execute against :7999
  (requires GPU, requires a UI click, requires privileged access) — flag
  these even if tagged EXECUTOR: AI, because the tag is a lie if execution
  is impossible
- Any place where sign-off is punted to the user without first requiring
  the AI to produce and report evidence
- Any residual "Manual E2E" / "manual E2E" / "manual test" language

Run these three greps as part of the review and include their outputs
in your findings:

    grep -rn "Manual\|manual" src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/
    grep -rn "EXECUTOR: HUMAN" src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/
    grep -rnE "^\- \[ \] [^E]" src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/

DO NOT fix anything yet. Deliver the findings table.

After the review, wait for my confirmation before proceeding. Phase 1
implementation begins only after I have reviewed your findings and given
explicit go-ahead. Do not start any code edits, do not run any tests, do
not modify any of these docs, until I confirm.

One more constraint: if during the review you notice anything that would
also warrant a design change (not just a wording/tagging fix), flag it
separately in a "Design concerns" section below the findings table. The
seven design decisions recorded in 01-design-review.md (Q1–Q7, recorded
2026-04-23) are the frozen anchor; surface challenges to them, don't
silently override.
```

---

## After pass 1 completes

- Review findings with the user
- Apply agreed fixes
- THEN move to `06-fitness-review-prompt.md`
- Only after BOTH passes are resolved does Phase 1 implementation begin
