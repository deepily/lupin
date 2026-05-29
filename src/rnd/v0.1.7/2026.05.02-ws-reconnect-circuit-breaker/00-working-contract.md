# Working Contract — WS Reconnect Circuit-Breaker

Before closing any phase of this milestone, the AI MUST have executed,
on its own initiative:

- **:7999 (AI-discretionary) layers** — JS unit tests of `WSChannel`
  (Layer 1, see `07-test-strategy.md`), Python WebSocket protocol tests
  via the existing `src/tests/websocket_smoke/` harness (Layer 2),
  inline `quick_smoke_test()` blocks where added, py_compile of any
  edited Python file, and the import-chain check for `routers/websocket.py`
  if its imports change.
- **:8000 (scheduled) layers** — Playwright Layer-3 (in-page MockWebSocket)
  and Layer-4 (real-server `routeWebSocket` injection) tests, the focused
  Layer-5 reproducer (`docker pause` → circuit-open → unpause → retry),
  and the broader E2E UI sweep (`run-e2e-ui-tests.sh`) for regression.
  Submit via `POST /api/test-suite/submit` with user slot-check per
  project CLAUDE.md §TESTING VENUES. Never inject via curl, direct
  `/api/push`, or in-process server instantiation.
- Every step listed in the Phase N "Verification" section.
- Every checkbox in the paired 9N execution log's "Live API probe" group
  (these are AI-executed via the API against `:7999` for live probes,
  or via scheduled :8000 submissions for monopolize-mode runs — they are
  NOT human operator steps).

The user's involvement is gated to three things and ONLY these three:

1. **Design decisions** — already captured in `01-design-review.md`
   Q1–Q12 FROZEN. New design choices discovered during implementation
   must be surfaced via cosa-voice `ask_multiple_choice` or `converse`,
   never silently decided by the AI.

2. **Slot confirmation for :8000 submissions** — per the test-server
   monopolize-mode protocol, any `/api/test-suite/submit` call requires
   a fresh user ask to confirm the scheduled_at slot does not collide
   with other scheduled tests. This is coordination, not
   approval-for-spend. See project CLAUDE.md §TESTING VENUES for the
   full :7999 / :8000 triage rubric.

3. **Genuine human-judgment calls** — visual subjective UX (banner copy
   tone, banner color choice if any, exact wording of the
   "tunnel exhausted" hint string in dev mode). These must be flagged
   explicitly by the AI with the reason the AI cannot decide. Rare.

If the AI cannot execute a verification step, it must name the specific
blocker (e.g., "this requires Chrome's actual 255-pending cap which
Playwright cannot trigger reliably") and ask — not skip, not defer, not
declare done.

A Phase is "complete" only when (a) every sub-step checkbox in the 9N log
is marked `[x]` with executed-and-reported evidence, AND (b) the AI has
filed the commit hash into the phase's Commits table. Anything less is
a violation of this contract.

## Pre-Phase Audit (Convention 4)

At the start of EACH phase (1–5), before writing any code, the AI must:

1. Re-read `99-plan-review-findings.md` to recall any phase-N
   deferrals (e.g., the Phase-5 close-code-collision sweep, the
   Phase-2 cache-bust pattern lookup, the Phase-3 banner insertion
   sentinel, the Phase-4 init-order site).
2. Re-read the relevant feedback memories (the table at
   `99-plan-review-findings.md` §6).
3. Surface any newly-discovered violation BEFORE writing code, not
   during code review.

This is the "execute-time audit" called out by memory
`feedback_audit_plans_at_execute_time`.

## Tests-Are-AI-Owned Reminder

Per `CLAUDE.local.md` THE USER IS NEVER A TESTER:

- "Manual E2E" in any doc in this set means "not yet automated by me"
  — it does NOT mean "the user does it." If a step appears that I
  genuinely cannot automate (e.g., visual pixel-perfect intent), it
  carries `EXECUTOR: HUMAN <specific reason>` per Convention 3.
- Bug discovery during testing is auto-queued to `bug-fix-queue.md` if
  bug-fix mode is active, OR surfaced in the 9N log's "Bugs filed"
  section. Never handed back to the user as "let me know if this fails."
- Reporting at phase close is tabular: per-tier pass/fail count, in the
  9N log.
