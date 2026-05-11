# ask_yes_no "Neither" affordance — Master Index

| Field | Value |
|---|---|
| **Status** | ⏳ Phase 0 in progress |
| **Last-reviewed-at** | _(stamp at end of Phase 0)_ |
| **Session** | 6d544991 (Arnold 🪨, 2026-05-11) |
| **Initiative origin** | TODO.md MCP SELF-INTROSPECTION FOLLOW-UPS (filed 2026-05-07 by session 6825e6af during plan-review pipeline) |
| **Plan source** | `~/.claude/plans/swirling-watching-hinton.md` (approved 2026-05-11 via ExitPlanMode) |
| **Cross-sub-projects touched** | LUPIN parent + CoSA submodule (one file: `notification_utils.py`) |

---

## Documents

| File | Role | Status |
|------|------|--------|
| [00-index.md](00-index.md) | Master nav, Q-decisions table, REUSE table, idempotency marker | ⏳ this |
| [01-design.md](01-design.md) | Full design, 7 Q-decisions ratified, 7 phases, 10 ACs, 4 risks | ⏳ Phase 0 |
| [02-handoff-summary.md](02-handoff-summary.md) | Cross-sub-project handoff for CoSA-context session (commit) | ⏳ Phase 0 |
| [90-execution-log.md](90-execution-log.md) | Phase status table, per-phase scaffolds, REUSE/AC closure evidence | ⏳ Phase 0 |

---

## Q-decisions FROZEN (7)

| # | Decision | Value |
|---|----------|-------|
| Q1 | Button label | **Neither** |
| Q2 | Keyboard shortcut | **None** (mouse/touch only) |
| Q3 | Return value string | `"neither"` (lowercase) |
| Q4 | Schema approach | Extend YES_NO response_value vocabulary (NO new ResponseType) |
| Q5 | Default-on-timeout | Unchanged (yes/no only; never "neither") |
| Q6 | Comment qualifier | Works for all three buttons via existing `[comment: ...]` |
| Q7 | Visual treatment | Neutral color (no green per `feedback_no_green_in_persona_pool`) |

---

## REUSE pre-pass

| Component | Path | Status |
|-----------|------|--------|
| Regex parser | `src/cosa/utils/notification_utils.py:215` `extract_qualifier_comment` | **Extend** — single-char regex change |
| Format helper | `src/cosa/utils/notification_utils.py:244` `format_qualified_response` | **Reuse as-is** (answer-agnostic) |
| MCP tool | `src/lupin_mcp/cosa_voice_mcp.py:887` `ask_yes_no` | **Docstring only** |
| HTML render | `src/fastapi_app/static/js/notifications.js:13782-13808` | **Extend** — add 3rd `<button>` |
| Click handler | `src/fastapi_app/static/js/notifications.js:13910-13916` | **Reuse as-is** — `dataset.response` generic |
| Submit handler | `src/fastapi_app/static/js/notifications.js:16313-16322` | **Reuse as-is** — string flows through |
| Comment qualifier widget | `src/fastapi_app/static/js/notifications.js:13797-13808` | **Reuse as-is** — works for all 3 buttons |
| Unit test class | `src/tests/unit/test_stop_hook.py:34` | **Extend** — 4 new "neither" tests |

---

## Doc conventions status

| Convention | Status |
|------------|--------|
| Phase 0 doc-gate explicit | ✅ Per `feedback_phase0_serialization_prominence` |
| Design doc + execution log paired | ✅ Per `feedback_plans_include_tracking_docs` |
| Cross-sub-project handoff doc | ✅ Per `feedback_cross_project_handoff_doc` |
| Idempotency marker | ⏳ stamped at end of Phase 0 |
| EXECUTOR: AI/HUMAN tags | ✅ all 7 phases tagged in 01-design.md §4 |

---

## Quick links

- [01-design.md §1 Context](01-design.md#1-context)
- [01-design.md §4 Phases](01-design.md#4-phases)
- [01-design.md §5 ACs](01-design.md#5-acceptance-criteria)
- [02-handoff-summary.md — CoSA commit pointer](02-handoff-summary.md)
- [90-execution-log.md — phase status](90-execution-log.md)
