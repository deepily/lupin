# Pass-2 Design Review — Ownership-Language Audit — LanceDB → PostgreSQL + pgvector Migration

**Reviewer**: Clayton 😎 (session `21ab2cc2`) · **Date**: 2026-07-01
**For manager**: Mr. Radio 🦉
**Doc under review**: `src/rnd/v0.2.0/2026.06.30-lancedb-to-postgres-pgvector-migration-design.md` (248 lines)
**Review type**: Cascaded review Stage 3 / Pass-2 — **Ownership-Language Audit** (`/plan-review-cascaded`: REUSE → Pass-1 → **Pass-2**)
**Rubric**: `planning-is-prompting/workflow/plan-review-cascaded-personas.md` §Persona 5 (Conventions 3/5/6) + manager brief (ownership gaps · silent hand-offs · untagged cross-actor deps · ACs with no named verifier)
**Scope boundary**: NOT a correctness/security re-review — Pass-1 (Cheech, `09036160`, APPROVE-WITH-REVISIONS) owns that. This pass hunts WHO-executes / WHO-verifies / how-decisions-propagate only.

---

## VERDICT: **CLEAR-WITH-REVISIONS**

The design is buildable and the correctness layer is already clean (Pass-1). No BLOCK-level ownership defect. But the ownership/hand-off layer has real gaps that should be folded **before the SWE build crew spins up**, because two whole phases (P0, P5) currently have **no named owner**, three Rick-decisions (Q1/Q2/Q3) have **no delivery path to the lanes that consume them**, and the open-question agenda **drifted stale against the folded Pass-1 F1** (still says "confirm cosine" when metric is `dot`). None force a rework; all are foldable revisions.

---

## Cascade-completeness check (manager brief item)

- **REUSE (Stage 1 Usability/Reuse) — FOLDED, not missing.** Pass-1 carried the reuse verdict: Cheech's C1 (additive-Postgres — reuses the existing DAO/engine/session/alembic machinery), C5 (doctrine reuse — `feedback_no_migration_code`), and the doc's §4.3 (repositories mirror the existing `rest/db/repositories/*` pattern; "one descriptive name everywhere, no shim") all answer the Stage-1 headline "Is the work reusing what already exists?" **REUSE requirement is satisfied.**
- **Pass-1 (Stage 2 Viability/Gap + adversarial)** — COMPLETE, folded (F1–F4 into the doc; F5/F6/F7 flagged build-owed).
- **Pass-2 (this)** — this document closes the cascade gate.

---

## Findings (grouped by ownership-defect class; no severity ranking per Persona-5 boundary)

### Class A — OWNERSHIP GAPS (step/phase with no named owner)

**O1 — §8 P0 + §9: schema-inventory phase (P0) has NO lane/owner.**
§9 lane decomposition maps Lane A→P1, B→P2, C→P3, D→P4 — but **P0 and P5 are unassigned**. P0 (dump the live schema of all 6 tables; confirm dims) is the prerequisite that makes §4.1 complete and settles Q3/Q6, yet nobody owns it. A build crew reading §9 finds no lane responsible for the first thing that must happen.
*Fix*: assign P0 to Lane A as its task-0 (or a manager-owned discovery spike), explicitly gating Lanes B/C on its completion.

**O2 — §8 P5 + §9: cutover+soak+teardown phase (P5) has NO lane/owner. (highest-value gap)**
P5 bundles four unowned actions: (a) flag-flip "on a watched run" — *who watches?*; (b) soak-clean determination — *who decides, on what signal?*; (c) teardown of LanceDB dep/keys/on-disk store; (d) the Pass-1 **F5** GCS-synced lancedb teardown in cloud envs. This is the phase most likely to silently land on Rick because it's the one with human-judgment-shaped verbs and no executor.
*Fix*: assign P5 to a named owner (recommend **manager-owned**, `EXECUTOR: AI` watched-run + a **defined soak-pass signal** — see H3), and fold F5 GCS teardown into P5 explicitly as a sub-step.

**O3 — §7: test tiers + equivalence harness carry NO EXECUTOR tag; "one-off comparison" trips Convention 5.**
None of the four §7 tiers (unit/integration/smoke/equivalence) is `EXECUTOR:`-tagged (Convention 3 miss — expected at design stage, but must be named before build). The **equivalence harness** — "a one-off comparison proving Postgres nearest-k matches LanceDB nearest-k … within float tolerance" — reads as *eyeballed-once*, the classic Convention-5 "Manual E2E" ownership gap (user-as-tester risk). It also has no pytest home and an **unquantified** "float tolerance."
*Fix*: tag every tier `EXECUTOR: AI`; give the harness a real pytest home (e.g. `src/tests/integration/`), a **quantified** tolerance, and a **programmatic pass/fail** — never "one-off."

---

### Class B — SILENT HAND-OFFS (phase assumes another actor did X; no explicit hand-off/receipt)

**H1 — §10 Q1 → §8 P4 / §9 Lane D: no receipt carries Rick's backfill decision to the backfill lane.**
Lane D (P4) is conditional on "if Q1 = backfill," but nothing specifies **who surfaces Q1 to Rick, records the answer, and signals Lane D to execute-or-skip.** Lane D silently assumes the decision arrived.
*Fix*: name the decision-broker (recommend **manager**) + a receipt: Q1 resolved → manager posts the ruling → Lane D gated on that post.

