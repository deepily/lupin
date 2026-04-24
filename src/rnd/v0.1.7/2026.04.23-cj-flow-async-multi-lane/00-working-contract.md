# Working Contract — CJ Flow Async Multi-Lane

Before closing any phase of this milestone, the AI MUST have executed,
on its own initiative:

- All automated layers against :7999 — unit, smoke (`/smoke-test-remediation FULL`),
  WebSocket smoke, E2E UI (`--bg` mandatory), integration (`--bg` mandatory,
  final gate).
- Every step listed in the Phase N "Verification" section.
- Every checkbox in the paired 9N execution log's "Protocol E2E" group
  (these are AI-executed via the API against :7999 — submit via
  /api/push, poll /api/get-queue/done, read /api/queue/pool-status,
  observe WebSocket events — they are NOT human operator steps).

The user's involvement is gated to three things and ONLY these three:

1. **Design decisions** — already captured in `01-design-review.md` Q1–Q7.
   New design choices discovered during implementation must be surfaced
   via cosa-voice `ask_multiple_choice` or `converse`, never silently
   decided by the AI.

2. **Slot confirmation for :8000 submissions** — per the test-server
   monopolize-mode protocol, any /api/test-suite/submit call requires
   a fresh user ask to confirm the scheduled_at slot does not collide
   with other scheduled tests. This is coordination, not approval-for-spend.

3. **Genuine human-judgment calls** — visual pixel comparison in a
   subjective sense, UX intent, copy tone. These must be flagged
   explicitly by the AI, with the reason the AI cannot decide. Rare.

If the AI cannot execute a verification step, it must name the specific
blocker (e.g., "needs GPU and I'm prohibited from GPU workloads") and
ask — not skip, not defer, not declare done.

A Phase is "complete" only when (a) every sub-step checkbox in the 9N log
is marked [x] with executed-and-reported evidence, and (b) the AI has
filed the commit hash into the phase's Commits table. Anything less is
a violation of this contract.
