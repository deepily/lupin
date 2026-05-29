# Phase 0 Decisions Captured — Multiplexer Notifications UI Rebuild

**Date**: 2026-05-03
**Status**: All 11 decisions captured. Phase 1 scaffolding design draft begins.
**Anchor docs**: `00-synthesis-and-roadmap.md` §5 (decision questions), `01-execution-plan.md` (tactical plan), `01-working-contract.md` (verification obligations)

This document is the durable record. Question IDs Q1–Q11 mirror `00-synthesis-and-roadmap.md` §5.

---

## Q1 — Name + URL

**Decision**: `multiplexer` at `/app/multiplexer`

**Rationale**: Distinct name keeps the new module tree and URL parallel-isolated from the existing `notifications` surface. Captures the multi-stream, multi-pane character of the new UI (jobs queue + notifications list + voice cards + focus tray + audio recorder + conversation pane). URL slot verified free in `src/cosa/rest/routers/pages.py:24-40` route table.

**Forward refs**: Phase 1 design doc registers the route + creates `multiplexer.html` shell.

---

## Q2 — Directory layout

**Decision**: Accept the synthesis §4.2 proposal as-is.

**Rationale**: Tree provides clean module boundaries from line one — `auth/`, `transport/`, `api/`, `stores/`, `tts/`, `audio/`, `render/`, `shared/`, `observability/`. No path renames requested.

**Forward refs**: Phase 1 design doc creates `src/fastapi_app/static/js/multiplexer/boot.ts` + minimal subdirs; later phases populate the rest.

---

## Q3 — Build chain

**Decision**: `esbuild` with `--watch`, build only. No Vitest yet.

**Rationale**: Single binary, content-hashed output kills the manual `?v=` cache-bust ritual. Watch mode auto-rebuilds during dev. Test execution stays manual per `01-working-contract.md` until Phase 7 hardening review re-evaluates whether to add Vitest for save-on-change unit feedback.

**Forward refs**: Phase 1 design doc creates `src/scripts/build-multiplexer.sh` driving esbuild + `tsconfig.json` at project root.

---

## Q4 — TypeScript strict mode

**Decision**: `tsc --strict` plus `noUncheckedIndexedAccess`.

**Rationale**: First TypeScript in the project. Strict mode catches errors vanilla JS misses. `noUncheckedIndexedAccess` adds undefined-checks on array/object indexing — important for greenfield safety. Pragmatic types: `any` allowed at boundaries; no compiler-enforced patterns beyond strict.

**Forward refs**: Phase 1 design doc specifies the `tsconfig.json` content.

---

## Q5 — ws-channel.js disposition

**Decision**: Copy + apply fixes in `src/fastapi_app/static/js/multiplexer/transport/ws-channel.ts`.

**Rationale**: Greenfield isolation principle. Original `ws-channel.js` keeps serving `notifications.html` until cutover. Divergence is permanent. Phase 3 applies Claude analysis §1.1 (binary-frame fix), §2.2 (lifecycle removal — orchestrator owns lifecycle), §2.5 (no JSON round-trip in dispatch chain).

**Forward refs**: Phase 3 design doc owns the port + fix work.

---

## Q6 — XState scope

**Decision**: XState for high-churn modules only — auth, TTS, action-required, connection. Plain reducers everywhere else.

**Rationale**: XState is high-value for event-driven flows with many transitions and complex invariants. Overkill for simple stores (notifications list, sender map). Hybrid keeps dependency cost low while applying the actor model where it pays off.

**Forward refs**: Phase 4 design doc identifies which stores get XState actors vs plain reducers, with module-by-module rationale.

---

## Q7 — Token storage migration

**Decision**: Out of scope for the multiplexer rebuild.

**Rationale**: Moving off `localStorage` requires server-side HttpOnly-cookie + CSRF redesign — FastAPI auth router changes, refresh-flow changes, CSRF middleware. Bundling that into the frontend rebuild bloats scope and adds server-side risk. Tracked as a separate post-cutover follow-up.

