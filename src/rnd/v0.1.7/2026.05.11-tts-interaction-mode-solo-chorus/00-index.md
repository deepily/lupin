# TTS Interaction Mode (Solo & Chorus) — Documentation Index

**Status**: ✅ **Minimum-viable closed 2026-05-13.** Phases 1-7 committed (commits `c82ee04`, `8a8c31c`, `9ba4db5`, `e17d7d7`, `b6f1ac2`). Solo/chorus framework live; toggle widget continues to function in legacy `notifications.js`. Phase 7b (multiplexer toggle widget migration) and Phase 8 (chorus UX polish) filed as separate follow-on tickets in `TODO.md` — both intentionally out-of-scope for this close per `97-phase7-execution-log.md` §7.
**Owner**: [LUPIN]
**Started**: 2026.05.11 (think-out-loud session 77e1bb27, Mr. Radio 🦉)
**Last updated**: 2026.05.13 (close-out push, session 6d663b6c Arnold 🪨)

---

## Scope of this subdirectory

This subdirectory holds the design exploration for adding a global INI switch — `tts interaction mode = solo | chorus` — that selects between two **permanently maintained** TTS interaction models for the cosa-voice MCP server:

- **`solo`** — today's behavior, preserved pixel-perfect: one session at a time speaks via TTS, with displacement enforcement when another session activates. Asyncio.Lock + scan + green mic-monopoly pin all live.
- **`chorus`** — the new experiment: N sessions can be in speakerphone mode simultaneously, persona voices disambiguate at the listener's ear, no displacement.

Both branches are first-class and permanent per [[feedback_feature_flag_preserves_old_path]]. The experiment is to live with chorus while keeping solo as a known-good revert target.

