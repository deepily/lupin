# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-03 to 05-06](history/2026-05-03-to-06-history.md).

### 2026.05.11 - Session 6e8a6a03 | CC notifications-card normalization — Phase 0 docs + plan-review (all 3 passes) CLOSED; Phase 1 implementation parked READY TO BEGIN

**Persona**: Rachel 🕊️ (calm & clear female, #7B1FA2)

**Accomplishments**:

- **New R&D milestone serialized** at `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/` (4 docs, 665 lines total, all Phase 0 deliverables landed before any code edits per documentation-first protocol):
  - `00-index.md` (141 LOC) — master nav, 9 Q-N FROZEN decisions table, REUSE-table with verification spot-checks, doc-conventions status, idempotency marker stamped
  - `01-design.md` (256 LOC pre-review, ~290 LOC post-review fixes) — full design: context, Q1-Q9 FROZEN, 8 phases (Phase 0/1/2/3/4/4.5/5/6) with EXECUTOR: AI/HUMAN tags, 19 ACs, risks, out-of-scope, REUSE pre-pass anchor
  - `02-handoff-summary.md` (110 LOC) — cross-sub-project handoff for Lupin mobile + multiplexer R&D teams (TL;DR / what changed / why / per-sub-project action / migration timeline / where to ask + 3-tier contact ladder)
  - `90-execution-log.md` (158 LOC pre-review, ~280 LOC post-review evidence) — phase status table, per-phase scaffolds, REUSE + Pass 1 + Pass 2 closure sections

- **`/plan-review` gate fully CLOSED 2026-05-11** — all 3 passes sequential per Q7, zero parallel dispatch:
  - **REUSE pre-pass**: 8 findings (4 reuse-as-is + 1 extend-existing + 3 genuinely-new). 3 fixes applied: elevated `.cc-retired-banner` CSS orphan cleanup to explicit Phase 1.8 + AC1.5; updated 00-index REUSE table with verbatim file:line spot-checks (notifications.js:2870-2949 research handler shape confirmed; notifications.html:272/319/381/441 sibling status divs confirmed; JobStore.ts:215 agent-agnostic confirmed; FastAPI 0.115.12 stacked-decorator support confirmed); added Risk row for `deprecated=True` repo novelty.
  - **Pass 1 Fitness**: 11 findings (0 Block / 4 Major / 7 Minor / 0 L3). 8/11 applied: M1 (Q8 verdict gate pinned to Phase 5.3) + all 7 Minors (function-name fossil note, literal mobile TODO entry shape, "one release cycle" tightened to v0.1.8+ trigger, WHO-to-contact 3-tier ladder, mobile TODO tag `[LUPIN-CC-SUBMIT-RENAME]` + section, backend coverage scope clarification, dropped `include_in_schema=False` so alias appears in OpenAPI as `deprecated: true`). M2/M3/M4 user-skipped.
  - **Pass 2 Adversarial**: 7 findings + 1 swept pattern offender (0 Block / 5 Major / 2 Minor / 0 L3). All 8 applied: A1 (AC11 visual baseline criteria falsifiable with pytest count + diff allow-list), A2 (AC5 "manual submit" → programmatic), A3 (Two-phase E2E gate `EXECUTOR: HUMAN` tag with same-line justification), A4 (Phase 6.8 `EXECUTOR: AI` + explicit 13-file allow-list), A5 (Phase 6.9 `EXECUTOR: HUMAN` for CoSA commit with nested-repo-boundary justification), a1 (mobile TODO placeholder vs literal clarification), a2 ("manual" metadata in Phase 6.1 + AC13 explained as legacy-item-name), plus swept the same "manual" pattern at Risks row 216 per `feedback_sweep_for_pattern_offenders`.

- **Idempotency marker stamped** in `00-index.md`: `last-reviewed-at: 2026-05-11 (commit c1cec74 — pre-implementation HEAD)`.

- **Zero Layer-3 Design Concerns** across all 3 passes. All 9 Q-N FROZEN decisions stand unchanged.

- **Plan file authored + serialized**: `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (drafted in plan-mode 2026-05-09/10, approved via ExitPlanMode 2026-05-10, serialized into this R&D folder).

- **New auto-memory filed**: `feedback_cross_project_handoff_doc.md` — when a change touches multiple sub-projects (mobile, multiplexer, plugin, CoSA, in-flight R&D), plan must include (1) one concise ~150-line handoff doc and (2) seed TODO entries in each affected sub-project. User-ratified 2026-05-10 during plan-mode walk.

- **Channel switch mid-pass to cosa-voice high-priority action-required UI**: at user request mid-Pass-1, all subsequent gates routed through `mcp__cosa-voice__ask_multiple_choice` with `priority="high"` instead of built-in `AskUserQuestion`, so each plan-review decision surfaces as action-required notification in the UI (user not switching between terminal and browser).

**Files**:
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` (NEW)
- `TODO.md` (modified — new "FIRST THING NEXT SESSION — CC Card Normalization Phase 1" section above Mr. Radio's parallel-session Phase 6b section; Last-updated line refreshed)
- `history.md` (this entry)
- 2 NEW auto-memory files (outside repo): `feedback_cross_project_handoff_doc.md`, MEMORY.md index updated
- 1 NEW plan file (outside repo): `~/.claude/plans/ok-so-far-so-swirling-pearl.md`

**Status**: Phase 1 implementation BLOCKED on next-session user go-ahead. Origin plan + R&D folder are self-contained — fresh-context session can pick up by reading the 4 R&D docs in order.

---

### 2026.05.11 - Session 017dc1cc | Multiplexer Phase 6b Pass 1 Fitness CLOSED — 14/14 ratified via action-required UI

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Pass 1 Fitness ratification walk completed end-to-end** — 14/14 findings ratified across 9 turns (1 Minors batch covering F-8/F-9/F-10/F-11/F-12/F-14 + 8 individual Major walks: F-1, F-2, F-3, F-4, F-5, F-6, F-7, F-13). All firings returned `yes`. Per-decision routing via cosa-voice `ask_yes_no` action-required UI per user directive ("push every decision point into the action-required UI" — much easier to parse than terminal-text gates).

- **All 14 resolutions applied** to `09-phase6b-interactive-widgets-design.md`. Net ~+220 LOC across 8 distinct edit clusters: Boot wiring (mount() is sync addendum, F-12); Inertness-lift contract rewritten as single-write template swap (F-7); new Q-B1 dispatch contract subsection (F-3); Q-B3 state machine extended with `expired_visual` + `responded_default` vertices + Q-B5 ratified text rewritten with local RAF timer + clock-skew handling (F-4); AC table row updates (AC2c MutationObserver assertion, AC2d unit-test contract, AC5/AC5b enumerations, AC7 post-6a baseline, AC10b ceiling 500→700, AC10e command fix); two new AC enumeration sub-tables totalling 34 enumerated cases (AC5 subtotal 21, AC5b subtotal 13); R7 risk row for state-change storm (F-13); Phase 0 prerequisites updated (#3 reword for target API shape, #6 reword for sub-step 4A/4B DOD, NEW #7 for `countdown_expires_at` payload field); new § "Phase 4 sub-step DOD" subsection with explicit DOD tables (8 rows for 4A, 11 rows for 4B) + `JobStore.delete` signature returning `{ restoreState: () => void }` closure.

- **Pass 1 closed subsection** appended to `95-phase6b-review-findings.md` (+~70 LOC): full 9-row ratification record table cross-referencing each finding ID to the resolution applied; doc-state delta summary; convergence re-grep note; updated cycle-state diagram.

- **Pass 2 Adversarial dispatch gated on user go-ahead** per user direction. No auto-progression. The `93-resume-here-phase6b-pass1-ratification.md` file is now historical (left in place as audit trail; can be removed in a future cleanup).

**Files** (parent-Lupin scope only):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (status header + 14 finding resolutions applied)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (NEW "Pass 1 Fitness — closed 2026-05-11" subsection)
- `TODO.md` (FIRST THING IN THE MORNING entry replaced with DONE entry + resolution checklist + historical pointer)
- `history.md` (this entry)
- `.claude-session.md` (registered session 017dc1cc + touched files)

**Phase 6b cycle state**:
- Q-decisions ✅ CLOSED 12/12 (2026-05-07)
- REUSE pre-pass ✅ CLOSED 28 RE + 5 L3 (2026-05-07)
- Pass 1 Fitness ✅ CLOSED 14/14 (2026-05-11)
- Pass 2 Adversarial ⏳ gated on user go-ahead
- Code-execution plan ⏳
- Implementation ⏳

**Commits**:
- session checkpoint pending (this commit)

**Caveats / Notes**:
- `history.md` still at CRITICAL token threshold from 2026-05-07 — archival deferred again to avoid interleaving with active parallel session activity (session `f9608a41` last touched 2026-05-11 working inter-session-commons docs). Will revisit when parallel session pipeline is idle.
- Two task-tool reminders fired during the apply-edits phase; both ignored per harness instructions (tasks #1-#9 already correctly tracked the ratification turns; task #10 in_progress through the entire apply phase).
- Parallel session `f9608a41` (inter-session-commons R&D, separate scope) has its own ongoing work — files cleanly isolated from this session's commit per `.claude-session.md` v2.0 selective staging.

---

### 2026.05.09–11 - Session f9608a41 | NEW INITIATIVE: Inter-Session Commons + User-Broadcast — Phase 0 + 1 (steps 3a+3b) landed

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Multi-day session spanning 2026.05.09 → 2026.05.10 → 2026.05.11.**

**Accomplishments**:

- **NEW initiative launched: Inter-Session Commons + User-Broadcast Channel**. AI-to-AI blackboard for Claude Code sessions + user→all broadcast surface with persona-aware directive parsing (e.g., "all sessions: /plan-session-end; @Mr. Radio: also push; @Maria: skip commit"). Reuses existing per-session voice-persona system + conv-mode listener-injection pattern + WebSocket fanout infra. Doc-set at `src/rnd/v0.1.7/2026.05.09-inter-session-commons/`.

- **Phase 0 CLOSED — 15 Q-decisions ratified** (Q1 free-form + reserved topic registry; Q1b full reserved set: broadcast-acks + presence + system-events; Q2 silent unless priority=high; Q3 defer file-locks to Phase 5; Q4 24h active + indefinite archive; Q5 free-text + `@PersonaName:` syntax; Q6 non-blocking + live aggregate; Q6b both sync + async with naming alignment to project's `_sync`/`_async` convention; Q7 manifest orthogonal; Q8 case-insensitive + punctuation-tolerant matcher + LLM-fallback stub; Q9 follow @all only when persona missing; Q10 confirm dialog; Q11 1/30s rate limit; Q12 JWT-only; Q13 reject empty body; Q14 200 with no-active-sessions status; Q15 markdown from day one). Three architectural principles captured: commons is INTRA-AI; user-as-witness not middleman; sync/async naming consistency.

- **Full plan-review pipeline (REUSE → Pass 1 Fitness → Pass 2 Adversarial) CLOSED**. REUSE: 12 findings (8 reuse-as-is, 3 extend-existing, 1 genuinely-new fcntl with documented justification — `session_bridge.py:1022-1026` no-fcntl is a NUANCED choice for idempotent read-modify-write JSON, NOT a project-wide policy; commons appropriately diverges for append-only non-idempotent posts). Pass 1: 20 fitness findings across all 8 deficiency types ratified + applied. Pass 2: 13 ownership-language findings + 5 design concerns (2 auto-resolved by Cluster A's AI-spawn-subprocess insight) ratified + applied. Plan APPROVED for code-write 2026-05-11.

- **Path correction during walks: storage at `<project_root>/io/commons/`** (was `commons/` at root; user caught it). `io/` already gitignored at `.gitignore:68` — no separate exclusion needed.

- **100% coverage mandate** ratified for commons (commons-only scope per C3; multiplexer-only memory unchanged). Coverage tooling: pytest-cov 7.1.0 + coverage 7.14.0 installed in cosa venv + added to `pyproject.toml` dev deps + `uv.lock` regenerated cleanly (only 2 deps added, 55 lines, torch/flash-attn lock UNTOUCHED) + Docker candidate image `lupin:1.0.0-pytest-cov` built (6ff1643d8796, 31.7GB) but **NOT promoted** per the no-auto-promote-tags feedback memory.

- **Phase 1 implementation steps 3a + 3b CLOSED with 100% coverage**:
  - `src/lupin_mcp/commons_persona_matcher.py` (91 LOC) + 12 unit tests + 100% coverage. Case-insensitive + punctuation/space-tolerant mechanical matcher with stable LLM-fallback hook (Phase 3 wires the actual call).
  - `src/lupin_mcp/commons_store.py` (332 LOC) + 36 unit tests + 100% coverage. CommonsStore class with `post()` / `read()` / `who()`, YAML frontmatter, inline JSON metadata, POSIX `fcntl.flock` for multi-writer safety.
  - **AC10b real-fcntl stress test PASSED**: 5 child processes × 100 posts each = exactly 500 entries in the topic file, zero corruption, all sessions represented. Empirically validates the F6 fcntl ratification.

- **Cross-repo follow-up filed** at `planning-is-prompting/TODO.md`: after Lupin lands the 5 commons MCP tools, audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog (Lupin CLAUDE.md, src/docs/, planning-is-prompting workflow docs, cosa-voice-notifications skill, etc.).

- **Phase 1 step 3 is a natural session boundary.** Steps 4-8 remain: archival daemon (step 4), 5 MCP tool registrations (step 5), INI keys (step 6), 2-session smoke (step 7), AC12+AC14 subprocess verifications (step 8). Resume pointer at `91-resume-here-phase1-step4.md`.

**Files** (parent-Lupin scope only; no CoSA edits per Phase 1 §4):

- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/01-design.md` (NEW + Phase 0 ratifications + §4.1.1 ask threading + §4.2 empty-match)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md` (NEW + REUSE §11 + Pass 1 + Pass 2 applied)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-execution-log.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/91-resume-here-phase1-step4.md` (NEW)
- `src/lupin_mcp/commons_persona_matcher.py` (NEW)
- `src/lupin_mcp/commons_store.py` (NEW)
- `src/tests/unit/commons/__init__.py` (NEW)
- `src/tests/unit/commons/test_commons_persona_matcher.py` (NEW)
- `src/tests/unit/commons/test_commons_store.py` (NEW)
- `pyproject.toml` (pytest-cov added to dev deps)
- `uv.lock` (regenerated)
- (Outside repo, planning-is-prompting) `TODO.md` (cross-repo follow-up filed)

**Commits**: none yet — held for explicit user authorization per the `feedback_never_auto_commit_push` memory.

**Docker**: `lupin:1.0.0-pytest-cov` candidate built; `lupin:1.0.0` working tag UNTOUCHED. User decides when/if to promote.

**Caveats / Notes**:
- Phase 1 plan is the deliverable from the plan-review pipeline; code-write is partial (steps 3a + 3b only).
- No `:8000` Phase 1 tests scheduled (none needed — AC10/AC10b/AC11 are all `:7999` AI-discretionary).
- Voice persona color confirmed as immutable per-allocation by user (parallel to Sam-voice fallback for missing voice data) — design coherence with the per-session-voice-personas immutability invariant.

---

### 2026.05.07 - Session e8228026 | Multiplexer Phase 6a final closure on :8000 + Phase 6b planning launched (Q-decisions + REUSE done; Pass 1 paused)

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Phase 6a fully CLOSED on both `:7999` and `:8000`** — AC11a baseline captured (job `ts-b786315c`, 13:59 EDT, PNG at `io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/`) + AC11b regression GREEN (job `ts-bd34af9b`, 1 passed in 5.6s, 14:48 EDT, `-k` filter honored: 398 deselected / 1 selected). Discovery: visual baselines are gitignored under `io/` (`.gitignore:68`), so the baseline lives host-only and bind-mounts into the test container; no commit needed for the PNG.

- **Two `/api/test-suite/submit` silent-drop traps caught + documented as durable memories**:
  - `test_types="e2e_ui"` → silently dropped to 0/0/0/0 (no HTTP error). Use `"e2e"`. Memory `feedback_test_types_e2e_not_e2e_ui.md`.
  - Pydantic field is `pytest_args` (NOT `args`). v2 silently ignores unknown fields → submit body's `"args"` was dropped → full 23-min sweep ran instead of `-k` filtered. Memory `feedback_test_suite_submit_field_pytest_args.md`. Both `TODO.md` AC11a/AC11b entries fixed at source so the next session doesn't re-hit either trap.

- **Phase 6b planning launched** — design doc `09-phase6b-interactive-widgets-design.md` (NEW, 289 LOC) at canonical R&D path. 12 Q-B decisions across 4 clusters (submit semantics, TTS chrome, delete-button, boot/CSS/scope) ratified via cosa-voice walkthrough. Q-B6 corrected mid-walk: per-notification corner buttons belong in 6b not 6c per slicing manifest line 46.

- **REUSE pre-pass closed** — 28 RE-rows (16 reuse-as-is / 9 extend-existing / 3 genuinely-new) + 5 Layer-3 concerns ratified via 4-batch cadence. **C-4 confirmed empirically**: `JobStore.delete(idHash)` does NOT exist (only `indexById.delete(id)` internal Map call at `JobStore.ts:292`). Phase 6b Phase 4 must split into sub-step 4A (extend JobStore + 100% c8 tests) + 4B (wire delete-button click handler). AC table grew: AC2d (JobStore.delete grep + tsc guard), AC5c (delete-button extension tests ≥6 cases), AC10e (cross-phase count-cascade regression).

- **Pass 1 Fitness dispatched** — clean-context Explore agent, 14 findings (0 Block / 9 Major / 5 Minor / 0 Layer 3). Ratification PAUSED at user break point. F-1 caught a real bug in my own doc work — AC10b said `tts-chrome.css ≤500` but Q-B12 ratified `≤700`. Resume via `93-resume-here-phase6b-pass1-ratification.md` (NEW, 109 LOC).

- **Phase 6b cycle state**: Q-decisions ✅ → REUSE ✅ → Pass 1 ⏸️ paused → Pass 2 ⏳ → code-execution plan ⏳ → implementation ⏳.

**Files** (parent-Lupin scope only):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (NEW, 289 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (NEW, 156 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/93-resume-here-phase6b-pass1-ratification.md` (NEW, 109 LOC)
- `TODO.md` (AC11a/AC11b field-name fixes + 2026.05.08 morning section)
- `history.md` (this entry)
- 2 NEW auto-memory files (outside repo): `feedback_test_types_e2e_not_e2e_ui.md`, `feedback_test_suite_submit_field_pytest_args.md`

**Commits**:
- `243267b` — Phase 6a AC11a/AC11b CLOSED: TODO.md test-suite submit field-name fixes
- `d70be64` — Phase 6b planning checkpoint: Q-decisions + REUSE closed; Pass 1 paused at break point
- session-end commit pending (this entry)

**Caveats / Notes**:
- `history.md` remains at CRITICAL token threshold (~22.4k). Archival deferred per user direction earlier this session because parallel session 6825e6af (María) had uncommitted edits at that time. Carried forward to 2026.05.08 morning section in `TODO.md`.
- Phase 0 prerequisites for Phase 6b implementation (verified at code-execution plan time): `DELETE /api/queue/<bucket>/<id>` exists ✅; `multiSelect` payload, `AudioStore.currentNotificationIdHash`, action-required mount surface, CoSA `multiplexer_config.py` commit, `JobStore.delete(idHash)` — all pending verification.
- Parallel session 6825e6af (María 🌸) committed her own work (`4d2579f`) mid-session; her files cleanly isolated from my commits per parallel-session-safety v2.0.

---

### 2026.05.07 - Session 6825e6af | Bug Fix Mode — Notification 503 cascade reconciliation

**Persona**: María 🌸 (warm, inquisitive female)

**Context**: User opened a bug-fix session and asked to claim "Notification 503 cascade for offline users in expediter flow" (currently In Progress with stale owner 45e6bf84 — that session closed 2026-05-05T23:25). User flagged: "I thought that we had fixed it already." First task is reconciling the bug-queue entry against actual prior fixes before deciding scope.

### Fixes

#### Reconciliation — "thought we fixed it already"

User's recollection was substantially right: session 45e6bf84 on 2026-05-05 (commit `24e4731` + checkpoint `621be65`) completed Phases 0-4a of a real root-cause fix. The May-1 bug-queue framing ("client doesn't set `response_default`, 4 fix options") was disproved on May-5 — quote from `01-design.md`: "The fix is in the test harness, not the expediter or the server." Real root cause was **silent proxy startup failure**; May-5 made `_start_proxy` raising-on-failure + made all 7 callers abort on failure. Phase 4b on `:8000` was prepared but never ran — a NEW bug surfaced ("`pytest --auto-proxy` is a no-op — `pre_run_hook` never fires under pytest discovery") and was filed Queued. The In Progress entry stayed open because the new bug blocked Phase 4b's pytest path.

User chose **Path B**: fix the new pytest bug FIRST, then run Phase 4b through the canonical pytest path. Both bug-queue entries close together on AC11.

#### Phase 5 — pytest fixture wiring (CODE + :7999 VERIFY DONE)

- **R&D doc**: appended Phase 5 section to `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` + `90-execution-log.md`. Documents why module-scoped (not session-scoped — different test files have different `PROXY_PROFILE`) and why we did NOT take the alternative of wiring through pytest entry points.
- **Code (parent repo only — no CoSA edits)**:
  - `src/tests/smoke/conftest.py` — new module-scoped autouse fixture `_auto_proxy_for_module` + registered `--proxy-debug` CLI option. Fixture introspects test module for `EmbeddedProxyMixin` subclass DEFINED in the module (filter `obj.__module__ == module.__name__` to skip imported parents like `InteractiveSmokeTest`), instantiates it, calls `_start_proxy(...)` with env-var creds, and `pytest.fail(..., pytrace=False)` on `RuntimeError` to prevent cascade. Cleanup via `_stop_proxy()` at module teardown.
  - `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — regression test for the fixture; asserts `"auto proxy"` session is registered in `/api/debug/websocket-state` with a non-empty user mapping. Marker class `AutoProxyFixtureProbe(EmbeddedProxyMixin)` drives the fixture (profile=`deep_research`).
- **Class introspection sanity** across all 6 affected test modules picked the right concrete subclass: `ProxyIntegrationTest`/`proxy_integration_test`, `ExpeditorSmokeTest`/`expeditor_smoke`, `SweTeamProxySmokeTest`/`swe_team`, `PresentationLiveSmokeTest`/`presentation_gates`, `ResearchToPresentationLiveSmokeTest`/`research_to_presentation_gates`, `PresentationRenderOnlySmokeTest`/`presentation_gates`.
- **AC9 happy-path on `:7999`**: `pytest src/tests/smoke/test_auto_proxy_fixture.py --auto-proxy -v -s` → **1 passed in 2.19s**. Proxy registered as UUID `50c73ba7-36dd-4eaf-a7e2-63256252c84f` (matches the test-user UUID quoted in May-5 design doc).
- **AC10 sad-path on `:7999`**: same command with `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=wrong-password` → **1 error in 32.33s**, `ERROR at setup of test_fixture_started_proxy`. Test body never executed (cascade prevention contract honored). pytest reported as setup ERROR not assertion FAILED — correct distinction.

#### Phase 3 — `:8000` Phase 4b scheduling (DONE)

User authorized immediate slot. First submission `ts-f04eed7f` failed at startup (exit=4) because `pytest_args = "-k 'expr1 or expr2 or expr3'"` got `.split()` on whitespace — pytest received `'expr1`, `or`, `expr2'`, etc. as positional args and crashed with `ERROR: file or directory not found: or`. Resubmitted as `ts-e6bb533b` using 55 `--ignore=src/tests/smoke/<file>.py` tokens to narrow the smoke run to 4 keepers (`test_proxy_integration`, `test_expeditor_mock_job_smoke`, `test_swe_team_proxy`, `test_auto_proxy_fixture`). `--auto-proxy --cost-cap-usd 5.00` auto-injected via INI key (Cluster B from 2026-04-30 post-mortem) — confirmed in the running pytest argv.

Pre-flight: `preflight-test-container.sh` PASSED (all probes green). Direct container inspection confirmed bind-mount visibility: container saw the new fixture (`grep _auto_proxy_for_module conftest.py = 3 matches`) and the new test file (`test_auto_proxy_fixture.py` with today's mtime). No bounce required. `:8000` pool clean before submit (0 inflight, 0 pending).

#### Phase 4b — :8000 cascade-elimination (DONE — AC11 GREEN)

- **Job**: `ts-e6bb533b::50c73ba7-...`
- **Started**: 2026-05-07T15:23:40 EDT
- **Completed**: 2026-05-07T16:11:10 EDT
- **Duration**: 47:27 (2847.86s)

| Test | Result | Duration | Notes |
|------|--------|----------|-------|
| `test_auto_proxy_fixture::test_fixture_started_proxy` | ✅ PASS | <1s | Fixture regression test green |
| `test_expeditor_mock_job_smoke::test_expeditor_mock_job_smoke` | ✅ PASS | 1620.93s (27 min) | All scenarios green |
| `test_swe_team_proxy::test_swe_team_proxy` | ✅ PASS | 383.92s (6.4 min) | All scenarios green |
| `test_proxy_integration::test_proxy_integration` | ❌ FAIL | ~13 min | 14/15 scenarios pass; **scenario 15 EXP_RTPRES_MISSING failed for an UNRELATED REASON** — voice-routing classifier mis-routes "research something and present it" → `deep_research` instead of `research_to_presentation` |

**AC11 verification — zero `http_error_503`**:

| Source | Count |
|--------|-------|
| Run log `/tmp/smoke-20260507-201109.log` | grep `http_error_503` / `HTTP 503` / `User cancelled` / `503 Service` → **0 hits** |
| `lupin-rest-test` container logs (last 50 min) | grep `503` → 5 false positives, ALL source-port substrings (`127.0.0.1:45030`, `:45032`, etc.); zero actual HTTP 503 responses |
| Proxy subprocess stats (final) | `Notifications Received=90, Responses Sent=19, Script Matcher Used=17, LLM Used=2, Skipped=71, Errors=0` |

**Cascade is eliminated.** Both bug-queue entries close.

**Per-module fixture evidence** captured mid-run:
```
python3 -m pytest src/tests/smoke/ -v --ignore=... --auto-proxy --cost-cap-usd 5.00
└── python3 -m cosa.agents.notification_proxy --profile expeditor_smoke ...
```
The `--profile expeditor_smoke` matches `ExpeditorSmokeTest.PROXY_PROFILE` for that module — proof that `_auto_proxy_for_module` correctly introspects the test class and starts the right proxy per module.

#### Bug-queue updates

- ✅ "Notification 503 cascade for offline users in expediter flow" → **CLOSED** (resolved 2026-05-07 by 6825e6af; annotated In Progress entry with full closure evidence + folded into details)
- ✅ "`pytest --auto-proxy` is a no-op — `pre_run_hook` never fires under pytest discovery" → **CLOSED** (resolved 2026-05-07 by 6825e6af; annotated Queued entry with closure evidence)
- 🆕 **NEW Queued entry filed** (per TEST OWNERSHIP MANDATE): "Voice-routing classifier mis-routes 'research something and present it' → deep_research instead of research_to_presentation" — surfaced during Phase 4b run, NOT a regression of the cascade fix.

### Session Summary

**Outcome**: Two bug-queue entries closed in one session, one new bug filed.

- **Notification 503 cascade for offline users in expediter flow** — RESOLVED. May-5 (45e6bf84) landed Phases 0-4a (test-harness raise-on-failure + 7-caller abort). May-7 (6825e6af) landed Phase 5 (module-scoped pytest fixture closing the pre_run_hook gap). Phase 4b on `:8000` (job `ts-e6bb533b`, 47:27 runtime) verified zero `http_error_503` / 0 proxy errors / 90 notifications received / 19 responses sent.
- **`pytest --auto-proxy` is a no-op** — RESOLVED in same closure. Module-scoped autouse fixture in `src/tests/smoke/conftest.py` introspects test module for the concrete `EmbeddedProxyMixin` subclass (filter `obj.__module__ == module.__name__` to skip imported parents), instantiates it, calls `_start_proxy(...)` with env-var creds, `pytest.fail(..., pytrace=False)` on `RuntimeError`. Cleanup via `_stop_proxy()` at module teardown.
- **Voice-routing classifier mis-route** (NEW) — Queued for future session; pre-existing classifier issue surfaced only because the new pytest-path coverage now exercises Scenario 15 properly.

**Files modified (parent Lupin repo only — no CoSA edits)**:
- `bug-fix-queue.md` — Active Sessions row added; "503 cascade" In Progress entry closed; "pytest --auto-proxy no-op" Queued entry closed; new "voice-routing classifier" Queued entry filed
- `history.md` — this entry
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` — Phase 5 section appended
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` — Phase 5 status + Phase 4b evidence
- `src/tests/smoke/conftest.py` — fixture + `--proxy-debug` option
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — fixture regression test

**Status**: All work complete. Awaiting user `commit` authorization. No commits made automatically.

#### Checkpoint | 2026.05.07 20:15 | 503 cascade fix (Phase 5) + Phase 4b verification + bug-queue closures

**Files** (6 in Lupin parent + manifest):
- `src/tests/smoke/conftest.py` (modified — fixture)
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` (Phase 5 section)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` (Phase 5 + Phase 4b evidence)
- `bug-fix-queue.md` (closures + new Queued entry)
- `history.md` (session entry — this file)
- `.claude-session.md` (manifest section for 6825e6af)

**Commit**: 4d2579f

#### Checkpoint | 2026.05.07 23:00 | Bounded ClaudeCodeJob redesign — plan approved + serialized + REUSE closed + Pass 1 partial (4/11)

**Topic shift mid-session**: After bug-fix work landed at `4d2579f`, user pivoted to a proactive redesign of the BOUNDED `ClaudeCodeJob` to bring it to canonical agentic-job shape. Sequence:

1. **Investigation** — surveyed retired `/api/claude-code/dispatch` cluster (closed 2026-05-05 by `73bee1b`); audited current `src/cosa/agents/claude_code/` (4 of 8 canonical files; missing `config.py`/`state.py`/`orchestrator.py`/`__main__.py`); gold-reference is `src/cosa/agents/deep_research/`.
2. **Plan mode** — drafted at `~/.claude/plans/so-it-looks-like-silly-map.md`; user revised twice (rejected facade-wrap in favor of relocation of `cosa/orchestration/claude_code/` → `cosa/agents/claude_code/`; added cross-agent regression contract after flagging TFE/BFE possible dependency, which Explore agents verified is zero-deps today). Approved via ExitPlanMode.
3. **Serialization** — Phase 0 docs landed at `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/{01-design.md,90-execution-log.md}`.
4. **Plan-review install** — `/plan-install-wizard` (mode=install) added `/plan-review` slash command to `.claude/commands/plan-review.md` with Lupin-specific customization (project=Lupin, prefix=[LUPIN], `:7999`/`:8000` venue notes, CoSA git boundary callout, auto-memory feedback-loop callout).
5. **Convention amendment** (pre-flight to plan-review): created `00-index.md` (master nav + idempotency marker home + Prior art referenced section + Open follow-ups) and `00-working-contract.md` (Layer 2 anchor — test-layer enumeration, user-involvement gate, cannot-execute rule, phase-complete definition). Reformatted `01-design.md` decisions as `Q1`/`Q2`/`Q3 FROZEN 2026-05-07` with Question/✅ Decision/Rationale/Implication structure. Added 42 `EXECUTOR: AI / HUMAN <reason>` tags throughout Phase 6 + Phase 7 + Verification section. All 5 conventions satisfied (Convention 5 false-positive Manual hits skip-logged in `00-index.md`).
6. **REUSE pre-pass (§4)** — single Explore agent grep against `src/cosa/` + `src/fastapi_app/` + `src/tests/`. 18 findings; 4 user decisions via `AskUserQuestion`: F#3 reframe `ClaudeCodeRunResult` as rename-from-`TaskResult`, F#8 INI namespace `claude code bounded job *` (anticipates future `claude code interactive job *`), F#18 `Task`/`TaskType` to `state.py`, applied F#4 + SDK_AVAILABLE re-export + #16 deferral. Convergence ✓.
7. **Pass 1 Fitness (§5)** — single Explore agent. 11 findings + zero TBDs + zero Layer-3 Design Concerns. **STRUCTURAL batch (4/4) closed via single-finding `ask_yes_no` ratification** with conversation-mode voice gates: F1 atomic-rename approach (no shim — user surfaced the overengineering), F4 canonical "all args on `__init__` + parameterless run methods + job-level routing" matching Podcast `do_all_async`/`do_review_only_async`/`do_audio_only_async` pattern (user's qualifier "how does this affect bounded vs interactive dispatch?" surfaced the cleanest answer), F8 `stream_thoughts_to_voice` removed (vestigial copy-paste), F10 baseline timing re-targeted "BEFORE Phase 1" (Phase 2a relocation could leak into siblings).
8. **Pass 1 SUSPENDED at 7 remaining findings** (4 implementation-completeness + 3 operational). Resume with `/plan-review --from=fitness`. Detail in `90-execution-log.md` § "Pass 1 — Fitness — ⏸️ PARTIALLY CLOSED 2026-05-07; SUSPENDED at 4/11 findings applied".
9. **Filed**: TODO entry for `cosa-voice ask_yes_no()` to grow a "Neither" / "Discuss further" button — surfaced because the user wanted to qualify a yes mid-flight ("yes BUT how does this differ from existing patterns?") and the only tool today is comment-text on the chosen answer.

**Files** (this checkpoint, all Lupin parent — no CoSA edits):
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-working-contract.md` (NEW)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/01-design.md` (NEW; serialized + heavily restructured during plan-review amendments + REUSE/Pass-1 fixes)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/90-execution-log.md` (NEW; phase status table + REUSE closure + Pass 1 partial breadcrumbs)
- `.claude/commands/plan-review.md` (NEW; installed via `/plan-install-wizard`)
- `TODO.md` (modified — neither-button feature request appended to Pending section)
- `.claude-session.md` (manifest section — touched-files entries added)
- `history.md` (this file — this checkpoint)

**Commit**: c1cec74

---