**Forward refs**: Documented in `00-synthesis-and-roadmap.md` §3 "What is NOT in this roadmap"; will surface as a TODO.md item after multiplexer ships.

---

## Q8 — Service Worker / offline outbox

**Decision**: Out of scope for this iteration.

**Rationale**: Service Worker + Background Sync for replay-safe mutations is valuable but adds significant complexity (registration lifecycle, version skew, cache invalidation). Defer to post-cutover follow-up if/when offline support becomes a real requirement.

**Forward refs**: Documented in `00-synthesis-and-roadmap.md` §3 "What is NOT in this roadmap".

---

## Q9 — Cutover release count

**Decision**: **Unbounded** — `notifications.html` stays alive indefinitely after cutover; manual removal only.

**Rationale**: Override of the recommended 1-release window. Maximum fallback safety; no forced removal date. Once confidence in multiplexer is established, the user can request `notifications.html` removal as a separate task. The legacy URL becomes a permanent fallback option until explicitly retired.

**Forward refs**: Phase 9 cutover design doc explicitly excludes auto-removal of `notifications.html`. Cutover means "multiplexer is the default" — not "notifications.html is gone."

---

## Q10 — Per-phase user gate

**Decision**: Per-phase gate — design doc → user approve → code lands → repeat. Nine gates total (Phases 1 through 9).

**Rationale**: Lowest-risk cadence. Matches the established BFE/TFE pattern in this codebase. Each phase's design doc gets explicit user approval before any code in that phase lands. Drift between intent and implementation is caught at design time, not at code time.

**Forward refs**: Each phase's design doc lands as `0N-phaseM-design.md`; execution log section in `90-execution-log.md` opens only after user approval. Phase 1 design doc is `02-phase1-scaffolding-design.md`.

---

## Q11 — Adversarial review owner

**Decision**: Claude clean-context per phase + OpenAI at Phase 8 only.

**Rationale**: Each phase's design doc gets a clean-context Claude agent review (separate Agent spawn, no session history, structured findings table). Phase 8 viability gate runs the full triple-review: Claude clean-context + OpenAI deep-research + tracking-doc audit. Two-reviewer pyramid at every phase reserved for Phase 8 only — keeps per-phase overhead manageable while preserving full rigor at the cutover gate.

**Forward refs**: Each phase's design doc references the canonical PIP review machinery at `planning-is-prompting/workflow/plan-review.md` — REUSE pre-pass → Pass 1 (Fitness) → Pass 2 (Adversarial), parametrized via `{{slots}}` filled per milestone. **No retargeting of milestone-specific prompt clones is required** — the canonical doc IS the prompt source. The two files at `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/02-testing-review-prompt.md` and `03-fitness-review-prompt.md` are stale clones lifted from cj-flow and are NOT canonical — ignore them. (The directory's `01-working-contract.md` is a Layer-2 anchor instance per PIP §1 and stays.) Phase 8 design doc owns the full triple-review protocol on top of the per-phase Pass 1/2 machinery. See Q11 amendment below for the per-phase sequence.

---

---

## Q10 amendment — spine bundle for Phases 1-3 (2026-05-04)

**Decision refinement**: The per-phase gate stands as canonical for Phases 4-9. **Phases 1, 2, and 3 design docs land as a single bundled approval unit** ("the spine bundle") because their contracts (TS toolchain → service shapes → transport wrappers) are tightly coupled and benefit from coherent cross-phase design + review.

**Rationale**: Phase 1 (TS config + esbuild + ESLint) constrains Phase 2 (AuthManager + ApiClient + StorageService + EventBus + BroadcastChannel) shapes. Phase 2 contracts (event shape, refresh callback) are inputs to Phase 3 (ws-channel.ts + QueueTransport + AudioTransport + ClaudeCodeTransport). Designing them serially would pin earlier decisions before later constraints surface. Designing them together — and reviewing the bundle as a unit — catches contract-interface gaps at design time, when correction is cheap.

