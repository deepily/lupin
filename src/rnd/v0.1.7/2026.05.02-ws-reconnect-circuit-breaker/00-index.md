# WebSocket Reconnect Circuit-Breaker — Doc Set Index

**Status**: Plan drafted, plan-review findings embedded, awaiting user go-ahead.
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Format**: Pattern A/B/C (multi-doc design-set + paired execution logs).
**last-reviewed-at**: 2026-05-02 (pre-implementation; updated on each review re-run)

---

## Phase 0 — Documentation (this doc set) is mandatory and PRECEDES code

Per `~/.claude/CLAUDE.md` `DOCUMENTATION-FIRST PROTOCOL`: every document
listed in §Doc-Set Layout below MUST exist on disk before a single line of
JS or Python is touched. The Phase 0 deliverable is the doc set itself,
and the user's go-ahead on the doc set is the authorization to begin
Phase 1 code. Documentation is not a side-deliverable; it is the gating
artifact.

---

## Doc-Set Layout

| # | File | Purpose |
|---|------|---------|
| 00 | `00-index.md` (this) | Navigation + status block + Phase 0 reminder |
| 00 | `00-working-contract.md` | Test ownership, test layers, AI vs HUMAN execution rubric |
| 01 | `01-design-review.md` | Synthesized design + Q1–QN FROZEN decisions |
| 02 | `02-phase-1-ws-channel-module.md` | Extract `WSChannel` state machine into a stand-alone JS module |
| 03 | `03-phase-2-notifications-integration.md` | Wire `WSChannel` into `NotificationsUI`; rip out shared retry counter, redundant scheduling, counter-zeroing health monitor |
| 04 | `04-phase-3-circuit-banner-and-retry.md` | Add UI banner + Retry-now button on `ws-circuit-open` event |
| 05 | `05-phase-4-page-lifecycle.md` | `visibilitychange`, `pageshow`/`pagehide`, `online`/`offline`, `freeze`/`resume` integration |
| 06 | `06-phase-5-server-side-hardening.md` | Explicit close codes for auth failures; uvicorn `ws_ping_interval` survey; documentation touch-ups |
| 07 | `07-test-strategy.md` | Five-tier test pyramid + venue routing table + automated reproducer recipe |
| 08 | `08-rollout-and-rollback.md` | Feature-flag-free rollout (justified), rollback path, soak metric, success criteria |
| 90–94 | `9N-phase-N-execution-log.md` | Per-phase execution log; created at phase start, NOT now |
| 99 | `99-plan-review-findings.md` | REUSE pre-pass + Pass 1 (adversarial) + Pass 2 (fitness) findings tables |

Phase docs (02–06) all conform to `EXECUTOR: AI / HUMAN <reason>` Convention 3
on every verification step. The execution logs (90–94) are stubbed, not
written, until a phase begins — per Convention 4 (don't pre-fabricate evidence).

---

## Reading Order

For first-time review:
1. `00-working-contract.md` — anchor (Layer 2 per plan-review §1)
2. `01-design-review.md` — synthesized design + frozen decisions (Layer 3)
3. `07-test-strategy.md` — verifies Layer-1 mandate is honored
4. `02..06-phase-N-*.md` — phase-by-phase implementation plan
5. `08-rollout-and-rollback.md` — landing strategy
6. `99-plan-review-findings.md` — pre-execution review pass results

For re-invocation after edits, see plan-review §11 (Idempotency).

---

## Prior Art Referenced

(populated during REUSE pre-pass; see `99-plan-review-findings.md` §1)

---

## Open Follow-ups

(populated as Layer-3 design concerns are deferred or as plan-review
rounds find issues that get parked rather than fixed)

---

## Source Inputs

This doc set synthesizes three pre-existing inputs (kept in the same
directory as historical artifacts; do not re-execute them):

- `2026.05.02-ws-reconnect-circuit-breaker-expert-brief.md` — original forensic brief sent to outside reviewers
- `2026.05.02-ws-reconnect-circuit-breaker-solution-claude.md` — Claude reviewer's response
- `2026.05.02-ws-reconnect-circuit-breaker-solution-openai.md` — OpenAI reviewer's response

The synthesis lives in `01-design-review.md` §2; differences and how they
were resolved live in `01-design-review.md` §4.
