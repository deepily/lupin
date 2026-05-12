# Inter-Session Commons + User-Broadcast Channel — Index

| Field | Value |
|---|---|
| **Initiative** | Inter-Session Commons (AI ↔ AI blackboard) + User-Broadcast Channel (user → all CC sessions, persona-aware) |
| **Doc-set started** | 2026-05-09 |
| **Branch** | `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe` (may rebase to v0.1.8 if commons slips past v0.1.7 cut) |
| **Owner persona** | Tiberius 🌑 (session `f9608a41`) |
| **last-reviewed-at** | 2026-05-12 (Phase 2 CLOSED — see [`92-phase2-closure.md`](92-phase2-closure.md)) |

---

## Quick navigation

| Doc | Status | Purpose |
|---|---|---|
| [`01-design.md`](01-design.md) | ✅ CLOSED 2026-05-09 | Phase 0 design + ratification (15 Q-decisions) + 3 architectural principles |
| [`02-phase1-file-commons-design.md`](02-phase1-file-commons-design.md) | ✅ CLOSED 2026-05-11 — all 14 ACs verified | Phase 1 file-based commons MVP execution plan (14 ACs + AC10b stress, 5 NEW + 4 MODIFIED files) |
| [`92-phase1-closure.md`](92-phase1-closure.md) | 🟢 NEW — Phase 1 post-mortem | What landed, deferred items, Phase 2 unblock summary |
| [`03-phase2-user-broadcast-design.md`](03-phase2-user-broadcast-design.md) | ✅ CLOSED 2026-05-12 — all 14 ACs verified | Phase 2 user→all broadcast surface. REUSE + Pass 1 + Pass 2 all closed: 10 prior-art mappings + 4 plan corrections + 20 fitness findings + 12 threats walked + 11 ACs hardened + sanitization ratified + 2 new threats surfaced and mitigated. Implementation closed 2026-05-12. |
| [`92-phase2-closure.md`](92-phase2-closure.md) | 🟢 NEW — Phase 2 post-mortem | What landed, deferred items (D1 polling→push, LLM-fallback), Phase 3 unblock summary |
| [`90-execution-log.md`](90-execution-log.md) | ✅ All 8 steps CLOSED | Phase 1 execution status; per-step AC closure tracking |
| ~~[`91-resume-here-phase1-step4.md`](91-resume-here-phase1-step4.md)~~ | ⚪ Superseded 2026-05-11 | Step 4 closed; kept for history |
| ~~[`91-resume-here-phase1-step5.md`](91-resume-here-phase1-step5.md)~~ | ⚪ Superseded 2026-05-11 | Step 5 closed; kept for history |
| ~~[`91-resume-here-phase1-step6.md`](91-resume-here-phase1-step6.md)~~ | ⚪ Superseded 2026-05-11 | Step 6 closed; kept for history |
| ~~[`91-resume-here-phase1-step7.md`](91-resume-here-phase1-step7.md)~~ | ⚪ Superseded 2026-05-11 | Step 7 closed; kept for history |
| ~~[`91-resume-here-phase1-step8.md`](91-resume-here-phase1-step8.md)~~ | ⚪ Superseded 2026-05-11 | Step 8 closed; kept for history |

---

## Project overview

**Two related capabilities, one shared transport.**

1. **Session ↔ Session commons** — Claude Code instances post / read from a shared blackboard for cross-session status, coordination, and ask/answer. AI-to-AI primarily; user is a witness, not the middleman.
2. **User → All Sessions broadcast** — single message from notifications UI fans out to every active CC session with persona-aware directive parsing (`@PersonaName:` lines). Concrete near-term use: end-of-session ritual broadcast where Mr. Radio also runs `/plan-backup` + push, Maria skips commit, Tiberius does standard close — all from one user click.

**Out of scope** (per Phase 0 §9): cross-user / cross-installation commons; CC session ↔ non-CC agent commons; persistent commons across project boundaries; Mobile app participation.

---

## Q-decision summary (15 ratified, Phase 0 §13)

| # | Decision (1-line) |
|---|---|
| Q1 | Topic registry: free-form + reserved set |
| Q1b | Reserved set: full (`broadcast-acks` + `presence` + `system-events`) |
| Q2 | TTS fatigue: silent unless `priority=="high"`. Architectural principle: commons is INTRA-AI. |
| Q3 | Coordination primitives (file locks): defer to Phase 5 |
| Q4 | Persistence: 24h active + indefinite archive |
| Q5 | Broadcast directive shape: free-text + `@PersonaName:` syntax (with `@all:` / `@everyone:` aliases) |
| Q6 | Broadcast ack UX: non-blocking + live aggregate via WS |
| Q6b | Ask/answer: both `commons_ask_sync` + `commons_ask_async` (Phase 1) — naming aligned with project sync/async convention |
| Q7 | Manifest overlap: keep orthogonal |
| Q8 | Persona matching: case-insensitive + punctuation/space-tolerant + LLM-fallback stub |
| Q9 | No-persona fallback: follow `@all` directive only |
| Q10 | Confirm dialog: one-step recipient chip-row |
| Q11 | Rate limit: 1 broadcast / 30s / user (INI-configurable) |
| Q12 | Access control: authenticated user only (existing JWT) |
| Q13 | Empty body: HTTP 400 |
| Q14 | Zero recipients: HTTP 200 with `status="no-active-sessions"` |
| Q15 | Markdown rendering: from day one (deviated from default; +½ day Phase 2 effort) |