**Spine bundle scope**:
- Design docs: `02-phase1-scaffolding-design.md` + `03-phase2-foundation-design.md` + `04-phase3-transport-design.md`
- Single plan-review pass (per Q11 amendment) over all three with `{{PLAN_DOC_PATHS}}` listing all three
- Single user approval gate: ALL three design docs approved → spine implementation begins
- Implementation cadence within the bundle stays per-phase (Phase 1 implements + verifies + commits before Phase 2 code starts) to preserve working-contract verification discipline

**After spine ships** (end of Phase 3 implementation): natural go/no-go gate. If toolchain or transport surface issues that invalidate Phases 4-9 assumptions, project re-scopes BEFORE committing to 6 more design docs. If clean, per-phase from Phase 4 onward, lessons-informed.

**Forward refs**: §3 Phase Bundling subsection in `00-synthesis-and-roadmap.md`; "Approval coupling" notes in each of the three spine-bundle design docs (`02-phase1-scaffolding-design.md` already updated 2026-05-04; `03-phase2-foundation-design.md` and `04-phase3-transport-design.md` carry the same note from the moment of creation).

---

## Q11 amendment — review timing follows canonical PIP plan-review.md (2026-05-04)

**Decision refinement**: Per-phase clean-context Claude review timing aligns with the canonical PIP `plan-review.md` workflow. **Reviews fire AFTER the per-phase design doc is drafted (= tracking-doc generation per `/p-is-p-02-documentation`) and BEFORE the user approves it / the 90-execution-log section opens / code begins.**

**Canonical sequence per phase** (Phase 4 onward; spine bundle handles Phases 1-3 together as one bundled review pass):

1. AI drafts `0N-phaseM-design.md`
2. AI fills `plan-review.md` `{{slots}}` for this phase (slot table is in `02-phase1-scaffolding-design.md` for the spine bundle; per-phase doc carries its own slot table from Phase 4 onward)
3. AI spawns clean-context Claude Agent → REUSE pre-pass per PIP §4
4. User-decision gate per PIP §6 → AI applies approved fixes; appends "Prior art referenced" section to design doc / index
5. AI spawns clean-context Claude Agent → Pass 1 (Fitness) per PIP §5
6. User-decision gate per PIP §6 → AI applies approved fixes; runs convergence re-grep per PIP §7
7. AI spawns clean-context Claude Agent → Pass 2 (Adversarial) per PIP §8
8. User-decision gate per PIP §9 → AI applies approved fixes; runs convergence re-grep
9. Termination check per PIP §10 (0 new structural findings OR 2 rounds done; whichever first)
10. Idempotency marker updated per PIP §12 (`last-reviewed-at: YYYY-MM-DD (commit-hash)` line in design doc or 00-index)
11. User approves the post-review design doc
12. AI opens `90-execution-log.md` Phase N section (status: in-progress)
13. AI implements + executes verification matrix + files commit hashes
14. AI closes Phase N section (status: complete)
15. Repeat for Phase N+1

**Phase 8 carve-out**: Phase 8 (viability gate) uses the SAME machinery + adds OpenAI deep-research over the implementation per Q11 (original decision). Phase 8 is post-implementation by definition; this amendment concerns the per-phase reviews leading up to it.

**Source-of-truth**: `planning-is-prompting/workflow/plan-review.md` is canonical. The two prompt files at `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/02-testing-review-prompt.md` and `03-fitness-review-prompt.md` are stale milestone-specific clones and are NOT canonical — ignore them. The directory's `01-working-contract.md` is a Layer-2 anchor instance per PIP plan-review §1 and STAYS as-is.

