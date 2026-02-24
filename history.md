# Lupin Project History

### 2026.02.24 - Session 262 | Preference Learning — Phases 0-1 Implementation + Phases 2-3 Plans

#### Checkpoint 3 | 2026.02.24 18:00 | Write Phase 2 + Phase 3 implementation plan documents

**Accomplishments**:
- Wrote Phase 2 implementation plan: BLR + Thompson Sampling (767 lines)
  - Component A upgrade: BLR replacing Beta-Bernoulli with 4-feature Laplace approximation
  - Component D: Thompson Sampling gate with probabilistic Beta posterior sampling
  - Component E (optional): GP/BALD active query selection for informative deferral
  - 5 new config keys, 6 implementation steps, full verification plan
- Wrote Phase 3 implementation plan: Conformal Guarantees + optional ICRL (795 lines)
  - Conformal prediction wrapper (~50-80 lines) with MAPIE library
  - Optional ICRL prompt augmentation for ambiguous CBR cases
  - 3 new config keys, 7 implementation steps, full verification plan
- Updated R&D README with links to both new plan documents
- All file paths and class names verified against Phase 0+1 implementation (commit `bcd5e4e`)

**Files Created (Lupin — 2 files)**:
- `src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.24-phase-2-blr-thompson-sampling-plan.md`
- `src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.24-phase-3-conformal-icrl-plan.md`

**Files Modified (Lupin — 1 file)**:
- `src/rnd/README.md` — Added links to Phase 2 + Phase 3 plan documents

---

#### Checkpoint 2 | 2026.02.24 16:30 | Implement embedding infrastructure + CBR + Beta-Bernoulli trust

**Accomplishments**:
- Step 0: Renamed 11 config keys from `trust proxy` to `swe team trust proxy` prefix (4 files)
- Step 1: Added 12 new INI keys for Phase 0 (embedding/vector search) and Phase 1 (Beta-Bernoulli + CBR)
- Step 2: Created `ProxyDecisionEmbeddings` LanceDB store — 768-dim vector index for proxy decisions
- Step 3: Wired embeddings into `DecisionResponder` — best-effort LanceDB writes after PostgreSQL persist
- Step 4: Phase 0 tests — 10 unit tests (round-trip, similarity ordering, filtering, error resilience)
- Step 5: Added Beta-Bernoulli trust model to `TrustTracker` — dual-model dispatch (count vs beta), 95% credible interval lower bound, min samples gates
- Step 6: Created `CBRDecisionStore` — retrieve + majority vote + confidence scoring
- Step 7: Wired CBR into `EngineeringStrategy` in shadow mode — predict but don't override heuristic
- Phase 1 tests: 14 Beta-Bernoulli tests + 8 CBR tests
- Full regression: 1592 unit tests pass, 0 failures

**Files Created (CoSA — 2 files)**:
- `src/cosa/agents/decision_proxy/proxy_decision_embeddings.py` — LanceDB embedding store
- `src/cosa/agents/decision_proxy/cbr_decision_store.py` — CBR engine

**Files Modified (CoSA — 4 files)**:
- `src/cosa/agents/decision_proxy/config.py` — renamed keys + 12 new defaults + factory entries
- `src/cosa/agents/decision_proxy/responder.py` — embedding_provider, lazy store init, _persist_embedding()
- `src/cosa/agents/decision_proxy/trust_tracker.py` — Beta-Bernoulli _level_beta(), dual-model dispatch
- `src/cosa/agents/swe_team/proxy/engineering_strategy.py` — CBR shadow mode in decide() + evaluate()

**Files Modified (Lupin — 5 files)**:
- `src/conf/lupin-app.ini` — renamed 11 keys + added 12 new keys
- `src/conf/lupin-app-splainer.ini` — renamed 11 keys + added 12 new explanations
- `src/tests/unit/test_swe_team_config.py` — updated expected keys (15→27)
- `src/tests/unit/test_trust_tracker.py` — updated to_dict keys for trust_model field

**Files Created (Lupin — 3 test files)**:
- `src/tests/unit/test_proxy_decision_embeddings.py` — 10 Phase 0 tests
- `src/tests/unit/test_trust_tracker_beta.py` — 14 Beta-Bernoulli tests
- `src/tests/unit/test_cbr_decision_store.py` — 8 CBR tests

**Commit**: aa0bd3b

**Reminder**: CoSA changes (6 files) must be committed separately in CoSA context.

---

### 2026.02.24 - Session 261 | Jettison Gist Embeddings — Dead Code Removal

#### Dead Code Removal | 2026-02-24 | 5-phase implementation, 1538 unit tests pass

**Accomplishments**:
- Removed gist embedding generation from per-query path (`todo_fifo_queue.py`) — saves ~1 embedding API call per query
- Removed gist embedding generation from per-snapshot path (`solution_snapshot.py`) — saves ~2 embedding calls per snapshot creation (~29% of embedding budget)
- Removed `get_snapshots_by_solution_gist_similarity()` (~120 lines) from `lancedb_solution_manager.py`
- Removed 2 dead methods from `solution_snapshot.py`: `set_solution_summary_gist()`, `get_question_gist_similarity()`
- Removed gist embedding comparison code from deprecated `solution_snapshot_mgr.py`
- Cleaned admin similarity endpoint: removed `gist_threshold` param, gist search block, gist fields from response model
- Removed gist similarity column from admin snapshots UI (HTML + JS)
- Updated 2 test fixtures to use empty list `[]` instead of dummy gist embeddings
- Preserved: gist text fields, Level 3 exact matching, schema columns (empty to avoid LanceDB migration)

**Files Modified (CoSA — 4 files)**:
- `src/cosa/rest/todo_fifo_queue.py` — removed per-query gist embedding generation + 5 dict entries
- `src/cosa/memory/solution_snapshot.py` — stopped generating gist embeddings, removed 2 dead methods
- `src/cosa/memory/lancedb_solution_manager.py` — removed `get_snapshots_by_solution_gist_similarity()` (~120 lines)
- `src/cosa/memory/solution_snapshot_mgr.py` — removed gist embedding comparison in deprecated class

**Files Modified (Lupin — 4 files)**:
- `src/cosa/rest/routers/admin.py` — removed gist from similarity endpoint + response model
- `src/fastapi_app/static/html/admin/snapshots.html` — removed gist similarity column
- `src/fastapi_app/static/html/admin/js/admin-snapshots.js` — removed gist tab rendering + switch case
- `src/tests/smoke/test_answer_feedback_smoke.py` — gist embedding fixture → `[]`
- `src/tests/unit/test_answer_is_correct.py` — gist embedding fixtures → `[]`

**Reminder**: CoSA changes (4 files) must be committed separately in CoSA context.

---

### 2026.02.24 - Session 260 | Voice Module Refactoring — 5-Phase Deduplication

#### Refactoring | 2026-02-24 | Implementation complete, 1538 unit tests pass

**Accomplishments**:
- Implemented 5-phase voice/notification module refactoring to eliminate ~1,548 lines of copy-paste duplication across 16 files
- Phase 1: Created `sender_id.py` (shared project detection + sender_id construction) and `feedback_analysis.py` (shared approval/rejection signals), replacing 5 and 3 copies respectively
- Phase 2: Created `AgentNotificationDispatcher` class encapsulating shared async notify/confirm/feedback/choices pattern, reducing 4 cosa_interface files from ~1,600 to ~625 lines total
- Phase 3: Removed `inspect.signature()` hacks from core voice_io.py, reduced DR/PG/SWE voice_io wrappers to thin re-export modules (~100 lines each, down from 270-452)
- Phase 4: Created shared `sync_notify.py` helper for proxy agents, reduced 2 proxy voice_io files
- Phase 5: Updated MCP server to use shared `detect_project()` and `build_sender_id()`, moved `normalize_abstract()` to shared `notification_utils.py`
- Fixed 4 failing unit tests: updated mock targets from old internal paths to dispatcher-level mocks, added missing `job_id`/`queue_name`/`progress_group_id` params to PG cosa_interface
- Final result: 1538 passed, 0 failed (up from 1534/4 pre-fix)

**Files Created (CoSA)**:
- `src/cosa/agents/utils/sender_id.py` — shared project detection + sender_id builder
- `src/cosa/agents/utils/feedback_analysis.py` — shared approval/rejection analysis
- `src/cosa/agents/utils/agent_notification_dispatcher.py` — shared async notification dispatcher class
- `src/cosa/agents/utils/sync_notify.py` — shared sync REST notify helper for proxy agents

**Files Modified (CoSA — 12 files, +328/-1,876 lines)**:
- `src/cosa/agents/deep_research/cosa_interface.py` — dispatcher delegation
- `src/cosa/agents/podcast_generator/cosa_interface.py` — dispatcher delegation + added missing params
- `src/cosa/agents/swe_team/cosa_interface.py` — dispatcher delegation (role-aware)
- `src/cosa/agents/claude_code/cosa_interface.py` — dispatcher delegation
- `src/cosa/agents/deep_research/voice_io.py` — thin re-export wrapper
- `src/cosa/agents/podcast_generator/voice_io.py` — thin re-export wrapper
- `src/cosa/agents/swe_team/voice_io.py` — thin re-export wrapper
- `src/cosa/agents/decision_proxy/voice_io.py` — shared sync_notify
- `src/cosa/agents/notification_proxy/voice_io.py` — shared sync_notify
- `src/cosa/agents/utils/voice_io.py` — removed inspect.signature() hacks
- `src/cosa/agents/utils/__init__.py` — new module imports
- `src/cosa/utils/notification_utils.py` — added normalize_abstract()

**Files Modified (Lupin — 2 files)**:
- `src/lupin_mcp/cosa_voice_mcp.py` — delegated to shared sender_id + normalize_abstract
- `src/tests/unit/test_progress_group_passthrough.py` — updated 4 mock targets for dispatcher architecture

**Reminder**: CoSA changes (16 files) must be committed separately in CoSA context.

---

### 2026.02.24 - Session 259 | Decision Proxy Preference Learning — Take III Synthesis

#### Checkpoint | 2026.02.24 13:00 | Take III synthesis updates: Build vs Import, key rename, embedding fix

**Accomplishments**:
- Added Section 4.7 (Build vs Import Analysis): 12 libraries evaluated, ~750-900 lines custom code, 0-1 new packages
- Renamed all `trust proxy` INI keys to `swe team trust proxy` (21 occurrences) — future-proofs for non-SWE proxy domains
- Removed embedding model/dimension config keys (existing `EmbeddingProvider` at 768-dim handles this), updated key count from ~21 to ~19
- Updated Phase 0 work items with effort reduction note (embedding infrastructure already production-ready)
- Updated TODO.md with Take III synthesis link

**Files**: `2026.02.24-decision-proxy-preference-learning-analysis-take-III-synthesis.md`, TODO.md
**Commit**: 39f8ed7

#### R&D Synthesis | 2026-02-24 | Research document, no implementation