**Architectural principles emerged**:
1. Commons is INTRA-AI — user-bound comms via existing notification API
2. User-as-witness, not-as-middleman
3. Naming consistency: `_sync` / `_async` suffix matches existing project convention

---

## Phase summary

| Phase | Scope | Status |
|---|---|---|
| **0** | Design + ratification | ✅ CLOSED 2026-05-09 (15 Q-decisions) |
| **1** | File-based commons MVP — 5 MCP tools, store, matcher, archival, tests | ✅ CLOSED 2026-05-11 — all 8 steps + 14 ACs complete; 88 tests / 100% coverage |
| **2** | User → all broadcast — UI + 2 endpoints + persona-aware parse + ack aggregation + markdown rendering (Q15) | ✅ **CLOSED 2026-05-12** — all 13 steps + 14 ACs complete; 224 tests (216 unit/smoke + 8 Playwright); 100% coverage gate held across 8 commons modules (622 stmts, 170 branches) |
| **3** | WS push for commons + LLM-fallback wiring + ask_async injection (D1 deviation closure) | ⏳ Future |
| **4** | Postgres-backed commons + Multiplexer Commons tab | ⏳ Future (multiplexer Phase 6c prerequisite) |

---

## Prior art referenced (from REUSE pre-pass, 2026-05-10)

This is the persistent record of REUSE findings that survives past the review and is consulted at code-write time.

| # | Plan component | Verdict | Prior art (file:line) |
|---|---|---|---|
| F1 | `commons_store.py` | extend-existing | `cosa/training/peft_trainer.py:250-330`; `cosa/agents/deep_research_to_podcast/agent.py:save_report_with_frontmatter`; `cosa/agents/swe_team/state_files.py` |
| F2 | `commons_persona_matcher.py` | extend-existing | `cosa/rest/voice_persona_helpers.py:52-94`; `cosa/agents/test_fix_expediter/cluster.py`; `cosa/agents/notification_proxy/verification.py` |
| F3 | `commons_archival.py` | reuse-as-is | `cosa/rest/running_fifo_queue.py:95-107` `_ghost_job_sweep_loop` |
| F4 | 5 MCP tools registered on cosa_voice_mcp | reuse-as-is | `lupin_mcp/cosa_voice_mcp.py:620-1050`; naming via `notify_user_sync`/`async` precedent |
| F5 | Reserved-topic frontmatter | reuse-as-is | `cosa/training/peft_trainer.py:269-285`; `lupin_cli/notifications/notification_models.py` |
| F6 | `fcntl.flock()` for append safety | genuinely-new (justified) | First fcntl use; cross-ref `lupin_cli/claude_code/hooks/lib/session_bridge.py:1022-1026` for divergence rationale |
| F7 | Bridge-file presence enumeration | reuse-as-is | `lupin_cli/claude_code/hooks/lib/session_bridge.py:1156-1213` `find_active_voice_persona_sessions`; `:653-732` `find_active_conversation_sessions` |
| F8 | Test fixtures + 2-session smoke | reuse-as-is | `tests/unit/test_proxy_decision_embeddings.py` + 10+ others (`tempfile.TemporaryDirectory`); `subprocess.Popen` patterns |
| F9 | INI keys + splainer | reuse-as-is | `conf/lupin-app.ini:6-100` + `lupin-app-splainer.ini` (200+ keys precedent) |
| F10 | Q/A threading via `metadata.in_reply_to` | extend-existing | `cosa/rest/notification_fifo_queue.py:50-51` UUID correlation |
| F11 | UUID v4 generation | reuse-as-is | `cosa/rest/notification_fifo_queue.py:50` `str(uuid.uuid4())`; `uuid.uuid4().hex[:8]` per project short-form |
| F12 | `<system-reminder>` injection (Phase 3 target) | reuse-as-is | `cosa/rest/routers/conversation_mode.py:195-278`; `lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` |

---

## Open follow-ups

- **Cross-repo MCP tool catalog audit (filed at PIP TODO)** — After Lupin lands the 5 commons MCP tools, audit + update consumer-facing documentation in EVERY repo that references the cosa-voice MCP tool catalog. Filed at `<planning-is-prompting>/TODO.md` (Pending section, top entry, 2026-05-10).
- **F6 fcntl divergence note** — Apply at code-write to plan §9 risk table: explicit citation of `session_bridge.py:1022-1026` explaining why commons appropriately diverges from session_bridge's no-fcntl choice (different access pattern: append-only non-idempotent vs read-modify-write idempotent).
- **F2 reverse-direction caveat** — At code-write, verify `voice_persona_helpers.display_name_for` is structurally usable for the matcher's reverse direction (input string → canonical persona). May need adapter.
- **F10 ask_async edge cases** — At code-write, decide: should ask_sync match by sender-session too? Should ask_async collect multiple replies or first-only?
- **Q8-Q15 walked but not all `ask_multiple_choice`-ratified individually** — Q8 picked up an LLM-fallback stub addition during walk; Q15 deviated to markdown-from-day-one. Both notable in Phase 0 §13 deviations subsection.

---

## Skip-with-reason log

(empty)

---

## Idempotency marker

`last-reviewed-at: 2026-05-11 (Pass 2 Adversarial closed — 13 findings + 5 design concerns ratified, all fixes applied; **plan APPROVED for code-write**)`

**Plan-review pipeline fully closed.** Phase 1 implementation may begin per §5 of `02-phase1-file-commons-design.md`. No further plan-review gates required for this milestone.