The naming pair (`solo`, `chorus`) leaves room for `duet`, `trio`, `quartet` later — see [Q3 in open-questions](03-open-questions.md#q3--future-small-group-semantics-duet--trio--quartet).

---

## Document inventory

| # | File | Purpose | Status |
|---|---|---|---|
| 00 | [`00-index.md`](00-index.md) | This file — orientation, doc inventory, status snapshot | Current |
| 01 | [`2026.05.12-tts-interaction-mode-solo-chorus.md`](2026.05.12-tts-interaction-mode-solo-chorus.md) | **Canonical revised plan.** Solo/chorus framing, parallel preservation, phased landing | Drafted |
| 02 | [`02-background-synthesis.md`](02-background-synthesis.md) | Distillation of predecessor docs into one read-before-implementation reference | Drafted |
| 03 | [`03-open-questions.md`](03-open-questions.md) | Deferred design questions parked for future resolution | Open (Q4 resolved) |
| 04 | [`04-mode-coupling-audit.md`](04-mode-coupling-audit.md) | Q4 resolution — full audit of mode-coupled behaviors; readiness verdict for Phase 1 | ✅ Resolved |
| 10 | [`10-phase1-ini-plumbing-design.md`](10-phase1-ini-plumbing-design.md) | Phase 1 design — INI key + config helper | Drafted, awaiting implementation |
| 11 | [`11-phase2-bridge-rename-design.md`](11-phase2-bridge-rename-design.md) | Phase 2 design — bridge field rename + mode-aware defaults | Drafted, awaiting implementation |
| 12 | [`12-phase3-server-router-design.md`](12-phase3-server-router-design.md) | Phase 3 design — `speakerphone.py` rename + mode-conditional displacement | Drafted, awaiting implementation |
| 13 | [`13-phase4-mcp-tool-rename-design.md`](13-phase4-mcp-tool-rename-design.md) | Phase 4 design — MCP tool rename + `_notify_impl` mode-conditional | Drafted, awaiting implementation |
| 14 | [`14-phase5-hook-rider-design.md`](14-phase5-hook-rider-design.md) | Phase 5 design — 4-variant rider matrix + helper rename | Drafted, awaiting implementation |
| 15 | [`15-phase6-claude-md-skills-design.md`](15-phase6-claude-md-skills-design.md) | Phase 6 design — CLAUDE.md migration + skill rename/retire | Drafted, awaiting implementation |
| 16 | [`16-phase7-multiplexer-ui-design.md`](16-phase7-multiplexer-ui-design.md) | Phase 7 design — event rename + mode-aware toggle/affordances + 100% c8 | Drafted, awaiting implementation |
| 17 | [`17-phase8-color-glyph-uxs-design.md`](17-phase8-color-glyph-uxs-design.md) | Phase 8 design stub — chorus-mode green-pin/color-pool follow-up | Drafted (deferred) |
| 20 | [`20-test-parameterization-matrix.md`](20-test-parameterization-matrix.md) | Test inventory enumerating every solo/chorus-affecting test | Drafted |
| 90 | [`90-decisions-log.md`](90-decisions-log.md) | Append-only ledger of design decisions as the plan evolves | Open |
| — | [`2026.05.11-per-session-speakerphone-mode.md`](2026.05.11-per-session-speakerphone-mode.md) | **Superseded.** Original 2026-05-11 think-out-loud (hard-cut framing). Preserved as historical record | Historical |

**Naming convention in this subdir**: numeric-prefixed docs (`00`, `02`, `03`, `10`–`17`, `20`, `90`) are subdir-native; date-prefixed docs (`2026.05.11`, `2026.05.12`) predate the subdir and keep their original names for link stability. The May 12 doc occupies the conceptual `01` slot (the canonical plan).

**Execution logs and closure docs** (added once implementation begins, BFE pattern per [[feedback_plans_include_tracking_docs]]):
- `91-phase1-execution-log.md` ... `98-phase8-execution-log.md` — per-phase execution logs
- `92-phase1-closure.md` ... — per-phase closure docs as each phase wraps

---

## Predecessors (read for context)

- [`../2026.04.27-conversation-mode-design.md`](../2026.04.27-conversation-mode-design.md) — original conversation-mode design (single global toggle, monopoly semantics).
- [`../2026.04.30-conv-mode-three-layer-enforcement/`](../2026.04.30-conv-mode-three-layer-enforcement/) — three-layer enforcement refinement.

The `02-background-synthesis.md` doc in this subdir distills these into one read-before-plan reference so the May 12 canonical plan isn't read in a vacuum.

---

## Status snapshot

**Decided** (see [`90-decisions-log.md`](90-decisions-log.md) for full ledger):
- INI key: `tts interaction mode` with values `solo | chorus`.
- Default: `chorus` (the experiment is the work; opt into solo via INI override to invoke today's monopoly fallback). Flipped from `solo` at Phase 1 execution kickoff — see [`90-decisions-log.md`](90-decisions-log.md).
- Framing: parallel preservation (both modes first-class permanent), not hard-cut.
- Naming: rename per-session render-mode field from `conversation_mode_active` to `speakerphone_on` across all surfaces (bridge, MCP tools, HTTP endpoint, WS event, listener action, hook helpers, slash commands, skills).

**Resolved**:
- **Q4 mode-coupling audit** (✅ 2026-05-12) — see [`04-mode-coupling-audit.md`](04-mode-coupling-audit.md). Phase 1 unblocked; one finding folded into Phase 4 scope.

**Pending** (see [`03-open-questions.md`](03-open-questions.md)):
- Chorus-mode green-pin / color-pool treatment (deferred to Phase 8).
- Future small-group semantics (`duet` / `trio` / `quartet`).
- Predecessor-doc integration treatment.
- Stale `~/.claude/plans/` plan file cleanup.
- In-flight skill name reference sweep.

**Implementation readiness**:
- ✅ All Phase 1–8 design docs drafted.
- ✅ Q4 audit complete; no implementation-blocking couplings.
- ✅ Background synthesis + test parameterization matrix drafted.
- ⏸️ **Awaiting Rick's explicit go-ahead** to begin Phase 1 code work. Status remains 💭 thought exercise until that go-ahead arrives.

**Not started**:
- Any implementation work (still in Phase 0).
- Execution logs (`91`–`98`) and closure docs (`92`–) — added once implementation begins per phase.

---

## How to read this subdir

1. **Newcomers**: start here (`00`), then read the May 12 canonical plan (`01`-slot), then skim open questions (`03`).
2. **Anyone implementing**: start with `00`, then read `02-background-synthesis.md` to understand today's system, then read the May 12 plan, then read the relevant per-phase design doc (`10`–`17`) before touching code.
3. **Auditing design evolution**: read the decisions log (`90`) top-to-bottom, then dip into the May 11 historical doc to see where the thinking began.