**H2 — §10 Q2/Q3 → §8 P1 / §9 Lane A: index-metric + dim decisions must reach Lane A before it writes alembic, but no hand-off is specified.**
Lane A (P1) creates the tables + HNSW index + column dims — it structurally depends on Q2 (index/operator) and Q3 (dim=768 confirmed) being settled first, yet silently assumes it. If Lane A starts before Q2/Q3 land it bakes wrong choices into the migration.
*Fix*: gate Lane A P1 start on Q2/Q3 resolution, with the same named broker + receipt as H1.

**H3 — §6 / §1: soak → teardown transition has no named owner and no defined pass signal.**
"removed after a soak window" (§1) and "flip flag to postgres on a **watched run** → soak → remove LanceDB" (§6) assume someone declared the soak clean — but the success criterion is unobservable (Persona-5 rubric Q4): "soak is clean" has no defined metric/log signal, and no actor is named to declare it.
*Fix*: define the soak-pass signal (an observable metric/log threshold over the window) + name who declares it (recommend manager, `EXECUTOR: AI` on the signal check).

---

### Class C — OWNERSHIP-OF-CONSISTENCY drift (open-question agenda went stale against the folded Pass-1 F1)

**S1 — §8 P0 + §10 Q2 still say "confirm cosine" — contradicts folded Pass-1 F1 (metric is `dot`).**
§4.2 and §11 were correctly updated by the F1 fold (metric = `dot`, cosine-safe only under the L2-norm invariant), but the **open-question agenda and the P0 verification step were not**: §8 P0 says "Confirm cosine metric"; §10 Q2 says "ratify HNSW + cosine … Confirm LanceDB's current metric is cosine." A reviewer/implementer reading §10 Q2 (the "review agenda") would go confirm **the wrong thing**. This is an internal accountability gap — the agenda that drives WHO-confirms-WHAT points at a retracted premise.
*Fix*: rewrite Q2 → "ratify pgvector operator: inner-product `<#>` to mirror live `dot`, OR cosine `<=>` justified by the §4.2 L2-normalization invariant; metric is `dot` (Pass-1 F1-confirmed, not cosine)"; rewrite §8 P0 "Confirm cosine metric" → "Confirm the L2-normalization invariant holds on BOTH embedding paths (local confirmed; OpenAI path owed per F1)."

**S2 — §10 Q3 "P0 settles it" inherits O1's ownerlessness.**
Q3 (dim=768 across all prod tables) is delegated to P0 — but P0 has no owner (O1). The dim confirmation is therefore unowned by transitivity. Resolves automatically once O1 assigns P0.

---

### Class D — ACCEPTANCE CRITERIA with no named verifier

**A1 — §1 done-state bullets don't say WHO verifies / rollback is claimed but never exercised.**
- "Similarity search returns results equivalent (same metric, same top-k)" — verified by the §7 harness but not linked or tagged (and the harness itself is O3-ungoverned).
- "100% line/branch/function coverage" — the mandate is named (Convention 6 satisfied at the mandate level) but no per-phase `EXECUTOR: AI — pytest --cov / c8 --100 on <module>` assertion exists.
- "A documented cutover + **rollback** procedure" — rollback (§6 = flip flag back to `lancedb`) has **no test and no verifier**. A working rollback is asserted in the done-state but **nobody in the plan ever exercises it**. If cutover fails and rollback was never tested, the recovery path is unproven.
*Fix*: tag each §1 done-state bullet with its verifying mechanism + executor; add a **rollback-path test** (`EXECUTOR: AI`) so rollback correctness is *observed*, not asserted.

---

## Build-owed items from the doc header (F5/F6/F7) — ownership placement

- **F5 (GCS lancedb teardown)** — folds into **O2 / P5** (named there). Currently owner-less.
- **F6 (spaced column `"normalization version"` rename)** — belongs to whoever owns **P0→§4.1 full-schema** (O1's owner). Currently owner-less.
- **F7 ("eight modules" count)** — cosmetic; reconcile whenever §3 is next touched.

---

## Summary for Mr. Radio

- **Verdict**: CLEAR-WITH-REVISIONS — no BLOCK. Cascade is complete (REUSE folded into Pass-1; Pass-1 done; Pass-2 = this).
- **Fold before spinning the SWE crew** (they need owners + a decision-delivery path): **O1** (P0 unowned), **O2** (P5 unowned — highest value, absorbs F5), **H1/H2** (Rick's Q1/Q2/Q3 decisions have no receipt to Lanes D/A), **S1** (Q2/P0 still say "cosine" — stale vs folded F1).
- **Fold soon**: **O3** (tag test tiers + give the equivalence harness a pytest home + quantified tolerance), **H3** (define the soak-pass signal + owner), **A1** (tag done-state verifiers + add a rollback-path test).
- **Cosmetic**: S2 (resolves with O1), F6/F7 placement.

Once these ownership/hand-off revisions are folded, the cascade gate is closed and the build is safe to staff.