**Accomplishments**:
- Created unified Take III synthesis document merging Take I (codebase-grounded gap analysis, 4 upgrade paths, exact file paths) and Take II (algorithm-focused research, 3 contenders, 18 citations, cold-start phases)
- Key synthesis decisions: CBR replaces ICRL as primary preference backbone (works from day zero), GP/BALD added for active learning (absent from Take I), observation-count phases replace dependency-only phases, Beta-Bernoulli and BLR made sequential (not competing)
- Produced 10-section document: audit, foundations, gap analysis, 6-component algorithm selection, rejected techniques, 4-phase cold-start deployment, file inventory, 21 config keys, 32 consolidated references, 6 recommendations
- Reframed deferral as information-gathering mechanism (Take II's key conceptual insight)

**Files Created**:
- `src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.24-decision-proxy-preference-learning-analysis-take-III-synthesis.md`

**Files Modified**:
- `src/rnd/README.md` (new entry for Take III synthesis + Take II entry added)
- `history.md` (this entry)

---

### 2026.02.23 - Session 258 | Decision Proxy Preference Learning — R&D Analysis

#### R&D Analysis | 2026-02-23 | Research document, no implementation

**Accomplishments**:
- Created comprehensive R&D analysis document auditing the decision proxy's learning mechanism
- Traced 7-stage feedback loop end-to-end with exact file paths and line numbers across 8 source files
- Identified core gap: system learns *whether to act* (trust level) but not *which answers users prefer* (preference learning)
- Documented 4 high-priority upgrade paths: Bayesian Beta-Bernoulli trust (~1 day), LanceDB embedding-based decision recall (~2 days), In-Context RL prompt augmentation (~2-3 days), Thompson Sampling for exploration-exploitation gating (~3-5 days)
- Evaluated and rejected 4 techniques (RLHF, DPO, IDA, CAI) with rationale — all require fine-tuning, incompatible with API-based LLMs
- Designed phased roadmap with Mermaid diagram: A+B parallel → C → D, critical path ~4-5 days

**Files Created**:
- `src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.23-decision-proxy-preference-learning-analysis-take-I.md`

**Files Modified**:
- `src/rnd/README.md` (new entry for analysis document)
- `history.md` (this entry)

---

### 2026.02.23 - Session 257 | INI Config Key Naming Convention — Design Document

#### Design Document | 2026-02-23 | Planning only, no implementation

**Accomplishments**:
- Created comprehensive design document for standardizing ~98 underscore-separated INI config keys to space-separated format
- Analyzed current state: ~195 total keys, 44% underscore / 56% space, ~80 files affected (18 Lupin + 62 CoSA)
- Inventoried all 98 underscore keys grouped by category with proposed space-separated names
- Designed collision-safe replacement strategy using longest-match-first ordering
- Specified ConfigurationManager backward-compat shim with deprecation warnings → assertion mode lifecycle
- Outlined 6-phase migration plan: shim → INI rename → Lupin code → CoSA code → cleanup → regression (~2 weeks)
- Updated TODO.md with v0.1.6 entry and src/rnd/README.md with design doc entry

**Files Created**:
- `src/rnd/2026.02.23-ini-config-key-naming-convention.md` (design document)

**Files Modified**:
- `TODO.md` (new v0.1.6 entry for config key migration)
- `src/rnd/README.md` (new entry for design document)
- `history.md` (this entry)

---

### 2026.02.23 - Session 256 | Rename frontend-architecture.md

- Renamed `src/docs/frontend-architecture.md` → `src/docs/lupin-mpa-frontend-architecture.md`
- Updated 2 references in history.md
- **Commit**: f8d0e73

---

### 2026.02.23 - Session 255 | Bug Fix: Add Delete Functionality to Proxy Ratification Page

#### Fix 1: Add delete functionality to proxy ratification page
- **Source**: ad-hoc (feature gap — no way to delete unwanted pending decisions)
- **Files (CoSA)**: `proxy_decision_repository.py` (new `delete_pending()` method), `decision_proxy.py` (new `DELETE /api/proxy/decision/{id}` endpoint)
- **Files (Lupin)**: `proxy-ratify.html` (Delete Selected button, generic confirm modal), `proxy-ratify.js` (deleteDecision, quickDelete, bulkDelete, showConfirmModal, per-row delete button), `proxy-ratify.css` (.btn-delete-sm styles), `test_proxy_decision_repository.py` (4 new TestDeletePending tests)
- **Safety**: Only pending decisions deletable (backend guard), no trust state impact, confirmation required for all deletes
- **Test**: Unit 1538 PASS (1534 + 4 new), 0 failures
- **Commit**: 33b4122

#### Fix 2: Auto-focus confirm button in delete modal for keyboard-driven workflow
- **Source**: ad-hoc (UX — enable rapid trash-icon-click + Space-to-confirm workflow)
- **Files**: `proxy-ratify.js` (added `confirmBtn.focus()` after modal display)
- **Test**: Not required (1-line UX tweak, no logic change)
- **Commit**: debb307

---

### 2026.02.23 - Session 254 | src/rnd/ Directory Rename — Date Prefix Standardization

#### Checkpoint | 2026-02-23 | 9 directory operations, ~25 file reference updates, 0 regressions

**Accomplishments**:
- Consolidated `src/rnd/archive/` into `src/rnd/archived/` (moved `2025.09.28-perfect-remediation/` subdirectory, removed empty archive/)
- Renamed 7 directories in `src/rnd/` to add project-standard `YYYY.MM.DD-` date prefixes:
  - `deep-research-queue/` -> `2026.01.18-deep-research-queue/`
  - `headless-cc-for-dataframe-crud/` -> `2026.02.04-headless-cc-for-dataframe-crud/`
  - `job-state-transition/` -> `2026.01.28-job-state-transition/`
  - `jwt-oauth/` -> `2025.09.29-jwt-oauth/`
  - `pcm-streaming-demo/` -> `2026.01.07-pcm-streaming-demo/`
  - `prompts/` -> `2025.09.27-prompts/`
  - `sse-notifications/` -> `2025.10.15-sse-notifications/`
- Updated references across ~25 files: README.md, CLAUDE.md, TODO.md, notification-api.md, test READMEs, slash commands, history archives, internal self-references
- Verification: grep for all 8 old names returns 0 operational hits; 1534/1534 unit tests pass

**Files Modified** (reference updates):
- `CLAUDE.md`, `TODO.md`, `src/rnd/README.md`
- `src/docs/notification-api.md`, `src/tests/README.md`, `src/tests/integration/README.md`
- `.claude/commands/design-planning-docs.md`, `.claude/commands/history-management.md`, `.claude/commands/p-is-p-02-documentation.md`
- `src/scripts/create_notifications_table.py`, `src/tests/integration/test_notifications_integration.py`
- `src/rnd/2025.09.27-three-level-question-representation-architecture.md`, `src/rnd/2025.09.28-perfect-baseline-smoke-test-report.md`
- `src/rnd/2025.10.16-jwt-token-proactive-refresh.md`, `src/rnd/2025.11.08-phase-2.4-async-refactoring.md`
- Internal self-references in renamed directories (implementation-tracker, layer-2, 02-architecture, 03-decisions, 05-phase2-design-decisions, README, design-planning-docs)
- History archives: `history.md`, `history/2025-09-03-to-23-history.md`, `history/2025-10-16-to-30-history.md`, `history/2026-01-13-to-19-history.md`, `history/2026-01-19-to-02-02-history.md`, `history/2026-02-03-to-10-history.md`

---

### 2026.02.23 - Session 252 | Playwright E2E Testing — Planning Documents

#### Checkpoint | 2026-02-23 | 7 new files (5 planning docs, 1 serialized plan, 1 README update)

**Accomplishments**:
- Created comprehensive planning documents for Playwright E2E browser testing (deferred to v0.1.6)
- Inventoried 189 interactive elements across 12 UI pages + nav component for data-testid rollout
- Designed 28 test journey specs covering auth, admin, notifications, WebSocket, and visual regression
- Documented 9 architecture decisions (test runner, auth fixtures, naming conventions, isolation, etc.)

**Planning Documents Created** (`src/rnd/2026.02.23-automating-ui-testing/`):
- `00-index.md` — Navigation hub with test pyramid and quick-start
- `01-implementation-plan.md` — 8-phase tracking with ~78 checkboxed tasks and Gantt chart
- `02-architecture-decisions.md` — 9 ADRs with rationale and code examples
- `03-data-testid-inventory.md` — 189 elements mapped to proposed data-testid attributes
- `04-test-journey-specs.md` — 28 journeys, ~140-170 estimated tests, Mermaid flow diagrams

**Other Files**:
- `src/rnd/2026.02.23-playwright-e2e-testing-plan.md` — Serialized plan (summary + links)
- `src/rnd/README.md` — Added entry for new planning docs
- `TODO.md` — Marked research complete, added implementation item with link to planning docs

---

### 2026.02.23 - Session 253 | Profile Page Button Relocation

#### Fix 1: Move Change Password to header, remove redundant Go to Notifications
- **Source**: ad-hoc (UX improvement)
- **Files**: `src/fastapi_app/static/html/auth/profile.html`, `src/fastapi_app/static/html/auth/css/auth.css`
- **Changes**: Moved "Change Password" button into profile header (left of Logout) inside new `.profile-header-actions` div; removed bottom `.button-group` with redundant "Change Password" and "Go to Notifications" (already in top nav); added `.profile-header-actions` CSS rule
- **Test**: Unit 1534 PASS, Nav link 29 PASS
- **Commit**: dd62985

#### Checkpoint 2: Alembic migration — proxy_decisions + trust_states tables
- **Source**: Phase 6 testing blocker — admin proxy pages returning 500 (missing tables)
- **File created**: `src/migrations/versions/c7d8e9f0a1b2_add_proxy_decision_tables.py`
- **Changes**: Alembic migration creating `proxy_decisions` table (11 columns, 6 indexes) and `trust_states` table (6 columns, 3 indexes); migration ran successfully via `alembic upgrade head`
- **Test**: Unit 1534 PASS

---

### 2026.02.23 - Session 252 | Frontend Architecture Docs + UI Smoke Tests

#### Checkpoint | 2026-02-23 | 4 files (1 doc, 2 test files, 1 updated), 44 offline UI tests pass

**Accomplishments**:
- Created comprehensive frontend architecture reference doc (`src/docs/lupin-mpa-frontend-architecture.md`)
- Created 44 offline UI smoke tests for proxy ratification and trust dashboard pages
- Created 15 live integration tests for proxy UI page content verification
- Updated Phase 6 testing validation doc from "0 tests" to "+59 UI tests"

**Frontend Architecture Doc** covers:
- Directory structure, URL routing (12 `/app/*` routes via `pages.py`)
- 4-layer CSS cascade: `lupin-base.css` → domain → page → `lupin-nav.css`
- `auth.js` (16 functions) with token flow sequence diagram
- `lupin-nav.js` IIFE architecture with data-driven NAV_ITEMS
- Page lifecycle, common UI patterns, "Adding a New Page" checklist

**Offline UI Smoke Tests** (`test_proxy_ui_offline_smoke.py` — 44 tests):
- Tier A: HTML structure — CSS cascade, scripts, breadcrumbs, IDs, filters, table headers, modals (24 tests)
- Tier B: JS analysis — requireAuth, API endpoints, function declarations, XSS protection (13 tests)
- Tier C: CSS classes — badges, summary cards, mode bar, trust cards (7 tests)

**Live Integration Tests** (`test_proxy_ui_content.py` — 15 tests):
- Page titles, CSS/JS inclusion, admin headers, asset accessibility (requires server on 7999)

**Files Created**:
- `src/docs/lupin-mpa-frontend-architecture.md` — Comprehensive frontend reference
- `src/tests/smoke/test_proxy_ui_offline_smoke.py` — 44 offline tests (Tiers A+B+C)
- `src/tests/integration/test_proxy_ui_content.py` — 15 live tests (Tier D)

**Files Modified**:
- `src/rnd/.../06-testing-validation.md` — Phase 6 backfill: +59 UI tests

---

### 2026.02.23 - Session 251 | SWE Team UI Bug Fixes + Dry-Run Mock Proxy Decisions

#### Checkpoint | 2026-02-23 | 4 files modified (3 Lupin JS, 1 CoSA Python), 1534 unit tests pass

**Accomplishments**:
- Fixed 5 bugs in proxy admin pages discovered during first hands-on SWE Team UI testing
- Added mock proxy decision generation to dry-run execution path for UI testing
- All changes verified with 1534 unit tests passing, 0 failures

**Bug Fixes (Part 1)**:
- **Bug 1.1-1.2**: Added missing `/api` prefix to 7 API calls across `proxy-ratify.js` (2) and `proxy-dashboard.js` (5) — all calls were 404ing
- **Bug 1.3**: Fixed auth token key from `localStorage.getItem("auth_token")` to `getAccessToken()` in WebSocket auth
- **Bug 1.4**: Fixed invalid WebSocket session ID fallback (was `"proxy-ratify-" + Date.now()`, now `"proxy ratify"` adjective-noun format)
- **Bug 1.5**: Fixed ratification link URL from `/app/proxy-ratify` to `/app/admin/proxy-ratify` in notification proxy summary

**Dry-Run Mock Proxy Decisions (Part 2)**:
- Added 3 mock `ProxyDecision` records at end of `_execute_dry_run()` using `ProxyDecisionRepository.log_decision()`
- Categories: testing (L2, approved), deployment (L1, requires_review), destructive (L1, requires_review)
- All records: `action="suggest"`, `requires_ratification=True`, `metadata_json={dry_run: True}`
- Non-fatal try/except wrapper — dry-run completes even if DB unavailable

**Files Modified (Lupin)**:
- `src/fastapi_app/static/html/auth/admin/js/proxy-ratify.js` — `/api` prefix (2), `getAccessToken()`, session ID fix
- `src/fastapi_app/static/html/auth/admin/js/proxy-dashboard.js` — `/api` prefix (5)
- `src/fastapi_app/static/js/notifications.js` — ratify link URL fix

**Files Modified (CoSA — separate repo)**:
- `src/cosa/agents/swe_team/job.py` — `import uuid`, mock proxy decisions in `_execute_dry_run()`

---

### 2026.02.22 - Session 250 | CoSA Submodule Commit — Sessions 246-248

#### Checkpoint | 2026-02-22 | 9 CoSA files (1 new, 8 modified, +455/-17 lines)

**Accomplishments**:
- Committed accumulated CoSA changes from Lupin Sessions 246-248 to CoSA repository
- **Phase 7**: Proxy summary notifications, batch lifecycle (`acknowledge`/`batch-id` endpoints), circuit breaker alert callback
- **Phase 8**: Trust mode hot-reload (PUT/GET `/api/proxy/mode`), per-job trust_mode override, `_orchestrator` reference for runtime updates
- **Bug fixes**: Echo persistence to DB, abstract in interactions API, simplified echo message
- **Navigation**: `pages.py` clean `/app/*` URL router (12 routes)

**CoSA files committed** (separate repo):
- `agents/swe_team/job.py` — trust_mode override, _orchestrator ref
- `agents/swe_team/orchestrator.py` — proxy notifications, circuit breaker callback
- `cli/notification_models.py` — relaxed progress_group_id regex
- `rest/agentic_job_factory.py` — trust_mode factory wiring
- `rest/postgres_models.py` — widened progress_group_id column
- `rest/routers/decision_proxy.py` — batch endpoints + Phase 8 mode hot-reload
- `rest/routers/queues.py` — echo persistence, abstract field
- `rest/routers/swe_team.py` — trust_mode on submit request
- `rest/routers/pages.py` (NEW) — clean URL router

---

### 2026.02.21 - Session 249 | Unified Page Styling — Shared CSS Base + Purple Removal

#### Checkpoint | 2026-02-21 | 1 new file, 18 modified — lupin-base.css, de-purpled admin pages, 1518 unit tests pass

**Accomplishments**:
- Created `lupin-base.css` shared CSS foundation: reset, body defaults (`#f8f9fa`), blue buttons (`#3b82f6`), messages, spinner, utilities (8px scale)
- Scoped `auth.css` body gradient behind `body.auth-page` class — stops purple from leaking to app pages
- Removed duplicated CSS (buttons, messages, spinner, utilities) from `auth.css`, `admin.css`, `admin-dashboard.css`
- De-purpled admin pages: `.admin-header` → clean text + border, table `thead` → neutral gray (`#f8f9fa`), focus rings → blue (`#3b82f6`)
- Updated all 12 HTML templates: `lupin-base.css` as first stylesheet, `class="auth-page"` on login/register/change-password
- Fixed `.proxy-ratify-link` accent from purple to blue in `notifications.css`
- Profile page: lighter shadow (`0.1` opacity), centered via `margin: 20px auto`
- Full regression: 1518 unit tests pass, 0 fail

**Pre-existing integration test issues documented** (unrelated to CSS changes):
- 28 errors: "Email already registered" — stale test database, teardown not cleaning up prior registrations
- 6 errors: Missing pytest fixtures (`query`, `agent`) in `test_deep_research_orchestrator.py`
- 9 failures: bcrypt 72-byte password limit, `SessionSummary` attribute errors, registration conflicts

**Files Created (Lupin)**:
- `src/fastapi_app/static/css/lupin-base.css` — shared CSS foundation (all pages)

**Files Modified (Lupin)**:
- `src/fastapi_app/static/html/auth/css/auth.css` — scoped body, removed duplicates, fixed profile + link colors
- `src/fastapi_app/static/html/auth/admin/css/admin.css` — de-purpled header/table, blue focus rings, removed duplicates
- `src/fastapi_app/static/html/auth/admin/css/proxy-dashboard.css` — de-purpled thead, blue focus
- `src/fastapi_app/static/html/auth/admin/css/proxy-ratify.css` — de-purpled thead, blue focus
- `src/fastapi_app/static/html/admin/css/admin-dashboard.css` — removed duplicate buttons + font-family
- `src/fastapi_app/static/css/notifications.css` — proxy-ratify-link accent purple → blue
- 12 HTML templates: login, register, change-password, profile, users, proxy-ratify, proxy-dashboard, dev-tools, landing, dashboard, snapshots, notifications

---

### 2026.02.21 - Session 248 | Phase 7 + Phase 8: Proxy Notifications + Trust Mode Hot-Reload

#### Phase 7 Checkpoint | 10 tasks, 7 new tests, 1 E2E smoke — 1518 pass, 0 fail

**Phase 7 Accomplishments**:
- Relaxed `progress_group_id` regex + widened DB column for `pr-{hex}-{N}` batch IDs
- Batch generation counter + `acknowledge`/`batch-id` REST endpoints on decision proxy router
- Proxy summary notification emission in orchestrator (`_emit_proxy_summary_notification`)
- Frontend proxy ratify link + batch retirement visual in notification panel
- Focus refresh + WebSocket subscription on ratify page (belt-and-suspenders)
- Trust mode dropdown on SWE Team card (end-to-end: HTML → router → factory → job → orchestrator)
- Circuit breaker alert notification via `on_trip_callback`
- 7 new unit tests (6 proxy notification + 1 batch regex), 1 E2E smoke test

#### Phase 8: Hot-Reload of Trust Mode | 7 tasks, 16 new tests — 1534 pass, 0 fail

**Phase 8 Accomplishments**:
- Exposed `_orchestrator` reference on SweTeamJob (set during `_execute`, cleared in `finally`)
- `PUT /api/proxy/mode` endpoint — hot-reloads running orchestrator's proxy.trust_mode, falls back to INI config update
- `GET /api/proxy/mode` endpoint — returns INI mode, running mode, effective mode, has_running_job flag
- Replaced read-only trust mode span with dropdown selector on Trust Dashboard
- Dropdown wired to REST endpoint with success/queued toast + status dot indicator
- 7 hot-reload tests + 9 mode endpoint tests = 16 new tests total

**Files Modified (Lupin)**:
- `src/fastapi_app/static/html/auth/admin/proxy-dashboard.html` — mode dropdown selector
- `src/fastapi_app/static/html/auth/admin/css/proxy-dashboard.css` — `.mode-selector` + status dot styles
- `src/fastapi_app/static/html/auth/admin/js/proxy-dashboard.js` — renderModeBar → API fetch, onModeChange handler
- `src/tests/unit/test_swe_team_orchestrator.py` — TestTrustModeHotReload (7 tests)
- 4 tracking documents in `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture/`

**Files Created (Lupin)**:
- `src/tests/unit/test_decision_proxy_mode.py` — 9 mode endpoint tests

**CoSA files modified** (separate repo — commit separately):
- `job.py` — `_orchestrator` attribute + cleanup in finally
- `decision_proxy.py` router — PUT/GET /mode endpoints, TrustModeUpdateRequest, _find_running_swe_job

---

### 2026.02.21 - Session 247 | Central Navigation Hub for All HTML UIs

#### Checkpoint | 2026-02-21 | Nav bar, clean URLs, landing page — 6 new files, 18 modified, 29 nav tests pass

**Accomplishments**:
- Implemented complete Central Navigation Hub: top nav bar on every page, clean `/app/*` URLs, landing page, dev-tools page, and automated link testing
- **Phase 1**: Created `pages.py` router mapping 12 clean `/app/*` URLs to static HTML files via `FileResponse`; registered in `main.py` before static mount
- **Phase 2**: Built self-contained `lupin-nav.js` (IIFE, no auth.js dependency) + `lupin-nav.css` — data-driven nav items with role-based visibility, active page highlighting, responsive hamburger, logout
- **Phase 3**: Converted all relative CSS/JS paths to absolute in 10 HTML pages (critical for clean URL serving)
- **Phase 4**: Injected nav CSS+JS into all 10 production pages; updated 30+ hardcoded `window.location.href` calls across 4 JS files to `/app/*` clean URLs; updated `getSafeRedirectUrl()` whitelist
- **Phase 5**: Created `landing.html` (card dashboard with app + role-gated admin sections, quick stats from `/api/stats/`) and `dev-tools.html` (admin-only, lists 14 test pages as cards)
- **Phase 6**: Created `test_navigation_links.py` — 29 parametrized integration tests covering all clean URLs, legacy backward-compat paths, nav assets, root health check, and nav injection smoke tests
- Fixed: notifications.css `.section-toolbar` top offset (80→136px) for new 56px nav bar
- Fixed: Root `/` conflict — system router already serves health check; removed redirect from pages router
- All tests pass: 1511 unit, 29/29 navigation, 50/50 WebSocket

**Files Created (Lupin)**:
- `src/cosa/rest/routers/pages.py` — Clean URL → static file router (12 routes)
- `src/fastapi_app/static/js/lupin-nav.js` — Shared navigation component (IIFE)
- `src/fastapi_app/static/css/lupin-nav.css` — Navigation styles (responsive, 56px fixed)
- `src/fastapi_app/static/html/landing.html` — Central landing page with stats + admin section
- `src/fastapi_app/static/html/dev-tools.html` — Admin-only dev tools listing (14 test pages)
- `src/tests/integration/test_navigation_links.py` — 29 automated link verification tests

**Files Modified (Lupin)**:
- `src/fastapi_app/main.py` — Register pages router
- `src/fastapi_app/static/html/auth/login.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/auth/register.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/auth/profile.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/auth/change-password.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/auth/admin/users.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/auth/admin/proxy-ratify.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/auth/admin/proxy-dashboard.html` — Nav includes + absolute paths + clean URLs
- `src/fastapi_app/static/html/admin/dashboard.html` — Nav includes + clean URLs
- `src/fastapi_app/static/html/admin/snapshots.html` — Nav includes + clean URLs
- `src/fastapi_app/static/html/notifications.html` — Nav includes
- `src/fastapi_app/static/html/auth/js/auth.js` — Redirect whitelist + default path + clean URLs
- `src/fastapi_app/static/js/notifications.js` — 3 redirect paths updated
- `src/fastapi_app/static/html/admin/js/admin-dashboard.js` — 5 redirect paths updated
- `src/fastapi_app/static/html/admin/js/admin-snapshots.js` — 4 redirect paths updated
- `src/fastapi_app/static/css/notifications.css` — Toolbar top offset for nav bar

**Plan serialized**: `~/.claude/plans/jaunty-dazzling-piglet.md` (original 6-phase plan)

---

### 2026.02.21 - Session 246 | Bug Fix Mode

#### Fix 1: Urgent toggle not functional + conversation UX improvements

**Source**: bug-fix-queue.md (queued) + ad-hoc follow-ups
**Scope**: 7 sub-fixes across 4 files

1. **Double-toggle bug** (JS): `preventDefault()` stops native label→checkbox double-toggle; urgent toggle now works
2. **Urgent bubble color** (CSS): Changed from `#dc3545` (red) to `#ffcc80` (light amber matching toggle checked state)
3. **Echo temporal ordering** (JS): Moved optimistic render BEFORE `await fetch()` — user bubble now appears above the echo
4. **Echo persistence** (Python): Echo acknowledgment now persisted to database via `create_notification()` — visible in history
5. **Echo message simplified** (Python): Changed from echoing user text to "📨 Your message has been queued"
6. **Scroll on conversation toggle** (JS): `scrollIntoView()` on the interactions section header when expanding
7. **Abstract in conversation history** (JS+Python): Added `abstract` field to `get_job_interactions` API response; added clickable 📋 indicator after message text in both `renderInteractionItem()` and `createActivityLogEntry()`
8. **Claude Code Dispatcher relocated** (HTML): Moved from standalone section into "Submit Agentic Jobs" as a sub-accordion card alongside Research/Podcast/SWE Team; removed standalone toolbar button

**Files (Lupin)**:
- `src/fastapi_app/static/js/notifications.js` — toggle fix, optimistic render, scroll, abstract indicators
- `src/fastapi_app/static/css/notifications.css` — amber bubble background
- `src/fastapi_app/static/html/notifications.html` — Claude Code card relocation
- `src/cosa/rest/routers/queues.py` — echo persistence, echo message, abstract in interactions API
- **Test**: 1511 unit tests PASS, no regressions
- **Commit**: 34807f0 (Lupin), CoSA pending (queues.py)

#### Session Summary

(Will be completed at session close)

---

### 2026.02.20 - Session 245 | Phase 6: Decision Proxy UI — Ratification Page + Trust Dashboard

#### Checkpoint | 2026-02-20 | Proxy UI: 6 new files, 2 modified, 1511 tests pass

**Accomplishments**:
- Built complete Decision Proxy admin UI — Ratification Page and Trust Dashboard (Phase 6 of proxy light-up plan)
- Created ratification page (`proxy-ratify.html` + CSS + JS): summary cards (pending/approved/rejected/oldest), 3-dropdown filter bar (category/trust/action), decisions table with checkboxes and inline approve/reject, bulk actions, detail modal with feedback textarea, pagination (25/page)
- Created trust dashboard (`proxy-dashboard.html` + CSS + JS): mode bar (trust mode/domain/user), 6-category trust cards grid with level colors (L1-L5), success rate bars, circuit breaker status indicators (OK/TRIPPED/COOLDOWN), recent decisions table with category selector, pagination (50/page)
- Defined shared badge system: 4 action badges (shadow/suggest/act/defer), 5 trust level badges (L1-L5), 4 ratification state badges (pending/approved/rejected/N/R), 3 confidence color classes
- Added 2 admin cards to dashboard hub (shield+checkmark SVG for Ratification, pie chart SVG for Trust Dashboard)
- Added 2 nav buttons to profile page admin section (Pending Ratification, Trust Dashboard)
- All pages follow established patterns from `users.html`/`admin-users.js`: `requireAuth()`, `apiCall()`, `getCurrentUser()`, gradient thead, modal pattern, pagination, escapeHtml XSS prevention
- Responsive design: trust cards 3/2/1 col grid, summary cards 2x2 mobile, table horizontal scroll, modal 95% width mobile
- 1511 unit tests pass — no regressions (static HTML/CSS/JS only, no Python changes)

**Files Created (Lupin)**:
- `src/fastapi_app/static/html/auth/admin/proxy-ratify.html` — Ratification page HTML
- `src/fastapi_app/static/html/auth/admin/css/proxy-ratify.css` — Badge system + ratification styles
- `src/fastapi_app/static/html/auth/admin/js/proxy-ratify.js` — Ratification state/API/rendering logic
- `src/fastapi_app/static/html/auth/admin/proxy-dashboard.html` — Trust dashboard HTML
- `src/fastapi_app/static/html/auth/admin/css/proxy-dashboard.css` — Dashboard grid + trust card styles
- `src/fastapi_app/static/html/auth/admin/js/proxy-dashboard.js` — Dashboard state/API/rendering logic

**Files Modified (Lupin)**:
- `src/fastapi_app/static/html/admin/dashboard.html` — Added 2 admin cards in `.admin-tools-grid`
- `src/fastapi_app/static/html/auth/profile.html` — Added 2 nav buttons in `.admin-section .button-group`

**Implementation Tracking Updated**:
- `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture/01-implementation-current.md` — Phase 6 tasks 6.1-6.4 DONE
- `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture/06-testing-validation.md` — Phase 6 regression row added

---

### 2026.02.20 - Session 244 | Fix Duplicate User Bubbles + Urgent Toggle Styling + Cache Busting

#### Checkpoint | 2026-02-20 | Dedup user bubbles, urgent toggle CSS, cache-busting query params

**Accomplishments**:
- Fixed duplicate user message bubbles: removed redundant `appendJobUserMessage()` call from WebSocket `user_initiated_message` handler — optimistic render in `sendJobMessage()` already adds the bubble
- Enhanced urgent toggle CSS: base rule gets `border: 2px solid transparent` (prevents layout jitter), checked state changed from identical-to-hover `#fff3cd` to distinct amber `#ffcc80` with `2px solid #f59e0b` border
- Enhanced urgent user message bubble styling: added amber border + subtle glow + warm timestamp color for `priority-urgent` outgoing messages (applies to both live and history rendering)
- Added cache-busting query params (`?v=20260220`) to CSS and JS references in `notifications.html`
- Queued bug: urgent toggle JS handler not propagating priority on send — needs investigation of click handler (~line 1630) and `sendJobMessage()` priority extraction (~line 5580)

**Files (Lupin)**:
- `src/fastapi_app/static/js/notifications.js` — Removed duplicate `appendJobUserMessage()` in `processNotification()`
- `src/fastapi_app/static/css/notifications.css` — Urgent toggle base border, checked state amber, urgent bubble border+glow
- `src/fastapi_app/static/html/notifications.html` — Added `?v=20260220` cache-busting params
- `bug-fix-queue.md` — Queued urgent toggle propagation bug

---

### 2026.02.20 - Session 243 | Prohibit Manual Curl Testing — Documentation Updates

#### Checkpoint | 2026-02-20 | Curl prohibition documentation across 6 files

**Accomplishments**:
- Established project-wide prohibition against using curl for pipeline/integration testing across 6 documentation files
- Added "Testing Anti-Patterns" section to `CLAUDE.md` with 5 rules (NEVER curl for pipeline, NEVER manual POST+poll, NEVER bespoke curl scripts)
- Updated `AUTH-TESTING-GUIDE.md` with "Curl Patterns — Reference Only" deprecation warning before existing curl examples
- Added anti-patterns table to `src/tests/README.md` (3 anti-patterns with alternatives)
- Added blockquote note to `src/tests/smoke/README.md` pointing to CLAUDE.md anti-patterns
- Strengthened `.claude/skills/testing-patterns/SKILL.md` with 2 NEVER rules prepended to existing anti-patterns
- Updated TEST CREDENTIALS reference in CLAUDE.md to discourage curl, redirect to automated tests
- Curl remains acceptable for: API reference docs, deployment health checks, one-off debugging (never committed)

**Files (Lupin)**:
- `CLAUDE.md` — Added Testing Anti-Patterns section + updated TEST CREDENTIALS reference
- `src/tests/AUTH-TESTING-GUIDE.md` — Added "Curl Patterns — Reference Only" deprecation warning
- `src/tests/README.md` — Added Testing Anti-Patterns table
- `src/tests/smoke/README.md` — Added automated-testing-only blockquote
- `.claude/skills/testing-patterns/SKILL.md` — Prepended 2 NEVER rules to Anti-Patterns section

---

### 2026.02.20 - Session 242 | Approach D: Rename, Smoke Tests, Fix Running Queue Poll + Configurable Dry-Run

#### Checkpoint | 2026-02-20 | Rename user_message → user_initiated_message, 10-scenario smoke test, running queue poll fix, loop-based dry-run

**Accomplishments**:
- Renamed notification type `"user_message"` → `"user_initiated_message"` across 4 files (notification_client.py, queues.py, notifications.js, unit tests) for semantic clarity distinguishing proactive user communication from agent-initiated `response_requested` notifications
- Created `test_approach_d_user_messages.py` smoke test with 10 scenarios: 6 error scenarios (empty, whitespace, bad priority, no job, no auth, no body) + 4 happy-path inject scenarios (normal msg, urgent msg, multi msg, verify DB interactions)
- Fixed critical bug in running queue poll: `running_jobs_metadata` → `run_jobs_metadata` (API returns `f"{queue_name}_jobs_metadata"` where `queue_name="run"`)
- Made dry-run configurable: `dry_run_phases` (default 10) and `dry_run_delay` (default 1.5s) parameters added to SweTeamJob, wired through agentic_job_factory.py. Replaced 6 hardcoded sleep calls with loop over `DRY_RUN_PHASE_LABELS` list. Total dry-run: 15s (was 6s)
- Fixed results table "skip" handling in smoke test — skips no longer count as failures in "Overall" verdict

**Files (Lupin)**:
- `src/tests/smoke/test_approach_d_user_messages.py` — NEW: 10-scenario Approach D smoke test
- `src/tests/unit/test_swe_team_job.py` — Updated notification count assertion (7 → 11)
- `src/fastapi_app/static/js/notifications.js` — Renamed `'user_message'` → `'user_initiated_message'`
- `src/tests/unit/test_swe_team_notification_client.py` — Renamed type values in 9 test dicts

**Files (CoSA — commit separately)**:
- `src/cosa/agents/swe_team/notification_client.py` — Renamed filter, docstrings, smoke test dicts
- `src/cosa/agents/swe_team/job.py` — Added dry_run_phases/delay params, loop-based _execute_dry_run(), DRY_RUN_PHASE_LABELS
- `src/cosa/rest/routers/queues.py` — Renamed type in create_notification + WS emission
- `src/cosa/rest/agentic_job_factory.py` — Wire dry_run_phases/delay through factory

**Test**: 330 SWE unit tests PASS, 10/10 smoke test scenarios PASS

---

### 2026.02.20 - Session 241 | Activate SWE Team Proxy in Shadow Mode + Wire Trust Feedback Loop

#### Checkpoint | 2026-02-20 | Proxy default changed to shadow, trust feedback recorded on every user decision

**Accomplishments**:
- Changed SWE Team proxy default `trust_mode` from `"disabled"` to `"shadow"` — proxy object now created on every orchestrator, but shadow mode never acts autonomously (safe, observability-first)
- Restructured `_gated_confirmation()` to always call `evaluate()` for all non-disabled modes (shadow, suggest, active), then record trust feedback after user answers — agreement/disagreement tracked via `TrustTracker.record_decision()`
- Active mode auto-approval path now records `success=True` in trust tracker; suggest mode records user follow-through; shadow mode observes and records silently
- All trust recording wrapped in try/except so failures never break the main confirmation flow
- Added INI documentation keys for `swe team trust mode` in both config and splainer files
- Added 7 new tests in `TestTrustFeedbackLoop` class: shadow agreement/disagreement, active auto-approve records success, suggest agreement/disagreement, error resilience, shadow default creates proxy
- Updated 4 existing tests for new shadow default: renamed `test_default_trust_mode_disabled` → `_shadow`, explicit `trust_mode="disabled"` where proxy-None is needed, shadow evaluate assertion updated

**Files (Lupin)**:
- `src/conf/lupin-app.ini` — Added `swe team trust mode = shadow`
- `src/conf/lupin-app-splainer.ini` — Added trust mode explanation
- `src/tests/unit/test_swe_team_orchestrator.py` — 7 new + 4 updated tests (49 total in file)

**Files (CoSA — commit separately)**:
- `src/cosa/agents/swe_team/config.py` — Default `trust_mode` from `"disabled"` → `"shadow"`
- `src/cosa/agents/swe_team/orchestrator.py` — `_gated_confirmation()` restructured with trust feedback loop

**Test**: 1490 unit tests PASS (7 new + 1483 existing)

---

### 2026.02.20 - Session 240 | Add dry_run as Voice-Detectable Runtime Argument for SWE Team Training Data

#### Checkpoint | 2026-02-20 | Conditional args detection for LoRA training data generation

**Accomplishments**:
- Added 108 dry-run template lines to SWE team training data (75 natural phrasing + 33 ASR robustness variants) — 204 total lines, 53% dry-run coverage
- Introduced `conditional_args` config key to `agent-router-agentic-commands.json` — 16 trigger phrases (canonical + ASR mishearings like "try run", "dry bun", "dry rum")
- Modified `xml_coordinator.py` generator to scan voice commands for trigger phrases and append `dry_run="True"` to args output when matched
- Added 6 new unit tests in `TestSweTeamDryRunCoverage` class: template count, coverage minimum, ASR variant count, config presence, triggers list, no contamination in other agent templates
- All 17 SWE team training data tests pass, full unit suite: 1483 passed, 0 failures

**Files (Lupin)**:
- `src/ephemera/prompts/data/synthetic-data-agent-routing-swe-team.txt` — 108 new dry-run template lines (2 new sections)
- `src/conf/training/agent-router-agentic-commands.json` — `conditional_args` with `dry_run` triggers
- `src/tests/unit/test_swe_team_training_data.py` — 6 new tests + `DRY_RUN_TRIGGERS` constant

**Files (CoSA — commit separately)**:
- `src/cosa/training/xml_coordinator.py` — 7 lines for conditional args detection in `build_agentic_job_training_prompts()`

**Test**: 1483 unit tests PASS (6 new + 1477 existing)

---

### 2026.02.20 - Session 239 | Add Playwright E2E Testing Placeholder Notes (v0.1.6)

#### Checkpoint | 2026-02-20 | Forward-looking v0.1.6 Playwright E2E placeholders across 4 docs

**Accomplishments**:
- Added Phase 5c (UI E2E Testing) row to agentic-voice-workflow SKILL.md phase table and a callout note after the Key Test Infrastructure Files table
- Added Phase 5c line and Playwright reference to the slash command phase list and Testing References section
- Added Playwright E2E checklist item to FINAL VERIFICATION section in the canonical workflow document
- Added UI E2E tier row to testing-patterns SKILL.md Test Tiers table and a new "UI E2E Tests (Planned)" section before Anti-Patterns

**Files (Lupin)**:
- `.claude/skills/agentic-voice-workflow/SKILL.md` — Phase 5c row + v0.1.6 callout
- `.claude/commands/lupin-new-claude-agent-sdk-voice-workflow.md` — Phase 5c + Testing References line
- `src/workflow/agentic-voice-workflow.md` — FINAL VERIFICATION checklist item
- `.claude/skills/testing-patterns/SKILL.md` — UI E2E tier row + planned section

---

### 2026.02.19 - Session 238 | Approach D: Implement Hybrid Queue + Check-In for User-Initiated SWE Team Communication

#### Checkpoint | 2026-02-19 | Full 5-phase implementation of user-to-orchestrator mid-task messaging

**Accomplishments**:
- Implemented Approach D end-to-end: users can now send messages to running SWE Team jobs anytime via a WebSocket-based message queue. Messages accumulate in a `threading.Queue` and drain at orchestrator check-in points with LLM-powered analysis + yes/no confirmation
- **Phase 1**: Created `OrchestratorNotificationClient` — WebSocket client adapted from `BaseWebSocketListener` that filters for `user_message` notifications matching the target `job_id`, queues them for the orchestrator, and sets `threading.Event` on urgent priority
- **Phase 2**: Added queue drain + urgent interrupt to orchestrator — `_drain_user_messages()`, `_analyze_user_messages()` methods, modified `_check_in_with_user()` to drain before existing logic, added urgent interrupt check between task delegations in `_execute_live()`
- **Phase 3**: Modified `job.py` to create/manage notification client lifecycle; added `POST /api/jobs/{job_id}/message` REST endpoint to `queues.py` with job ownership validation
- **Phase 4**: Added message input UI to running job cards — text input with STT button, urgent priority toggle, send button, live interaction pane with cross-tab sync via WebSocket
- **Phase 5**: 20 new notification client tests + 10 new orchestrator queue drain tests — all 317 SWE team tests pass, 0 regressions
- Moved planning doc from `src/rnd/` root into `src/rnd/2026.02.13-claude-code-agentic-dev-team/`

**Files (CoSA — commit separately)**:
- `src/cosa/agents/swe_team/notification_client.py` — NEW: WebSocket client for user message filtering + queuing
- `src/cosa/agents/swe_team/orchestrator.py` — Queue drain, LLM analysis, urgent interrupt between tasks
- `src/cosa/agents/swe_team/config.py` — Added `enable_user_messages: bool = True`
- `src/cosa/agents/swe_team/job.py` — Notification client lifecycle management
- `src/cosa/rest/routers/queues.py` — `POST /api/jobs/{job_id}/message` endpoint

**Files (Lupin)**:
- `src/fastapi_app/static/js/notifications.js` — Job card message input, STT, send handler, cross-tab sync
- `src/fastapi_app/static/css/notifications.css` — Message input styling, urgent toggle, user message items
- `src/rnd/2026.02.13-claude-code-agentic-dev-team/2026.02.18-approach-d-hybrid-queue-checkin.md` — MOVED from `src/rnd/`
- `src/tests/unit/test_swe_team_notification_client.py` — NEW: 20 unit tests
- `src/tests/unit/test_swe_team_orchestrator.py` — 10 new `TestUserMessageQueue` tests

**Test**: 317 SWE team tests PASS (20 new + 10 new + 287 existing)
**Plan file**: `~/.claude/plans/elegant-brewing-adleman.md`

---

### 2026.02.19 - Session 237 | Approach C: Hybrid Fast Lane + Bounded Agentic Pool (Planning)

#### Checkpoint | 2026-02-19 | Create planning documentation for CJ Flow concurrent processing

**Accomplishments**:
- Created implementation tracking document for Approach C: hybrid architecture where consumer thread becomes a dispatcher that processes sync agents inline (fast lane) and submits agentic jobs to a bounded `ThreadPoolExecutor`
- Documented thread safety model with shared-state analysis (RLock on FifoQueue, existing thread-safety in WebSocketManager/UserJobTracker/emit_job_state_transition)
- Designed 3-phase implementation plan: Phase 1 (RLock + config + thread safety tests), Phase 2 (pool + dispatcher refactor + tests), Phase 3 (API endpoint + E2E verification)
- Updated TODO.md with 10 phase-by-phase checklist items
- Updated src/rnd/README.md with link to tracking document
- Zero implementation code — planning documents only

**Files (Lupin)**:
- `src/rnd/2026.02.19-approach-c-hybrid-queue-architecture.md` — NEW: Implementation tracking doc with Mermaid diagram, thread safety model, phase checklist, critical files table
- `src/rnd/README.md` — Added entry for Approach C
- `TODO.md` — Added CJ Flow concurrent processing section (10 items)
- `history.md` — This entry

---

### 2026.02.19 - Session 236 | Bug #5: Unify Job-User-Session Association

#### Checkpoint | 2026-02-19 | Eliminate dual-bookkeeping in CJ Flow queue system

**Accomplishments**:
- Implemented 5-phase plan to eliminate dual-bookkeeping where `UserJobTracker` side-table duplicated user/session info already on job objects via `QueueableJob` protocol
- **Phase 0**: Fixed JWT key bug in 2 routers (`"user_id"` -> `"uid"` — key never existed in JWT, silently fell back to email)
- **Phase 1**: Added `register_scoped_job()` atomic method to `UserJobTracker` — replaces scattered 2-3 call sequences
- **Phase 2**: Migrated 11 write sites across 9 files to `register_scoped_job()` — makes scoped IDs (`base_hash::user_id`) universal across ALL job types
- **Phase 3**: Replaced 12 `get_user_for_job()` tracker lookups with direct `job.user_id` — `QueueableJob` protocol guarantees attribute exists
- **Phase 4**: Removed 5 dead methods + 2 dead dicts from `UserJobTracker` — class now focused on reverse-index for O(1) queue filtering
- Added 13 new unit tests for `register_scoped_job()` and related methods
- All 1,447 unit tests passing after changes

**Files (CoSA — commit separately)**:
- `src/cosa/rest/queue_extensions.py` — Add `register_scoped_job()`, remove 5 dead methods/2 dicts
- `src/cosa/rest/running_fifo_queue.py` — 9 tracker lookups -> direct `job.user_id`
- `src/cosa/rest/todo_fifo_queue.py` — 3 write consolidations + 1 read simplification
- `src/cosa/rest/queue_consumer.py` — 1 tracker lookup -> `job.user_id`
- `src/cosa/rest/routers/queues.py` — 1 tracker lookup -> `job.user_id` + remove unused import
- `src/cosa/rest/routers/podcast_generator.py` — JWT fix + scoped ID (2 sites)
- `src/cosa/rest/routers/deep_research_to_podcast.py` — JWT fix + scoped ID
- `src/cosa/rest/routers/deep_research.py` — Scoped ID
- `src/cosa/rest/routers/claude_code_queue.py` — Scoped ID
- `src/cosa/rest/routers/swe_team.py` — Scoped ID
- `src/cosa/rest/routers/mock_job.py` — Scoped ID (2 sites)

**Files (Lupin)**:
- `src/tests/unit/test_queue_extensions.py` — NEW: 13 unit tests
- `src/tests/unit/test_crud_queue_integration.py` — Fixed mock setup (added `user_id`)

**Test**: 1,447 unit tests PASS
**Commit**: aece71f
**Plan file**: `~/.claude/plans/cosmic-herding-quill.md`

---

### 2026.02.18 - Session 235 | Approach D Planning: Hybrid Queue + Check-In for User-Initiated Communication

**Accomplishments**:
- Planned Approach D implementation for user-initiated communication with running SWE Team jobs
- Design decision: WebSocket inbound event (`user_message_to_job`) instead of REST endpoint — consistent with existing fire-and-forget notification architecture
- Design decision: LLM-powered analysis at check-in — lead model analyzes accumulated messages and proposes concrete actions, then asks yes/no confirmation before incorporating
- Created serialized plan document at `src/rnd/2026.02.18-approach-d-hybrid-queue-checkin.md`
- Updated TODO.md with high-priority resume-next-session item
- Updated R&D README with new document link

**Files**: 3 new/modified (Lupin repo)
- `src/rnd/2026.02.18-approach-d-hybrid-queue-checkin.md` — NEW: Serialized implementation plan
- `src/rnd/README.md` — Added Approach D entry
- `TODO.md` — Added Approach D implementation item

**Plan file**: `~/.claude/plans/agile-kindling-tide.md` (5 files, ~170 lines, 6 steps)

---

### 2026.02.18 - Session 234 | Bug F: sender_id Validation Fix for SWE Team Notifications

**Accomplishments**:
- Verified Bug F fix already applied in `cosa_interface.py`: `get_sender_id()` now strips `::user_id` suffix from compound session IDs before building sender_id
- Confirmed smoke test coverage (compound hash stripping assertions) already in place
- Fix lives in CoSA submodule — uncommitted, needs separate CoSA commit

**Files**: 0 modified (Lupin repo), 1 modified (CoSA repo — commit separately)
- `src/cosa/agents/swe_team/cosa_interface.py` — Strip `::user_id` from session_id in `get_sender_id()` + smoke test *(CoSA)*

**Note**: Short verification-only session. The fix was applied in a prior session's context but the CoSA commit was not yet made.

---

### 2026.02.18 - Session 233 | User-Initiated Check-In for SWE Team Orchestrator

#### Checkpoint | 2026.02.18 | Implement Approach B MVP — periodic check-in between tasks

**Accomplishments**:
- Created R&D document `05-user-initiated-communication.md` analyzing 4 approaches for user-to-orchestrator communication; recommends Approach B (periodic check-in) as MVP foundation for future Approach D (hybrid queue)
- Added `_check_in_with_user()` method to orchestrator — enters WAITING_FEEDBACK state, calls `get_feedback()` with configurable timeout, classifies response via `is_approval()`
- Added 2 check-in call sites in `_execute_live()`: between-task (with feedback injection into next task's objective) and post-completion (before summary)
- Added `enable_checkins` (bool, default True) and `checkin_timeout` (int, default 30s) config fields
- Updated 9 unit test mocks to include `get_feedback = AsyncMock( return_value=None )` — all 65 SWE Team tests passing
- Updated 00-index.md with new document entry

**Files**: 2 modified + 1 new (Lupin repo), 2 modified (CoSA repo — commit separately)
- `src/rnd/2026.02.13-claude-code-agentic-dev-team/05-user-initiated-communication.md` — NEW: Full analysis + MVP design + Approach D expansion
- `src/rnd/2026.02.13-claude-code-agentic-dev-team/00-index.md` — Added doc row
- `src/tests/unit/test_swe_team_delegation.py` — 3 tests: added `get_feedback` AsyncMock
- `src/tests/unit/test_swe_team_verification.py` — 6 tests: added `get_feedback` AsyncMock
- `src/cosa/agents/swe_team/orchestrator.py` — `_check_in_with_user()` + 2 call sites + feedback injection *(CoSA)*
- `src/cosa/agents/swe_team/config.py` — `enable_checkins`, `checkin_timeout` *(CoSA)*
- `history.md` — this entry

**Commit**: c14ca6b

---

### 2026.02.18 - Session 232 | Fix SWE Team vs Claude Code Routing Confusion in LoRA Training Data

#### Checkpoint | 2026-02-18 | Improve discriminability between SWE team and Claude Code training examples

**Accomplishments**:
- Created `placeholders-swe-team-tasks.txt` with 100 feature-oriented task descriptions (e.g., "user authentication and registration flow", "payment processing integration with Stripe") — semantically distinct from the coding-task style of `placeholders-claude-code-tasks.txt`
- Updated `agent-router-agentic-commands.json` to point SWE team placeholder from `claude_code_tasks` → `swe_team_tasks`
- Added `get_swe_team_tasks()` getter to `XmlPromptGenerator` and registered `swe_team_tasks` in `XmlCoordinator` dispatch dict
- Added 6 direct routing phrases ("go to swe team for FEATURE") and 5 ASR robustness variants ("go to the sweet team for FEATURE") to the SWE team template
- Updated `VALID_GETTER_NAMES` in unit test to include `swe_team_tasks`
- Full regression: 1434 unit tests passing, 0 failures

**Files**: 4 modified + 1 new (Lupin repo), 2 modified (CoSA repo — commit separately)
- `src/ephemera/prompts/data/placeholders-swe-team-tasks.txt` — NEW: 100 feature-oriented SWE task descriptions
- `src/ephemera/prompts/data/synthetic-data-agent-routing-swe-team.txt` — Added 11 routing + ASR phrases
- `src/conf/training/agent-router-agentic-commands.json` — Placeholder swap `claude_code_tasks` → `swe_team_tasks`
- `src/tests/unit/test_swe_team_training_data.py` — Added `swe_team_tasks` to valid getter set
- `src/cosa/training/xml_prompt_generator.py` — `get_swe_team_tasks()` method *(CoSA)*
- `src/cosa/training/xml_coordinator.py` — Dispatch registration *(CoSA)*
- `history.md` — this entry

---

### 2026.02.18 - Session 231 | Fix Duplicate Notification + Raw JSON Response Rendering

#### Checkpoint | 2026-02-18 | Fix duplicate "submitted" notification + human-readable response values

**Accomplishments**:
- **Bug D — Duplicate "submitted" notification**: Added early `return` after the `AGENTIC_AGENTS` branch in `push_job()` — prevents fallthrough to common post-chain code that sent a second `_notify( msg, job=None )` without `job_id`, routing to the wrong sender card (Lupin/Claude Code accordion instead of the job card)
- **Bug E — Raw JSON in response values**: Added `formatResponseValue()` helper method to `notifications.js` that unwraps the `{value, source}` JSON envelope and formats nested `answers` dicts as readable `key: value` pairs; updated `renderInteractionItem()` to use it
- Full regression: 1434 unit tests passing, 0 failures

**Files**: 1 modified (Lupin repo), 1 modified (CoSA repo — commit separately)
- `src/cosa/rest/todo_fifo_queue.py` — Early return after agentic branch (line 738-739) *(CoSA)*
- `src/fastapi_app/static/js/notifications.js` — `formatResponseValue()` + updated `renderInteractionItem()`
- `history.md` — this entry

---

### 2026.02.18 - Session 230 | Expeditor UX Bugs + Speculative Job ID for Agentic Routing

#### Checkpoint | 2026-02-18 | Fix 3 expeditor UX bugs + speculative job card for agentic routing

**Accomplishments**:
- **Bug 2 — TTS reads all batch questions**: Truncated `format_open_ended_batch_for_tts()` to return count-only preamble (`"I have N questions for you."`) instead of reading every question aloud — individual questions are already displayed in the UI batch form
- **Bug 1 — Task field not pre-populated**: Added 4-line block in `expeditor.expedite()` that populates `fallback_defaults` with `original_question` for required args missing a default — user's question now appears as `default_value` in the batch form (works for all 5 agents: SWE Team `task`, Deep Research `query`, etc.)
- **Step 3A — Registry `job_prefix`**: Added `"job_prefix"` field to all 5 AGENTIC_AGENTS entries (dr, pg, rp, cc, swe) — enables speculative ID generation before expeditor runs
- **Step 3B — Speculative job ID**: Rewrote `_handle_agentic_command()` to generate a speculative job ID before expeditor, emit `pending→todo` with `expediting: True` metadata, pass `job_id` to expeditor for notification routing, and handle cancel/failure cleanup (→ dead queue + `remove_job`)
- **Step 3C — Expediting UI indicator**: Propagated `expediting` flag from metadata to job object in `handleJobStateTransition()`; added amber spinning `⟳` indicator for expediting cards in todo queue (CSS `.status-indicator.expediting`)
- Updated 1 unit test assertion + fixed empty-list edge case to match new TTS behavior
- Full regression: 1434 unit tests passing, 0 failures

**Files**: 4 modified (Lupin repo), 4 modified (CoSA repo — commit separately)
- `src/cosa/utils/notification_utils.py` — Batch TTS truncation + empty-list guard *(CoSA)*
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` — Fallback default pre-population *(CoSA)*
- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` — `job_prefix` field + smoke test *(CoSA)*
- `src/cosa/rest/todo_fifo_queue.py` — Speculative job ID + `import uuid` *(CoSA)*
- `src/fastapi_app/static/js/notifications.js` — Propagate `expediting` flag + indicator
- `src/fastapi_app/static/css/notifications.css` — `.expediting` animation (amber spin)
- `src/tests/unit/test_runtime_argument_expeditor.py` — Updated batch TTS assertion
- `history.md` — this entry

---

### 2026.02.18 - Session 229 | Add Agentic Agent Mode Switches to Q&A Card

#### Checkpoint | 2026-02-18 | Add agentic modes to Q&A dropdown + routing logic + unit tests

**Accomplishments**:
- Added `AGENTIC_MODE_MAP` dict (5 entries) mapping mode keys to routing commands, plus 5 new `MODE_METADATA` entries for UI display
- Added `elif user_mode in AGENTIC_MODE_MAP` branch in routing logic — agentic modes now bypass LoRA router entirely and produce commands that enter the agentic path (disambiguation → expeditor → factory)
- Updated `set_user_mode()` validation to accept both `MODE_TO_AGENT` and `AGENTIC_MODE_MAP` keys
- Added `<optgroup>` separators to HTML dropdown — "Quick Agents" (7 existing) and "Agentic Processes" (5 new: Deep Research, Podcast Generator, Research to Podcast, Claude Code, SWE Team)
- New unit test file: `test_mode_management.py` with 27 tests across 5 classes (dict consistency, set/get/clear mode, available modes, command mapping)
- Full regression: 1434 unit tests passing, 0 failures

**Files**: 3 modified + 1 new (Lupin repo), 1 modified (CoSA repo)
- `src/cosa/rest/todo_fifo_queue.py` — `AGENTIC_MODE_MAP`, `MODE_METADATA` entries, routing branch, validation update *(CoSA repo — commit separately)*
- `src/fastapi_app/static/html/notifications.html` — `<optgroup>` + 5 agentic `<option>` entries
- `src/tests/unit/test_mode_management.py` — 27 new unit tests
- `history.md` — this entry

---

### 2026.02.18 - Session 228 | Mount ~/.lora_env into Docker container

#### Checkpoint | 2026-02-18 | Add .lora_env volume mount to start-docker-lupin.sh

**Accomplishments**:
- Fixed LoRA env var resolution in Docker — Session 227's `main.py` parser works natively but inside the container `/root/.lora_env` didn't exist
- Added `-v "$HOME/.lora_env:/root/.lora_env:ro"` read-only volume mount to `docker run` command in `start-docker-lupin.sh`
- Verified: file mounts correctly, parser reads it, env vars resolve in-process (note: `docker exec` can't see them — it spawns a separate process)

**Files**: 1 modified (scripts repo)
- `$DEEPILY_PROJECTS_DIR/scripts/server/start-docker-lupin.sh` — `.lora_env` volume mount (commit `4ccbcfc` in scripts repo)

---

### 2026.02.18 - Session 227 | Fix LoRA env var resolution in FastAPI server

#### Checkpoint | 2026-02-18 | Load ~/.lora_env at Python level in main.py + belt-and-suspenders in shell script

**Accomplishments**:
- Fixed `${LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH}` not resolving in FastAPI server — `os.path.expandvars()` was working but env var was unset in server process because `run-fastapi-lupin.sh` never sourced `~/.lora_env`
- Added `~/.lora_env` parser in `main.py` after LUPIN_ROOT bootstrap — reads `export KEY="value"` lines into `os.environ` before ConfigurationManager init
- Added `source ~/.lora_env` belt-and-suspenders in `run-fastapi-lupin.sh`
- Updated `lupin-app.ini` to use `${LUPIN_ROUTER_LORA_MINISTRAL_8B_PATH}` and `${LUPIN_ROUTER_LORA_QWEN3_4B_PATH}` env var references instead of hardcoded paths
- Updated splainer.ini with env var resolution documentation
- Added post-training `source ~/.lora_env` to `run-agentic-intent-training.sh`
- New smoke test: `test_lora_env_update_smoke.py`

**Files**: 6 modified/new
- `src/fastapi_app/main.py` — `~/.lora_env` loader (11 lines)
- `src/scripts/run-fastapi-lupin.sh` — belt-and-suspenders source
- `src/conf/lupin-app.ini` — env var references for LoRA model paths
- `src/conf/lupin-app-splainer.ini` — env var resolution docs
- `src/scripts/run-agentic-intent-training.sh` — post-training env sourcing
- `src/tests/smoke/test_lora_env_update_smoke.py` — new smoke test

---

### 2026.02.18 - Session 226 | Voice-Driven SWE Team Job Creation with dry_run Support

#### Checkpoint | 2026.02.18 | Fix SWE Team voice + dry_run support (factory wiring, _parse_boolean, registry, proxy, tests)

**Accomplishments**:
- Wired canonical `create_agentic_job()` factory into voice path in `todo_fifo_queue.py`, replacing inline 3-of-5-agent factory — unblocks SWE Team and Claude Code for voice-driven job creation
- Added `_parse_boolean()` helper to `agentic_job_factory.py` and updated all 5 `dry_run` lines — fixes bug where string `"no"` was truthy in Python, causing all voice-created jobs to run as dry_run=True
- Added `dry_run` to SWE Team registry entry (arg_mapping, fallback_questions, fallback_defaults) and CLI `--user-visible-args`
- Removed 3 hardcoded `dry_run` exclusions in `expeditor.py` — visibility now controlled by `user_visible` whitelist (shown for SWE Team, hidden for Deep Research)
- Added `dry_run` Q&A proxy entry to `swe-team.json` and updated `all_agents`/`swe_team` TEST_PROFILES
- Added 12 new unit tests (7 for `_parse_boolean`, 5 for dry_run visibility) — 1407 total passing

**Files (Lupin repo)**: 2 files modified
- `src/conf/notification-proxy-scripts/swe-team.json` — dry_run Q&A proxy entry
- `src/tests/unit/test_runtime_argument_expeditor.py` — 12 new tests

**Files (CoSA nested repo)**: 6 files modified
- `src/cosa/rest/todo_fifo_queue.py` — canonical factory import, deleted 75 lines dead code
- `src/cosa/rest/agentic_job_factory.py` — `_parse_boolean()`, updated 5 dry_run lines
- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` — dry_run in SWE Team entry
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` — removed 3 dry_run exclusions
- `src/cosa/agents/swe_team/__main__.py` — dry_run in --user-visible-args
- `src/cosa/agents/notification_proxy/config.py` — dry_run in TEST_PROFILES

**Commit**: e568f43

---

### 2026.02.18 - Session 225 | Fix SWE Team Notification Routing to CJ Flow Job Card

**Accomplishments**:
- Fixed positional argument mismatch between core `voice_io.notify()` dispatcher and SWE Team's `cosa_interface.notify_progress()` — converted all 4 dispatch branches from positional to keyword arguments, making it immune to extra params like `role`
- Added `SESSION_ID = self.id_hash` in SWE Team job's `_execute_dry_run()` and `_execute()` paths so sender_id includes job hash suffix for proper routing
- Added missing `progress_group_id` parameter to SWE Team `voice_io.notify()` wrapper
- Changed `agentic_job_base.py` `notify_progress()` and `notify_completion()` to import core `voice_io` instead of hardcoded Deep Research `voice_io`, preventing all subclasses from using DR's sender identity
- All 1395 unit tests pass, all smoke tests green

**Files (CoSA nested repo)**: 4 files modified
- `src/cosa/agents/utils/voice_io.py` — keyword args in dispatch
- `src/cosa/agents/swe_team/job.py` — SESSION_ID assignment
- `src/cosa/agents/swe_team/voice_io.py` — progress_group_id param
- `src/cosa/agents/agentic_job_base.py` — core voice_io import

---

### 2026.02.18 - Session 224 | Progress Group Accordion Layout Fix

#### Checkpoint | 2026.02.18 | Fix progress group side-by-side → vertical stack + right-align toggle badge

**Accomplishments**:
- Fixed progress group accordion layout: added `flex-direction: column` to `.progress-group-entry` to override parent `.sender-message`'s horizontal flex — head and history now stack vertically instead of side-by-side
- Right-aligned toggle/count badge: added `width: 100%` to `.progress-group-head` so `margin-left: auto` on the toggle badge pushes it to the right edge
- Verified with 2 rounds of 5 test notifications using `progress_group_id`

**Files**: `src/fastapi_app/static/css/notifications.css` (2 lines added)
**Commit**: 29921df

---

### 2026.02.17 - Session 223 | Testing Skill Documentation — Pattern A Authority Model

#### Checkpoint | 2026.02.17 | Update testing-development skill with Pattern A authority model

**Accomplishments**:
- Updated `~/.claude/skills/testing-development/SKILL.md`: Added "Smoke Test Authority Model (Pattern A)" section between Three-Tier table and Quick Commands; revised Key Principles to 7 items with Pattern A principles first (source QST is truth, wrappers never duplicate, every file has test_*)
- Rewrote `~/.claude/skills/testing-development/references/smoke-tests.md`: Replaced Option 1/2 with Pattern A two-layer architecture (source QST + thin pytest wrapper), added decision tree (5 categories: thin wrapper, subsystem, offline, cross-object, unit-in-disguise), return convention (True/False vs raises), canonical file anatomy, naming conventions, orphan detection audit commands, nuanced anti-patterns table with exceptions
- Updated `~/.claude/skills/testing-development/references/unit-tests.md`: Added "Boundary: When a Smoke Test Is Really a Unit Test" section with 4 smell indicators (@patch, MagicMock, method-level testing, fixture mocks)
- Documentation only — no code changes to actual test files
- Verified all examples match real Lupin smoke test files (orchestrator dry-run, decision proxy offline, deep research dry-run)

**Files**: 3 skill documentation files in `~/.claude/skills/testing-development/` (outside repo)

---

### 2026.02.17 - Session 222 (continued) | Smoke Test Consistency Cleanup

#### Checkpoint | 2026.02.17 | Pattern A consistency for all smoke test files

**Accomplishments**:
- Converted 2 redundant smoke test files to thin wrappers importing source module QSTs (orchestrator, queue_consumer)
- Converted 3 legitimate smoke test files to Pattern A: QST authoritative, thin `test_*` wrapper (decision_proxy, answer_feedback, simple_agents)
- Converted 1 borderline smoke test to Pattern A (agentic_disambiguation)
- Added pytest `test_*` wrappers to 4 orphaned files (crud_dataframes, deep_research_submit, token_refresh, vllm_client)
- Fixed 1 broken file: renamed `test_*` functions with non-fixture params to `_run_*` helpers (notifications_progress_group)
- Added `test_embedding_benchmark()` wrapper to embedding benchmark file
- Result: 37 smoke tests collected, zero ERRORs, zero orphaned files; 1395 unit tests passing

**Files**: 12 smoke test files in `src/tests/smoke/`

---

### 2026.02.17 - Session 220 (continued) | Progress Group History Accumulation

#### Checkpoint 3 | 2026.02.17 | Backend persistence + frontend accordion for progress group history

**Accomplishments**:
- Step 1: Added `progress_group_id` column to `Notification` model (String(12), nullable, indexed)
- Step 2: Created Alembic migration `b5c6d7e8f9a0` — add column + index, ran upgrade successfully
- Step 3: Added `progress_group_id` param to `create_notification()` in notification_repository.py
- Step 4: Wired `progress_group_id` through all 3 `create_notification()` call sites in notifications router; added `progress_group_id` + `job_id` (bonus fix) to both serialization dicts (`get_sender_conversation` + `get_sender_conversation_by_date`)
- Step 5: Rewrote `updateProgressGroupEntry()` and `updateSenderProgressGroupEntry()` in JS — now accumulates history (old head → collapsible history container, newest first) with toggle chevron; wrapped initial entries in `.progress-group-head` div structure; added delegated click handlers for toggle on both job card activity logs and sender card date accordions
- Step 6: Added CSS styles for `.progress-group-head`, `.progress-group-toggle`, `.progress-group-history`, `.progress-history-entry`
- Full regression: 1395 unit tests pass, 0 failures

**Files**: postgres_models.py, migration b5c6d7e8f9a0, notification_repository.py, notifications.py (router), notifications.js, notifications.css
**Commit**: 0c53952 (Lupin) + CoSA pending

---

### 2026.02.17 - Session 222 | SWE Team Training Data + Remove Superfluous Agentic JSONL

#### Checkpoint | 2026.02.17 | SWE Team training data + remove unused agentic-only JSONL output

**Accomplishments**:
- Removed superfluous agentic-only JSONL write pipeline (stale regex, unused output)
  - Deleted `write_agentic_job_ttv_split_to_jsonl()` + `get_agentic_job_train_test_validate_split()` from xml_coordinator.py
  - Removed reference write block + cleaned validate/test/full blocks in run-agentic-intent-training.sh
  - Removed agentic entries from analyze-training-distribution.py
  - Deleted 3 orphaned agentic-job-xml-{train,test,validate}.jsonl files
- SWE Team training data additions (from earlier in session)
- Full regression: 1395 unit tests pass, 0 failures

**Files**: xml_coordinator.py, run-agentic-intent-training.sh, analyze-training-distribution.py, +7 earlier files
**Commit**: 6bae381

---

### 2026.02.17 - Session 221 | TODO.md Structural Cleanup

#### Checkpoint | 2026.02.17 | TODO.md structural cleanup

**Accomplishments**:
- Moved 14 fully-completed sections from Pending to condensed one-liners in Completed (Recent)
- Trimmed mixed sections (DataFrame CRUD, Before Branch Merge) to open items only
- Pending section reduced from ~200 lines to ~74 lines (17 open items preserved)
- 15 new condensed summary lines added to Completed (Recent)

**Files**: TODO.md
**Commit**: 3cf8551

#### Checkpoint 2 | 2026.02.17 | TODO.md updates: SWE Team Docs to Completed + new items

**Accomplishments**:
- Moved SWE Team Testing Docs Update from Pending to Completed (Recent) as condensed one-liner
- Added "Run and remediate full testing harness" to Before Branch Merge section
- Added "Automated E2E Testing Research" (MEDIUM) — research AI/automation for notification, API, and UI testing

**Files**: TODO.md
**Commit**: 2ee4a32

---

### 2026.02.17 - Session 220 | Wire progress_group_id Into All Agentic Iterative Loops

#### Checkpoint | 2026.02.17 | Wire progress_group_id into PG, DR, SWE Team loops

**Accomplishments**:
- Phase 1 (Infrastructure): Added `progress_group_id` + `queue_name` params to Podcast Generator `voice_io.notify()`, SWE Team `cosa_interface.notify_progress()`, orchestrator `_notify()`, and hooks `notification_hook()`
- Phase 2 (Podcast Generator): Wired per-language group ID into audio generation loop (start/stitch/complete) + TTS milestone callback (`_audio_progress_callback`) — collapses 10+ cards into 1 per language
- Phase 3 (Deep Research): Wired single `research_group_id` across subquery loop (3 notify calls) — collapses 6-20 cards into 1
- Phase 4 (SWE Team): Wired 5 separate group IDs — delegation loop, coder SDK stream, tester SDK stream, verification cycle, re-delegation stream
- Full regression: 1343 unit tests pass, 0 failures

**Files**: voice_io.py (PG), cosa_interface.py (SWE), orchestrator.py (SWE+PG), hooks.py (SWE), cli.py (DR)
**Commit**: d635876 (Lupin), 178dfaf (CoSA)

#### Checkpoint 2 | 2026.02.17 | Add 41 unit tests for progress_group_id passthrough

**Accomplishments**:
- Added `test_progress_group_passthrough.py` with 41 tests covering all 6 modified files
- Phase 1 tests: Mock-based passthrough verification (voice_io, cosa_interface, orchestrator._notify, hooks)
- Phase 2-4 tests: Source inspection verification (group ID generation + wiring in all loops)
- Cross-cutting: pg-{8hex} format validation (valid/invalid/fuzz with 100 random UUIDs)
- Full regression: 1384 unit tests pass (1343 + 41 new), 0 failures

**Files**: src/tests/unit/test_progress_group_passthrough.py
**Commit**: 1bb8cda

---

### 2026.02.17 - Session 219 | Fix Factory ValueError on Non-Numeric Args (SWE Team Proxy)

**Accomplishments**:
- Fixed HTTP 500 crash: `ValueError: invalid literal for int() with base 10: 'default'` in `agentic_job_factory.py`
- Added `_SEMANTIC_NONE` set + `_parse_optional_int()`/`_parse_optional_float()` safe parsing helpers (Layer 1: factory)
- Replaced 6 raw `int()`/`float()` casts across all 5 agentic job types (deep research, podcast, research-to-podcast, claude code, swe team)
- Added `"timeout"` + `"default"` to expeditor skip guards at both batch and single paths (Layer 2: belt-and-suspenders)
- Full regression: 1343 unit tests pass, 0 failures

**Files Modified**: `src/cosa/rest/agentic_job_factory.py`, `src/cosa/agents/runtime_argument_expeditor/expeditor.py`

---

### 2026.02.16 - Session 218 | SWE Team Surface 3 Proxy Integration + Phase 4 Gap-Fill Tests

**Accomplishments**:
- Phase 4c/4e gap-filling: 87 new unit tests across trust_tracker, circuit_breaker, engineering_decisions (1265 total)
- Surface 2A: SWE Team Job class, factory registration, FastAPI router (22 tests, 1319 total)
- Surface 2B: Mock endpoint scenarios — 6/6 pass (dry_run, agent_type, cost, timestamps, missing/empty task)
- Surface 3: Registered SWE Team in AGENTIC_AGENTS (5th agent), added `--user-visible-args` to CLI, created Q&A proxy script `swe-team-test.json`, created `test_swe_team_proxy.py` (3 scenarios)
- Added SWE Team to PRODUCT_NAMES + `swe_team` profile to notification proxy config
- Full regression: 1343 unit tests pass, 0 failures
- **Blocker**: Proxy startup crash — two bugs identified: (1) truncated ImportError in llm_script_matcher import chain, (2) profile name mismatch (`swe_team_test` not in TEST_PROFILES choices). Deferred to tomorrow.

**Files Modified**: agent_registry.py, swe_team/__main__.py, todo_fifo_queue.py, notification_proxy/config.py, test_runtime_argument_expeditor.py, 03-testing-validation.md, swe-team-test.json (new), test_swe_team_proxy.py (new)
**Checkpoints**: d5f5e24 (Phase 4 tests), f5311c4 (Surface 3 infrastructure)
**Note**: CoSA submodule changes (4 files) need separate commit

---

### 2026.02.16 - Session 217 | Document progress_group_id in Notification API Docs

**Accomplishments**:
- Documented `progress_group_id` parameter across all 5 relevant sections of `notification-api.md` (query params, AsyncNotificationRequest, to_api_params, NotificationItem, WebSocket payload)
- Added `progress_group_id` to MCP tool docstring in `cosa_voice_mcp.py`
- Feature was fully implemented but undocumented — this closes the documentation gap

**Files Modified**: `src/docs/notification-api.md` (+5 insertions), `src/lupin_mcp/cosa_voice_mcp.py` (+3 lines)
**Commit**: 51b3bff

---

### 2026.02.16 - Session 216 | PEFT Resume OOM Documentation (WILL NOT FIX)

**Accomplishments**:
- Documented PEFT trainer resume-path OOM as WILL NOT FIX (intractable — PyTorch CUDA allocator internals)
- Added known-issue comment block in `peft_trainer.py` resume branch (CoSA submodule, pending separate commit)
- R&D analysis already committed in Session 214 checkpoint: `src/rnd/2026.02.16-peft-resume-oom-cold-allocator-analysis.md`
- Root cause: cold allocator creates monolithic ~16 GB segment; ~62 MB residual pins it after cleanup; vLLM subprocess OOMs on GPU 0
- Updated CoSA submodule commit backlog in TODO.md

**Files Modified**: TODO.md, history.md (CoSA: training/peft_trainer.py pending)

---

#### Checkpoint | 2026.02.16 19:30 | Simplify semantic match to top-1 + confirm strategy

**Files**: lupin-app.ini, lupin-app-splainer.ini, lancedb_solution_manager.py, todo_fifo_queue.py, file_based_solution_manager.py

- Removed hard threshold floor (95%) that silently discarded vector matches below cutoff
- New 3-tier decision: 100% auto-accept, >=90% ask user, <90% log and skip to LLM
- Commented out L3 gist match block in LanceDB manager (gist text retained for display/logging)
- Removed threshold filter from L4 vector search — all results returned to caller
- Restructured `push_job()` decision logic from 2-branch (above/below confirmation) to 3-tier
- Lowered `similarity_threshold_confirmation` from 98.0% to 90.0% (new ask floor)
- Mirrored changes in file_based_solution_manager.py for backend parity
- 1265 unit tests pass, 0 failures
- **Note**: CoSA submodule changes (3 files) need separate commit

---

#### Checkpoint | 2026.02.16 18:30 | Add answer_is_correct to solution snapshots with async verification

**Files**: solution_snapshot.py, lancedb_solution_manager.py, running_fifo_queue.py, test_answer_is_correct.py (new)
**Commit**: dbb3b20

- Added `answer_is_correct` tri-state field (True/False/None) to SolutionSnapshot constructor and LanceDB schema
- Created `_fire_correctness_check_async()` in RunningFifoQueue — non-blocking daemon thread sends yes/no notification after agent completion, persists response to LanceDB
- Cache hits inherit stored `answer_is_correct` value (no re-asking)
- Added `answer_is_correct` to WebSocket metadata in all 3 completion paths (base agent, snapshot, cached)
- Dropped and recreated LanceDB `solution_snapshots` table for schema migration
- 12 new unit tests (field defaults, for_current_user/get_copy preservation, LanceDB round-trip for all 3 states)
- Full regression: 1331 unit tests pass, 0 failures
- **Note**: CoSA submodule changes (3 files) need separate commit

---

#### Checkpoint | 2026.02.16 16:00 | SWE Team notification gap analysis implementation

**Files**: orchestrator.py, config.py, state_files.py, cosa_interface.py, voice_io.py, test_swe_team_orchestrator.py

- Implemented 3-tier SWE Team Notification Gap Analysis plan (20 gaps addressed)
- **Tier 1a**: Added 6 missing progress notifications (verification pass/fail, delegation errors, rich completion abstract)
- **Tier 1b**: Added escalation `request_decision()` after max verification retries with 3 options
- **Tier 2a**: Added `job_id` passthrough + `_notify()` helper for CJ Flow readiness
- **Tier 2b**: Added `state["artifacts"]` dict for CJ Flow-compatible output
- **Tier 1c**: Added `ResultMessage` forwarding through `notification_hook` in 3 SDK loops
- **Tier 2c**: Added `_emit_state()` callback at 8 state transitions for WebSocket visibility
- **Tier 3a**: Added contract documentation to cosa_interface.py and voice_io.py
- **Tier 3b**: Wired decision proxy via `_gated_confirmation()` adapter (trust_mode: disabled/shadow/suggest/active)
- **Tier 3c**: Added `on_log` callback to ProgressLog, wired to notifications when `narrate_progress=True`
- Created 32 new unit tests in `test_swe_team_orchestrator.py`; 183 SWE team tests pass, 0 failures
- **Note**: CoSA submodule changes (5 files) need separate commit

---

#### Checkpoint | 2026.02.16 14:30 | Phase 4c/4e gap-filling unit tests

**Files**: test_trust_tracker.py, test_circuit_breaker.py, test_engineering_decisions.py (+1 more)
**Commit**: d5f5e24

- Created 87 new gap-filling unit tests across 3 files for SWE Team Decision Proxy
- `test_trust_tracker.py` (28 tests): L3-L5 graduation, intermediate demotion, rolling window, decay, serialization
- `test_circuit_breaker.py` (27 tests): min-sample gate, confidence boundary, trip demotion, cooldown, callbacks
- `test_engineering_decisions.py` (32 tests): keyword validation, cap constants, confidence formula, trust buildup
- Updated `03-testing-validation.md` with Phase 4 results and regression tracking
- Full regression: 1265 unit tests pass, 0 failures (was 1178)

---

### 2026.02.16 - Session 214 | Bug Fix Mode

**Accomplishments**:
- Verified and closed 4 pre-existing bug fix queue items (3 queued + 1 orphaned in-progress)
- Verified semantic-similarity confirmation is fully configurable at runtime via `similarity_confirmation_enabled` config key, REST toggle endpoint, and runtime check in `todo_fifo_queue.py` — moved from In Progress to Completed
- Verified Cache N/A bug fix: code fallback changed from `"N/A"` to `[ "" ]`, empty-code guard in `run_code()`, `try/except ValueError` in caller — moved to Completed
- Verified CRUD test fixes (`test_crud_agent_emits_job_state_transition`, `test_crud_agent_pushed_to_done_queue`): 3 MagicMock lines added — both tests now pass
- Full unit test suite: 1170 tests pass, zero regressions

**Files Modified**:
- `bug-fix-queue.md` (queue cleanup: 3 queued → completed, 1 in-progress → completed)

---

*Earlier sessions archived — see navigation links below.*

## Navigation

### Archive Links
- **[Feb 10-14, 2026](history/2026-02-10-to-14-history.md)** - Sessions 171-213: Notification Proxy Agent, SWE Team Phases 2-4, Calculator completion, CRUD bug fixes, Unified Smoke Test Framework, PEFT Resume OOM analysis
- **[Feb 3-10, 2026](history/2026-02-03-to-10-history.md)** - Sessions 126-180: DataFrame CRUD Phases 1-3, Runtime Argument Expeditor, PEFT Phase 2, Notification Proxy Agent, Calculator Mock Pipeline, Yes/No Comment Feature, Agentic Voice Workflow v2.0
- **[Jan 19 - Feb 2, 2026](history/2026-01-19-to-02-02-history.md)** - Sessions 57-124: Podcast Generator Phase 2, Deep Research CLI UX, LORA Training Integration, Test Suite Remediation, Cache Freshness, Queue Protocol Refactoring
- **[Jan 13-19, 2026](history/2026-01-13-to-19-history.md)** - Sessions 56-74b: Conversation Identity, Deep Research Agent, Podcast Generator Phase 1, Job Queue Progressive Disclosure UI
- **[Nov 23, 2025 - Jan 12, 2026](history/2025-11-23-to-2026-01-12-history.md)** - Sessions 7-55: MCP Voice, Directory Rename, Claude Code Dispatcher
- **[Oct 16 - Nov 22, 2025](history/2025-10-16-to-11-22-history.md)** - Sessions 1-6: Admin Dashboard, LanceDB, PostgreSQL Migration
- **[Oct 16-30, 2025](history/2025-10-16-to-30-history.md)** - SSE Notification System Phase 2
- **[Oct 1-15, 2025](history/2025-10-01-to-15-history.md)** - JWT/OAuth, User Filtering
- **[Sep 3-23, 2025](history/2025-09-03-to-23-history.md)** - History Management, WebSocket Architecture
- **[August 2025](history/2025-08-history.md)** - TTS Streaming, Audio Pipeline, WebSocket Enhancements
- **[July 2025](history/2025-07-history.md)** - Progressive TTS, User Routing Architecture
- **[June 2025](history/2025-06-history.md)** - Lupin Renaming, Notification System Foundation
- **[May 2025 and Earlier](history/2025-05-and-earlier-history.md)** - PEFT Training, Agent Migrations, Flask to FastAPI
- **[Archive Index](history/README.md)** - Full archive listing with descriptions

### Implementation Documents
- **Current Focus**: SWE Team Notification Gap Analysis + CJ Flow Integration
- **SWE Team Design**: `src/rnd/2026.02.13-claude-code-agentic-dev-team/`
- **Decision Proxy**: `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture.md`

### Quick Navigation
- **Run FastAPI server**: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- **Run GUI client**: `src/scripts/run-lupin-gui.sh`
- **Integration tests**: `./src/tests/run-integration-tests.sh -v`
- **Smoke tests**: `src/scripts/run-websocket-smoke-tests.sh`
