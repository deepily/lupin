# Phase 8 — Chorus-Mode Color & Glyph UX Follow-up

**Date**: 2026.05.12
**Status**: 📝 Design stub — DEFERRED until after Phases 1–7 land and chorus mode has been used in practice.
**Owner**: [LUPIN] (Rick)
**Phase**: 8 of 8 (deferred follow-up)
**Prerequisites**: All of Phases 1–7. Live experience with chorus mode for 1–2 weeks before this phase is scoped.
**Companion docs**: [`00-index.md`](00-index.md), [`03-open-questions.md`](03-open-questions.md) (Q1 + Q2)

---

## 1. Why this phase exists

Under solo mode, the persona color pool excludes green because green-on-success is reserved for the mic-monopoly pin (per [[feedback_no_green_in_persona_pool]]). The reservation has clear utility: green identifies the one session that currently holds speakerphone.

Under chorus mode, there is no mic monopoly to signal. Multiple sessions can be speakerphone-on simultaneously, so a single highlighted card no longer makes sense. The green reservation has no use-case in chorus.

This phase asks: what should the chorus-mode visual treatment be? Three options were sketched in the May 12 plan and [[03-open-questions.md#q1]]:

| Option | Meaning | Tradeoff |
|---|---|---|
| (a) Green = speaker-on | All speakerphone-on cards green (most cards in chorus) | Default-green dilution; signal weak |
| (b) Green = phone-mode | Phone-mode cards highlighted as the deliberate exception | Inverts intuition (green ≠ "on") |
| (c) Drop green reservation in chorus; toggle uses icon shape only | Phone glyph vs speaker glyph; color free for personas | Frees the color pool; cleanest |

The May 12 plan **recommends (c)** but defers the decision.

---

## 2. Why this is deferred

Three reasons:

1. **Live experience needed**. The right answer depends on what chorus mode feels like in daily use. Hypothetical UX choices made before living with the experiment risk solving the wrong problem.
2. **Solo-mode unchanged**. Phases 1–7 preserve solo's UX exactly; the deferral does not block the parallel-preservation goal.
3. **Single-AC scope**. The color/glyph question is small enough to be a single follow-up PR. It does not need to be packed into the coordinated Phases 1–7 PR.

---

## 3. What this phase will do (when scoped)

**Step 1 — Live-use feedback collection** (1–2 weeks after Phases 1–7 land):

- Use chorus mode for daily voice work.
- Note pain points: did you ever struggle to tell which session was speakerphone-on? Did the lack of pinning cause card-drift annoyance? Did the persona colors feel cluttered?
- Capture observations in `03-open-questions.md` Q1 with timestamps.

**Step 2 — UX decision** (Rick chooses one of (a) / (b) / (c) or proposes a new option):

- Update `90-decisions-log.md` with the choice and rationale.
- Update [[feedback_no_green_in_persona_pool]] memory: solo reservation untouched; chorus treatment per the decision.

**Step 3 — Implementation** (if (c) is chosen):

- Update persona color pool generator to include green-spectrum colors (Q2 in open questions).
- Update `SpeakerphoneToggle` to use icon-shape-only differentiation (no color change).
- Add tests covering the icon-only differentiation.
- Drop the `speakerphone-active-solo` CSS class for chorus-mode cards (already conditional per Phase 7 design).

**Step 3 — Implementation** (if (a) or (b) is chosen):

- TBD per the choice.

**Step 4 — Tests + verification**:

- Unit tests covering the chosen visual treatment.
- Manual verification in browser with chorus mode active.
- Coverage maintained at `c8 --100` per [[feedback_100pct_coverage_multiplexer]].

---

## 4. Scope guardrails

This phase is **single-AC**, **single-PR**. Do not let it grow:

- **In scope**: persona-color-pool changes, toggle glyph choices, visual treatment of speakerphone-on cards in chorus.
- **Out of scope**: any backend changes; any solo-mode visual changes; any new mode introduction (e.g., duet/trio — those are Q3 in open questions, separate work).

---

## 5. Implementation timing (when scoped)

Estimated active work: 60–120 minutes including tests + coverage.

---

## 6. Cross-cutting concerns

### Memory check (at scoping time)

- [[feedback_no_green_in_persona_pool]] — solo reservation rule still in force; chorus rule defined by this phase's decision.
- [[feedback_100pct_coverage_multiplexer]] — coverage gate applies.
- [[feedback_no_migration_code]] — if persona colors change, existing assignments are regenerated (not migrated).

---

## 7. Hand-off

This is the terminal phase. After Phase 8 lands, the speakerphone subdir is in a "feature complete + reversible" state. No further phases planned unless new use-cases (duet/trio, color-pool expansion, etc.) emerge.
