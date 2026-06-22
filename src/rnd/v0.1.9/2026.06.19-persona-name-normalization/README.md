# Persona-Name Normalization (v0.1.9)

Centralizing persona/voice-name normalization onto **one root algorithm** so accented /
punctuated names (`María` 🌸, `Mr. Radio` 🦉) key, store, query, and compare identically
across every subsystem — killing the persona-normalizer drift bug-class permanently.

**Branch**: `wip-v0.1.9-2026.06.19-bug-fixing`
**Status (2026-06-21)**: Phase 0 + Phase 1 (foundation) committed; Phases 2–4 pending. Test
execution deferred to the dev server / SWE team (this work was authored on a laptop with no
pytest/Docker).

## Documents

| Doc | What it covers |
|---|---|
| [`01-centralized-persona-normalization-plan.md`](01-centralized-persona-normalization-plan.md) | The full design + 4-phase implementation plan, current-state inventory of the 5+ divergent normalizers, critical files, verification (SWE-team checklist), risks, and the done-vs-remaining handoff status. |

## The design in one line

One identity root (`canonical_persona_key`, keep-spaces) + two thin derivations
(`normalize_for_match` = root minus spaces, for lenient free-text matching;
`persona_slug` = root with spaces→separator, for filenames/topics), all in the new shared
home `src/lupin_mcp/persona_normalization.py`.

## Antecedent records (history this builds on — kept in their original v0.1.8 home)

- `src/rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.18-owed-oracle-persona-normalizer-drift-and-store-unknown-false-idle.md`
  — the READ-seam fix that introduced `canonical_persona_key` and scoped this work as its follow-up.
- `src/rnd/v0.1.8/2026.06.11-arbiter-lineage-persistence-and-persona-matching.md`
  — the arbiter role-misclassification fix (the other face of the drift).
- `src/docs/fleet-liveness-and-task-store-architecture.md` — the one-store/three-readers
  architecture the normalizer's identity key joins across.