**Forward refs**: §4.4 tracking-doc layout in `00-synthesis-and-roadmap.md`; "Plan-review pointer" sections in each phase design doc replace what would have been a milestone-specific "Adversarial review prompt" section.

---

## Q12 — Multi-tab support (added 2026-05-04 PM)

**Decision** (2026-05-04 PM, ratified during Phase 4 plan-review pipeline / Q4): **OUT OF SCOPE.** The multiplexer is a single-tab application. Same UI bound to same server+port across multiple tabs has no real use case for this product, and the coordination cost (cross-tab state replication, ordering invariants, double-broadcast races) is disproportionate to the value.

**Rationale**: A user who wants two views of the same notification surface opens a second WINDOW of the same tab; same browser process, same JavaScript context, same WebSocket. They get exactly one source of truth. Multi-tab adds N WebSocket connections + N stores + cross-tab coordination protocol for zero functional gain.

**Implication**: `BroadcastChannel("lupin")` wrapper from Phase 2 (`src/fastapi_app/static/js/multiplexer/shared/broadcast.ts`) is INERT — the code exists but no consumer wires it. boot.ts does NOT call `broadcast.start()`. Phase 2's `BROADCAST_WHITELIST` constant exists but is never consulted at runtime. See `TODO.md` "Phase 2 cleanup" follow-up for removal tracking.

**Forward refs**:
- Phase 4 design doc drops the "Cross-tab via BroadcastChannel?" column from store summary table; Q4 ratified as "sidestepped per Q12"
- Phase 5+ design docs MUST NOT add cross-tab features without re-opening this decision via a Q12 amendment
- Phase 9 cutover: `notifications.html` (legacy) keeps its multi-tab behavior — Q12 governs the multiplexer only

---

## Cross-reference summary

| ID | Topic | Decision |
|---|---|---|
| Q1 | Name + URL | `multiplexer` at `/app/multiplexer` |
| Q2 | Directory layout | Accept synthesis §4.2 |
| Q3 | Build chain | esbuild + `--watch`, build only |
| Q4 | TypeScript | `tsc --strict` + `noUncheckedIndexedAccess` |
| Q5 | ws-channel.js | Copy + fix in `multiplexer/transport/ws-channel.ts` |
| Q6 | XState scope | High-churn modules only (auth, TTS, action-required, connection) |
| Q7 | Token storage | Out of scope (post-cutover follow-up) |
| Q8 | Service Worker | Out of scope (post-cutover follow-up) |
| Q9 | Cutover release count | Unbounded (manual removal only) |
| Q10 | Per-phase gate | Yes, 9 gates total. **Amended 2026-05-04**: Phases 1-3 bundle as the spine (single approval unit); Phases 4-9 individual gates. |
| Q11 | Review owner | Claude clean-context per phase + OpenAI at Phase 8. **Amended 2026-05-04**: timing per canonical PIP `plan-review.md` (REUSE → Fitness → Adversarial; review fires AFTER design doc draft, BEFORE user approval). Stale clones at `2026.05.03-testing-and-fitness-prompts/02-` + `/03-` are NOT canonical. |
| Q12 | Multi-tab support | **OUT OF SCOPE.** Single-tab application policy ratified 2026-05-04 PM during Phase 4 plan-review (sidesteps Q4 cross-tab BroadcastChannel question). Phase 2 `broadcast.ts` is inert; Phase 2 cleanup tracked as `TODO.md` follow-up. |

## Self-audit

| Memory | Compliance |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ This doc IS the Phase 0 capture |
| `feedback_documentation_first_protocol` | ✅ Decisions captured before any Phase 1 code |
| `feedback_audit_plans_at_execute_time` | ✅ Each phase design doc will re-audit at execute time |
| `feedback_lupin_only_never_cosa` | ✅ Q1 route registration in `pages.py` flagged as CoSA-context user commit |
| `feedback_never_auto_commit_push` | ✅ Q10 per-phase gate enforces explicit user approval at every phase boundary |
