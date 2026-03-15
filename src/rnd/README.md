# R&D Documentation Index

This directory contains research and development documents for the Lupin project.

## Recent Additions

### 2026.03.14 - Presentation Generator Agent
- **R&D Directory**: [2026.03.14-presentation-generator/](2026.03.14-presentation-generator/00-index.md) - Agentic process (Claude SDK) that transforms research documents or technical blog posts into 10-20 minute slide decks with presenter notes. Single orchestrator pattern (like Podcast Generator). 8-phase pipeline: ingest, analyze narrative, outline titles+visuals, elaborate content+notes, serialize YAML, render Marp Markdown, render Mermaid visuals, deliver. 4 human-in-the-loop gates. Pluggable visual renderer registry for future AI generators. Theme cascade: INI -> YAML template -> per-presentation overrides.
  - [Strategy & Design](2026.03.14-presentation-generator/01-strategy-and-design.md) | [Implementation Plan](2026.03.14-presentation-generator/02-implementation-plan.md) | [Tracking](2026.03.14-presentation-generator/03-implementation-tracking.md)

### 2026.03.14 - Claude Agent SDK Config Migration Plan (Revised)
- **Plan**: [2026.03.14-claude-agent-sdk-config-migration-plan.md](2026.03.14-claude-agent-sdk-config-migration-plan.md) - Revised plan for migrating Deep Research, Podcast Generator, and LLM Client Factory configs from hardcoded `@dataclass` to COSA ConfigurationManager (INI + env var overrides). No backward compatibility — `from_config()` is the only path. Supersedes 2026.01.27 plan. 5 phases: INI key prep, Deep Research, Podcast Generator, LLM Client Factory, testing.

### 2026.03.13 - CJ Flow Persistence Plan
- **Plan**: [2026.03.13-cj-flow-persistence-plan.md](2026.03.13-cj-flow-persistence-plan.md) - Durable PostgreSQL-backed persistence for AgenticJobBase jobs (DeepResearch, PodcastGenerator, ClaudeCode, SweTeam). Central write-through via `emit_job_state_transition()`, job_history table with JSONB metadata, startup recovery marking interrupted jobs, `/api/job-history` endpoint with role-based auth. 5 phases: schema+model, persistence service, write-through integration, startup recovery, API+tests.

### 2026.03.12 - TTS Focus Mode Race Condition Analysis
- **Analysis**: [2026.03.12-tts-focus-mode-race-condition-analysis.md](2026.03.12-tts-focus-mode-race-condition-analysis.md) - Execution path analysis of TTS state after action-required notification completion. Documents three paths (A: audio finishes before user answers, B: user answers while audio plays, C: dismiss/cancel) and identifies race condition where `onended` handler enters focus mode for an already-responded notification, permanently freezing the TTS queue.

### 2026.03.12 - Integration Test Remediation & DB Disambiguation
- **Plan**: [2026.03.12-integration-test-remediation-and-db-disambiguation.md](2026.03.12-integration-test-remediation-and-db-disambiguation.md) - 8-step plan: run & triage ~26 integration test failures (stubs, LanceDB normalization, external deps), fix 1 WebSocket failure, then rename `lupin_db` → `lupin_db_dev`/`lupin_db_prod` (67 references across 12 files), full test suite re-run.

### 2026.03.12 - Integration Test Hot-Swap Config
- **Plan + Implementation**: [2026.03.12-integration-test-hot-swap-config.md](2026.03.12-integration-test-hot-swap-config.md) - Hot-swap the running dev server between Development and Testing config blocks via `/api/init` + `swap_database()`. Eliminates need for separate test server (GPU RAM constraint). 6 phases: server-info endpoint, swap_database() function, /api/init config_block_id param, integration runner rewrite, smoke test validation, WebSocket guard. Phases 1-5 complete, Phase 6 (DB name disambiguation) deferred.

### 2026.03.11 - Integration Test Isolation Audit & Remediation Plan
- **Audit**: [2026.03.11-integration-test-isolation-audit.md](2026.03.11-integration-test-isolation-audit.md) - Comprehensive audit of test tier architecture and database isolation gaps. Integration tests fail with "Email already registered" due to configuration boundary gap: dev-server tests and test-server tests share port 7999 with no config validation or database boundary checks. 5-phase remediation plan: server-info endpoint, pre-flight validation, post-startup verification, WebSocket guard, clean_test_db hardening.

### 2026.03.11 - Baseline Test Report
- **Report**: [2026.03.11-baseline-test-report.md](2026.03.11-baseline-test-report.md) - Comprehensive baseline test results across all 5 test tiers before remediation.

### 2026.03.11 - Universal Prediction Engine: Live E2E Validation Plan
- **Plan**: [2026.03.11-upe-live-e2e-validation-plan.md](2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md) - Comprehensive live validation of all 7 UPE slices against running FastAPI server. 5 phases: baseline (87 unit + 21 E2E tests), warm prediction threshold investigation, 6 new gap-filling E2E tests, browser visual QA for prediction hint rendering, and full cold-to-warm lifecycle validation with accuracy tracking.

### 2026.03.05 - Voice Injection: Listener + tmux + UserPromptSubmit Hook Plan
- **Plan**: [2026.03.05-voice-injection-listener-tmux-hook-plan.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.05-voice-injection-listener-tmux-hook-plan.md) - Implementation plan for direct voice injection into idle Claude Code sessions. Reuses existing notification -> listener -> JSONL buffer pipeline, adds tmux session discovery in register_session.py, tmux Enter trigger in CCNotificationListener after buffering, and new UserPromptSubmit hook that drains buffer and injects as additionalContext. 6 phases, 10 files (3 new, 7 modified), ~24 unit tests + E2E smoke test.

### 2026.03.02 - Slice 6: Prediction Hint UI Rendering
- **Plan**: [2026.03.02-slice-6-prediction-hint-ui-rendering.md](2026.02.23-trust-proxy-preference-learning/2026.03.02-slice-6-prediction-hint-ui-rendering.md) - Render prediction hints inside response-required notification cards in the browser. Adds `buildPredictionHintSection()` and `formatStrategyLabel()` to `notifications.js`, injects hint between abstract and progress bar, purple-themed CSS styling. Zero Python changes — purely frontend. Closes the "full stack per type" architecture gap.

### 2026.03.02 - Slices 4+5: Open-Ended and Open-Ended Batch Prediction
- **Plan**: [2026.03.02-slices-4-5-open-ended-prediction.md](2026.02.23-trust-proxy-preference-learning/2026.03.02-slices-4-5-open-ended-prediction.md) - Two-tier prediction for free-text responses: exact match retrieval (CBR) + LLM synthesis (Phi-4 14B). Covers both `open_ended` (from `converse()`) and `open_ended_batch` (from `ask_open_ended_batch()`). New XML model, prompt template, upgraded accuracy comparators with embedding cosine similarity. ~36 unit tests + 6 E2E tests.

### 2026.03.02 - Slice 3: Multi-Select Multiple Choice Prediction
- **Plan**: [2026.03.02-slice-3-multi-select-mc-prediction.md](2026.03.02-slice-3-multi-select-mc-prediction.md) - Extending PredictionEngine to handle `multiSelect: true` from cosa-voice `ask_multiple_choice()`. Fixes TypeError on list-as-dict-key in vote tallying, adds data-driven comparator dispatch, ~10 unit tests + 2 warm E2E tests.

### 2026.03.02 - Voice Hook Integration: Status Summary & Testing Plan
- **Status**: [2026.03.02-status-summary-and-testing-plan.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.02-status-summary-and-testing-plan.md) - Phase 7 (E2E Testing + Polish) status summary. 6 of 7 phases complete, 126 hook unit tests + ~430 total tests. Covers test inventory, E2E gap analysis (10 scenarios), pre-merge gate requirements, and CLI simulation commands for voice pipeline testing.

### 2026.02.28 - Design Doc Revisions: Voice I/O Phase 1 (Session 290)
- **Revisions**: [2026.02.28-design-doc-revisions-session-290.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.28-design-doc-revisions-session-290.md) - Four architectural revisions to the voice hook integration master plan before Phase 1 implementation. (1) No new VOICE_INPUT type — reuses existing `user_initiated_message`. (2) Simplified sender ID — user's email, no fancy convention. (3) Stateful WebSocket listener replaces ephemeral DB queries — `CCNotificationListener` subclasses `BaseWebSocketListener`, buffers to JSONL, atomic drain. (4) Phase 1 simplified to 7 steps. New components: credentials INI infrastructure, CC Notification Listener, SessionEnd hook, 35 automated tests.

### 2026.02.27 - Bug Fix: target_user Notification Dispatch (IN PROGRESS)
- **Plan**: [2026.02.27-target-user-notification-dispatch-bug-fix.md](2026.02.27-target-user-notification-dispatch-bug-fix.md) - Investigation and partial fix for "Cannot resolve target_user" errors during podcast generator job execution. Session 283 implemented target_user plumbing through 7 files (dispatcher, 4 cosa_interfaces, 2 jobs). Error persists after server restart — investigation traced full 13-step call chain from API submission through Docker-isolated execution. Key finding: Docker container doesn't inherit host env vars (LUPIN_DEV_EMAIL) or config files (~/.notifications/config). Next step: test-first approach to reproduce and verify fix.

### 2026.02.28 - Phase 0 Validation Report: Hook Contract Validation
- **Report**: [2026.02.27-phase-0-validation-report.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.27-phase-0-validation-report.md) - Empirical validation of all 5 hook types from 3,430 captured payloads over ~22.5 hours. Documents JSON schemas per hook type (PreToolUse, PostToolUse, Stop, Notification, SessionStart), validates 12 research claims (all PASS), identifies 7 surprises/deviations (model field in SessionStart, source field, MCP response type difference, pre/post count delta). Tool usage frequency analysis (Read 35.5%, Bash 22.1%, Edit 8.2%). Session bridge file verification (26 files created). Phase 0 gate: 12/12 checks passed.

### 2026.02.27 - Universal Decision Proxy: Multi-Response-Type Prediction Engine
- **Plan**: [2026.02.27-universal-prediction-engine-plan.md](2026.02.23-trust-proxy-preference-learning/2026.02.27-universal-prediction-engine-plan.md) - Approved implementation plan for extending the trust proxy system to handle ALL notification response types (yes_no, multiple_choice, open_ended, open_ended_batch) with prediction hints, accuracy tracking, and progressive learning. Vertical slice architecture: Slice 0 (foundation infrastructure — PredictionEngine singleton, prediction_log table, NotificationCategoryClassifier with 6 fixed categories), Slice 1 (yes_no simple binary via CBR majority vote), future slices for qualified yes_no, multiple_choice variants, and open_ended. Reuses CBRDecisionStore, ProxyDecisionEmbeddings, CategoryClassifier ABC, and EmbeddingProvider. Performance budget: 15-40ms total prediction latency. Progressive learning timeline from cold start (day 1) to autonomous responses (day 30+). SWE team decision proxy becomes a future consumer of the same engine.

### 2026.02.26 - Voice Hook Phase 0 Implementation
- **Plan**: [2026.02.26-voice-hook-phase-0-implementation.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.26-voice-hook-phase-0-implementation.md) - Phase 0 execution plan: 5 test hooks (SessionStart, PostToolUse, PreToolUse, Stop, Notification), shared `hook_common.py` library with TTS via `lupin_cli.notifications`, PPID-based session bridge (`session_bridge.py`), and hook registration in `settings.local.json`. Validates research claims empirically. Review decisions: AD-5 all boundaries drain, AD-6 PPID session bridge, AD-2 `lupin_cli.notifications` package.

### 2026.02.25 - Voice I/O Integration with Claude Code System Hooks
- **Directory**: [2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/) - Research + implementation plan for full bidirectional voice loop via Claude Code's 18 system hook events. Opportunistic voice drain architecture: speech captured between tool calls, accumulated in existing notification API as `VOICE_INPUT` type, drained at hook boundaries (PostToolUse primary, Stop secondary) and injected as `additionalContext`. Voice-driven approvals via PermissionRequest hook. 8 implementation phases over 6-8 weeks.
  - **Research**: [2026.02.25-voice-io-integration-with-cc-system-hooks-research.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.25-voice-io-integration-with-cc-system-hooks-research.md) - Complete I/O contract reference for all 18 hook events: exit codes, JSON schemas, blocking semantics, injection surfaces.
  - **Plan**: [2026.02.25-opportunistic-voice-hook-integration-plan.md](2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.25-opportunistic-voice-hook-integration-plan.md) - Hook-by-hook suitability matrix (3 tiers), data flow diagrams, 7 architecture decisions, risk assessment, file organization, verification gates.

### 2026.02.27 - End-to-End Trust Proxy Conceptual Overview
- **Overview**: [2026.02.27-end-to-end-trust-proxy-overview.md](2026.02.23-trust-proxy-preference-learning/2026.02.27-end-to-end-trust-proxy-overview.md) - End-to-end conceptual walkthrough of the decision proxy system: from cold start with seed data, through shadow mode data collection, to autonomous predictions via CBR engine. Traces the full data flow across all 5 stages (bootstrap, shadow, provisional, trusted, autonomous), explains the three trust models (count-based, Beta-Bernoulli, BLR), the morning coffee ratification workflow, safety mechanisms (circuit breaker, category caps, time-weighted decay), and the flywheel effect. Component map covering FastAPI server, CJ Flow, WebSocket events, decision proxy agent, PostgreSQL, and LanceDB. Quick-start checklist and complete key files reference.

### 2026.02.25 - SWE Proxy: Data Origin Tracking + Workload Generator
- **Implementation Plan**: [2026.02.25-swe-proxy-data-origin-and-workload-generator.md](2026.02.25-swe-proxy-data-origin-and-workload-generator.md) - **✅ IMPLEMENTED (Session 268)** - Two work items: (1) `data_origin` column added to PostgreSQL + LanceDB proxy decision stores for provenance tracking (`organic`, `synthetic_seed`, `synthetic_generated`), with migration, backfill of 50 seed rows, repository layer updates, and 14 new unit tests. (2) Workload generator + capture harness: 18-task catalog across 6 engineering categories, enhanced dry-run using real `EngineeringClassifier` pipeline (6 phase-specific questions per run), `swe_workload_runner.py` capture harness with JSONL manifest output, and 7 new integration tests validating CJ Flow lifecycle + proxy decision correctness. Total: 1659 tests passing (+14 new).

### 2026.02.25 - UNBOUNDED vs SWE Team Comparative Analysis
- **Research**: [2026.02.25-unbounded-vs-swe-team-comparative-analysis.md](2026.02.25-unbounded-vs-swe-team-comparative-analysis.md) - Rigorous comparative analysis of CJ Flow's two autonomous coding architectures: UNBOUNDED (Interactive Claude Code with human-in-the-loop) vs SWE Team (Bounded multi-agent with trust proxy). Covers autonomy spectrum, when-to-use decision matrix, community research application ("Five Laws", Ralph Loop, Cursor's lessons), state management comparison, and identifies the UNBOUNDED dry-run testing gap. Grounded against actual codebase with verified line counts and file references.

### 2026.02.24 - Preference Learning Seed Data Generator
- **Plan + Script**: [2026.02.23-trust-proxy-preference-learning/2026.02.24-preference-learning-seed-data-plan.md](2026.02.23-trust-proxy-preference-learning/2026.02.24-preference-learning-seed-data-plan.md) - **IMPLEMENTED** - Self-contained bootstrap script (`src/scripts/seed_proxy_decisions.py`) that populates 50 realistic decision scenarios across all 6 engineering categories into PostgreSQL + LanceDB, then batch-ratifies them to create training signal for the CBR engine. Includes CLI modes: `--dry-run`, `--ratify`, `--verify`, `--clean`, `--category`. Designed for reuse across all 4 preference learning phases (0-3). Required step for bootstrapping the preference learning system in any new environment.

### 2026.02.24 - Phase 2 Implementation Plan: BLR + Thompson Sampling
- **Implementation Plan**: [2026.02.23-trust-proxy-preference-learning/2026.02.24-phase-2-blr-thompson-sampling-plan.md](2026.02.23-trust-proxy-preference-learning/2026.02.24-phase-2-blr-thompson-sampling-plan.md) - **PLANNED** - Phase 2 of the preference learning system (30-100 observations, ~3-5 days). Three components: (A) BLR upgrade replacing Beta-Bernoulli with Laplace-approximated Bayesian Logistic Regression using 4-feature vectors (category, question length, time of day, recent error rate), ~150-200 lines of numpy/scipy. (D) Thompson Sampling gate replacing fixed trust-level thresholds with probabilistic Beta posterior sampling for natural exploration-exploitation. (E) Optional GP/BALD active query selection for maximizing learning value of human interactions, ~200-300 lines. 5 new config keys (`swe team trust proxy thompson enabled/act threshold/suggest threshold`, `bald enabled/defer threshold`). 2 new files + 3 test files. Target: ~40-60% autonomous decisions.

### 2026.02.24 - Phase 3 Implementation Plan: Conformal Guarantees + Optional ICRL
- **Implementation Plan**: [2026.02.23-trust-proxy-preference-learning/2026.02.24-phase-3-conformal-icrl-plan.md](2026.02.23-trust-proxy-preference-learning/2026.02.24-phase-3-conformal-icrl-plan.md) - **PLANNED** - Phase 3 of the preference learning system (100+ observations, ~3-5 days). Two components: Conformal prediction wrapper (~50-80 lines) providing distribution-free coverage guarantees via prediction sets ({approve}, {reject}, or {approve, reject}), using MAPIE library (only new dependency). Optional ICRL prompt augmentation (~60-80 lines) for LLM-based disambiguation of ambiguous CBR cases with mixed verdicts, adding ~500ms-2s latency only for ~5-15% of genuinely ambiguous decisions. 3 new config keys (`conformal enabled`, `icrl enabled/top k`). Target: ~80-95% autonomous decisions.

### 2026.02.24 - Voice Module Deduplication Plan (Implemented)
- **Plan**: [2026.02.24-voice-module-deduplication-plan.md](2026.02.24-voice-module-deduplication-plan.md) - **IMPLEMENTED (Session 260)** - 5-phase refactoring plan for voice/notification module deduplication. Created shared `AgentNotificationDispatcher`, `sender_id.py`, `feedback_analysis.py`, `sync_notify.py`. Eliminated ~1,548 lines of copy-paste duplication across 16 files (12 CoSA + 2 Lupin + 4 new). All 1538 unit tests pass.

### 2026.02.23 - INI Config Key Naming Convention — Design Document
- **Design Document**: [2026.02.23-ini-config-key-naming-convention.md](2026.02.23-ini-config-key-naming-convention.md) - **📋 PLANNED (v0.1.6)** - Comprehensive design document for standardizing all ~98 underscore-separated INI config keys to space-separated format. Current state: 44% underscore / 56% space across ~195 keys. Migration affects ~80 files (18 Lupin + 62 CoSA). 6-phase plan: backward-compat shim in ConfigurationManager, INI file renames, Lupin code updates, CoSA code updates (separate repo), shim removal + guardrail test, final regression. Includes complete key inventory with proposed names, collision-safe longest-match-first replacement strategy, and rollback plan. Estimated ~2 weeks implementation.

### 2026.02.24 - Decision Proxy Preference Learning — Take III Synthesis
- **Synthesis Document**: [2026.02.23-trust-proxy-preference-learning/2026.02.24-decision-proxy-preference-learning-analysis-take-III-synthesis.md](2026.02.23-trust-proxy-preference-learning/2026.02.24-decision-proxy-preference-learning-analysis-take-III-synthesis.md) - **RESEARCH COMPLETE** - Unified synthesis of Take I (codebase-grounded gap analysis, 4 upgrade paths) and Take II (algorithm-focused research, 3 contenders, 18 citations). Key synthesis decisions: CBR replaces ICRL as primary preference backbone (works from day zero), GP/BALD added for data-efficient active learning, observation-count phases replace dependency-only phases, Beta-Bernoulli and BLR are sequential not competing. 6-component architecture: Bayesian Trust Scoring, Embedding-Based Decision Recall, CBR with Bayesian Confidence, Thompson Sampling for act/defer routing, GP/BALD active learning, optional ICRL for ambiguous cases. Cold-start-aware 4-phase deployment (0→1-30→30-100→100+ observations), ~10-15 days total effort, critical path ~7-10 days. 32 consolidated references. Deferral reframed as information-gathering mechanism.

### 2026.02.23 - Decision Proxy Preference Learning — Gap Analysis & Upgrade Paths
- **R&D Analysis (Take I)**: [2026.02.23-trust-proxy-preference-learning/2026.02.23-decision-proxy-preference-learning-analysis-take-I.md](2026.02.23-trust-proxy-preference-learning/2026.02.23-decision-proxy-preference-learning-analysis-take-I.md) - **RESEARCH COMPLETE** - Audit of the decision proxy's current graduated autonomy scaffold (SAE J3016 L1-L5 pattern, circuit breaker, shadow mode) revealing a key gap: the system learns *whether to act* but not *which answers humans prefer*. 7-stage feedback loop trace with exact file/line references. Four high-priority upgrade paths: (1) Bayesian Beta-Bernoulli trust replacing counter thresholds (~1 day), (2) LanceDB embedding-based decision recall replacing ILIKE substring matching (~2 days), (3) In-Context Reinforcement Learning (Song et al. 2025) — the core preference learning breakthrough via prompt augmentation (~2-3 days), (4) Thompson Sampling for probabilistic exploration-exploitation gating (~3-5 days). All compatible with API-based LLMs (no fine-tuning). Phased roadmap: A+B parallel → C → D, critical path ~4-5 days. Includes rejected alternatives (RLHF, DPO, IDA, CAI) with rationale.
- **R&D Analysis (Take II)**: [2026.02.23-trust-proxy-preference-learning/2026.02.23-decision-proxy-preference-learning-analysis-take-II.md](2026.02.23-trust-proxy-preference-learning/2026.02.23-decision-proxy-preference-learning-analysis-take-II.md) - **RESEARCH COMPLETE** - Algorithm-focused research analyzing 3 preference learning contenders: (1) Bayesian online logistic regression with Thompson Sampling (simplest principled, 10-30 examples), (2) GP preference learning with BALD active querying (most data-efficient, 2-5 examples), (3) Case-based reasoning with Bayesian confidence (works from day zero, maximally interpretable). 18 academic citations. Cold-start-aware phased deployment (0→1-30→30-100→100+ observations). Key insight: deferral is an information-gathering mechanism, not failure. Supplementary approaches: Contextual TS, conformal prediction, Bayesian Bradley-Terry, learning-to-defer.

### 2026.02.23 - Playwright E2E Testing: Planning & Design Documents
- **Planning Hub**: [2026.02.23-automating-ui-testing/00-index.md](2026.02.23-automating-ui-testing/00-index.md) - **📋 PLANNED (v0.1.6)** - Comprehensive planning documents for Playwright Python E2E browser testing. 8-phase implementation plan (~78 tasks, ~5 weeks), 9 architecture decisions, complete data-testid inventory (189 elements across 12 pages + nav), 28 test journey specs covering auth, admin, notifications, WebSocket, and visual regression. Foundation research recommends Playwright Python + pytest-playwright for FastAPI + vanilla HTML/JS stack. Round 2 adds Claude Code + Playwright MCP for AI-augmented test generation and self-healing selectors. Serialized plan: [2026.02.23-playwright-e2e-testing-plan.md](2026.02.23-playwright-e2e-testing-plan.md).
- **Research Foundation**: [2026.02.23-automating-ui-testing/2026.02.23-automating-ui-testing-research.md](2026.02.23-automating-ui-testing/2026.02.23-automating-ui-testing-research.md) - **RESEARCH COMPLETE** - Tool evaluation: Playwright vs Selenium vs Cypress vs browser-use. Community consensus, framework comparison matrix, AI augmentation landscape.

### 2026.02.19 - Approach C: Hybrid Fast Lane + Bounded Agentic Pool for CJ Flow
- **Implementation Plan**: [2026.02.19-approach-c-hybrid-queue-architecture.md](2026.02.19-approach-c-hybrid-queue-architecture.md) - **🔄 IN PROGRESS** - Hybrid architecture for CJ Flow concurrent job processing. Consumer thread becomes a dispatcher: sync agents (MathAgent, CalendarAgent, etc.) process inline via fast lane, while agentic jobs (DeepResearch, Podcast, ClaudeCode) submit to a bounded `ThreadPoolExecutor` (configurable N workers). Eliminates head-of-line blocking where 10-minute DeepResearchJobs block 2-second MathAgent queries. Phase 1: RLock on FifoQueue for thread safety. Phase 2: Pool + dispatcher refactor in RunningFifoQueue with `delete_by_id_hash()` replacing `pop()` for concurrent removal. Phase 3: API monitoring endpoint + E2E verification. No protocol changes, no agentic job internal changes. Serialized from plan `sprightly-juggling-origami.md`.

### 2026.02.18 - Approach D: Hybrid Queue + Check-In for User-Initiated Communication
- **Implementation Plan**: [2026.02.18-approach-d-hybrid-queue-checkin.md](2026.02.18-approach-d-hybrid-queue-checkin.md) - **📋 PLANNED** - User-initiated communication with running SWE Team jobs. Decouples message submission (anytime via WebSocket fire-and-forget) from message consumption (at check-in points). Three components: `threading.Queue` on orchestrator, `user_message_to_job` WebSocket inbound event, LLM-powered drain logic where lead model analyzes accumulated messages and asks yes/no confirmation before incorporating. Builds on Approach B (periodic check-ins, already implemented). 5 files, ~170 lines. Parent design doc: `src/rnd/2026.02.13-claude-code-agentic-dev-team/05-user-initiated-communication.md`. Serialized from plan `agile-kindling-tide.md`.

### 2026.02.16 - PEFT Resume-Path OOM: Cold Allocator Root Cause Analysis
- **Root Cause Analysis**: [2026.02.16-peft-resume-oom-cold-allocator-analysis.md](2026.02.16-peft-resume-oom-cold-allocator-analysis.md) - **🚫 WILL NOT FIX** - `--resume-from-merged` + `--post-quantization-stats` causes vLLM OOM after 8-bit quantization. Two-factor root cause: (1) Cold CUDA caching allocator creates monolithic ~16 GB segment; ~62 MB residual pins entire segment after cleanup. (2) vLLM subprocess can't access parent's reserved memory, sees only ~10 GB free on GPU 0. Happy path avoids this via mature allocator from prior training/merge cycles. Intractable at application level (PyTorch allocator internals). Workaround: skip `--post-quantization-stats` when resuming, validate vLLM manually in a separate process. Related: [2026.02.14-peft-resume-from-merged.md](2026.02.14-peft-resume-from-merged.md).

### 2026.02.14 - PEFT Pipeline: Resume from Merged Adapter
- **Reference Document**: [2026.02.14-peft-resume-from-merged.md](2026.02.14-peft-resume-from-merged.md) - **REFERENCE** - Operational runbook for the `--resume-from-merged` flag added to `peft_trainer.py`. Skips phases 1-3 (pre-validation, fine-tuning, adapter merge) and jumps directly to phase 4-5 (post-training validation + quantization) using an existing merged adapter directory. Includes exact CLI incantations (with/without sudo), environment variable prerequisites, flag reference table, and phase map. Target: Ministral-8B-Instruct-2410 merged adapter from 2026-02-14 02:24. vLLM server lifecycle is self-managed by the trainer. Normal full-run path: `run-agentic-intent-training.sh`.

### 2026.02.14 - Proxy Integration Test Plan (12-Scenario Matrix)
- **Test Plan**: [2026.02.14-proxy-integration-test-plan.md](2026.02.14-proxy-integration-test-plan.md) - **✅ IMPLEMENTED** - Original test plan for the 12-scenario proxy integration test combining Calculator (3), CRUD (5), and Expediter (4) scenarios. Tests exercise the full notification proxy auto-answer pipeline: submit-and-poll for Calculator/CRUD, synchronous arg resolution for Expediter, with 3-tier strategy chain (Phi-4 script matcher, keyword rules, Claude cloud fallback). 10 unit tests accompany the integration test (1170 total). **Reference guide**: `src/docs/automated-interactive-testing.md`.

### 2026.02.14 - SWE Team Phase 4: Trust-Aware Decision Proxy — 4-Layer Architecture
- **Architecture & Light-Up Plan**: [2026.02.14-swe-team-phase-4-decision-proxy-architecture/00-index.md](2026.02.14-swe-team-phase-4-decision-proxy-architecture/00-index.md) - **🔄 IN PROGRESS** - Graduated-trust autonomous decision-making for the SWE team. 4-layer hybrid architecture: Layer 1 shared proxy infrastructure (extracted from notification_proxy), Layer 2 notification proxy (refactored), Layer 3 decision proxy (domain-agnostic trust framework with TrustTracker L1-L5, CircuitBreaker, PostgreSQL DecisionStore), Layer 4 SWE engineering proxy (6 engineering categories, concrete strategy). Architecture implemented (Phases 4a-4e, 1490 tests). **Light-Up Plan**: 8-phase plan to connect all disconnected surfaces — mount REST router, wire INI config, add persistence, build UI dashboard, enable notifications. Original architecture doc preserved as [2026.02.14-decision-proxy-architecture-original.md](2026.02.14-swe-team-phase-4-decision-proxy-architecture/2026.02.14-decision-proxy-architecture-original.md).

### 2026.02.13 - Unified Notification Proxy + Interactive Smoke Test Framework
- **Implementation Document**: [2026.02.13-unified-smoke-test-framework.md](2026.02.13-unified-smoke-test-framework.md) - **🔄 IN PROGRESS** - Extract ~450 lines of duplicated infrastructure from 3 live pipeline smoke tests (calculator, CRUD, expeditor) into reusable base classes. `LivePipelineTestBase` (shared auth, session, polling, validation), `EmbeddedProxyMixin` (auto-launch notification proxy as subprocess), `InteractiveSmokeTest` (merged class for voice-interactive tests). 4 new files in `src/tests/smoke/utilities/`, 3 existing tests refactored. Phase 1-2 complete, Phase 3 live verification pending server availability. Unit regression: 815 passed, 2 pre-existing failures.

### 2026.02.12 - Three-Model PEFT/LoRA Comparison: Ministral-8B vs Qwen3-4B vs Llama-3.2-3B
- **Analysis Document**: [2026.02.12-three-model-peft-comparison-ministral-qwen-llama.md](2026.02.12-three-model-peft-comparison-ministral-qwen-llama.md) - **ANALYSIS COMPLETE — Deploy Ministral-8B 8-bit** - Comprehensive comparison of three fine-tuned LoRA models for 34-command agentic intent routing. Ministral-8B dominates: 97.9% exact match POST-training, 8-bit quantization is lossless (98.7% EM, 0 commands degraded, +0.8pp vs full precision). Qwen3-4B loses 11.8pp on 4-bit quantization (94.7% → 83.0%, 20 commands degraded). Llama-3.2-3B is not viable (64.1% EM post-quant, 25 commands degraded). Includes per-command accuracy breakdown across all 34 commands, speed vs accuracy tradeoff matrix, VRAM footprint analysis (8-bit Ministral ~8.7GB fits on 24GB RTX 4090 at 0.85 util), and training pipeline timing comparison. Config switched from Qwen3 4-bit to Ministral 8-bit for development routing.

### 2026.02.12 - CJ Flow Bounded Job Packaging Guide
- **Reference Document**: [2026.02.12-cj-flow-bounded-job-packaging-guide.md](2026.02.12-cj-flow-bounded-job-packaging-guide.md) - **REFERENCE** - Comprehensive packaging guide for adding new bounded jobs to the CJ Flow (COSA Jobs Flow) queue system. Covers all 7 required pieces: job class (AgenticJobBase subclass), QueueableJob protocol compliance (22 attrs + 4 methods), factory registration, config keys, REST router, notifications, and smoke test. Includes full walkthrough of ClaudeCodeJob reference implementation, copy-paste quick-start template, three-tier testing checklist (smoke/unit/integration), and 6 documented common pitfalls (race conditions, missing attrs, asyncio conflicts). Canonical reference for `src/cosa/agents/<name>/job.py` pattern.

### 2026.02.11 - vLLM Llama-3.2-3B Latency Analysis: Why 2.8x Slower Than Qwen3-4B?
- **Research Document**: [2026.02.11-vllm-llama-3.2-latency-analysis.md](2026.02.11-vllm-llama-3.2-latency-analysis.md) - **📊 ANALYSIS COMPLETE — Fix: Force Marlin GPTQ kernel** - Llama-3.2-3B (3B params, 4-bit GPTQ) runs at ~490 ms/item — 2.8x slower than Qwen3-4B (174 ms) despite being a smaller model. Root cause: AutoRound GPTQ not triggering the Marlin kernel (documented 2.6x gap between naive GPTQ and Marlin-GPTQ). Fix: add `--quantization gptq_marlin` to vLLM config for post-quantization validation stage only. Expected improvement: ~490 ms → ~200 ms. Includes cross-model architecture comparison, CPU overhead analysis, tiered optimization recommendations, and vLLM 0.9.x upgrade warning. Follow-up to [Qwen3 Upgrade Analysis](2026.02.10-vllm-upgrade-analysis-qwen3-performance.md).

### 2026.02.11 - CRUD Live Pipeline Testing Guide
- **Testing Guide**: [2026.02.11-crud-live-pipeline-testing-guide.md](2026.02.11-crud-live-pipeline-testing-guide.md) - **🔄 ONGOING** - How to run the 8-scenario CRUD live pipeline test with notification proxy auto-confirmation. Covers bug fix status (complete), unit tests (6 new, 816 total), two-terminal proxy setup, expected results with/without proxy, scenario matrix reference, and remaining work (live run, Part 2 UI tests, Phase 4). Session 189, commit fd21f0c.

### 2026.02.10 - Fix CRUD Delete Bug + Live Pipeline Smoke Test
- **Implementation Plan**: [2026.02.10-crud-delete-bug-fix-and-live-pipeline-smoke-test.md](2026.02.10-crud-delete-bug-fix-and-live-pipeline-smoke-test.md) - **📋 PLANNED** - Fix delete-all-records bug (Session 167) + create live pipeline smoke test. Part A: 5-change bug fix (dedup keys in schemas.py, dedup guard in add_item, multi-delete guard in delete_item, reject infra columns in match_fields, "duplicate" voice formatting). Part B: 6 new unit tests (TestDeduplicationGuards). Part C: `test_crud_live_pipeline.py` — 8-scenario live test matrix following calculator + expeditor patterns (direct-mode todo/calendar CRUD + LORA routing). Part D: Full regression verification. Replaces Part 3 curl tests.

### 2026.02.10 - Expand Smoke Test Matrix to 13 Scenarios
- **Implementation Plan**: [2026.02.10-expand-smoke-test-matrix-13-scenarios.md](2026.02.10-expand-smoke-test-matrix-13-scenarios.md) - **🔄 IN PROGRESS** - Expand expeditor smoke test matrix from 9 to 13 scenarios. 4 new scenarios: DR_FULL (all args, confirmation-only), RTP_LANGUAGES (partial extraction), PG_LANGUAGES (languages + special handler), RTP_BARE (maximum 5-arg batch). Fixes two-pass docstring to single-pass automated instructions. DR_CANCEL stays manual-only (1-of-13). Automated run covers 12 scenarios in single proxy pass. Session 179.

### 2026.02.10 - Calculator Step 24: Automated Q&A Card Test Matrix
- **Implementation Plan**: [2026.02.10-calculator-step-24-automated-qa-card-test-matrix.md](2026.02.10-calculator-step-24-automated-qa-card-test-matrix.md) - **IN PROGRESS** - Automated smoke test for Calculator agent live pipeline (Step 24 of testing ladder). Adds `job_id` to `/api/push` response for clean poll-by-ID, creates 6-query test matrix exercising full pipeline: TodoFifoQueue → mode bypass → CalculatorAgent → Phi-4 intent extraction → dispatch → TTS. Includes dedicated mock job test account with auto-registration. Session 172.

### 2026.02.10 - Notification Proxy Agent Design
- **Design Document**: [2026.02.10-notification-proxy-agent-design.md](2026.02.10-notification-proxy-agent-design.md) - **✅ IMPLEMENTED** - Standalone CLI agent ("Notification Proxy") that logs in as `mock.tester@lupin.deepily.ai`, subscribes to notification events via WebSocket, and automatically answers Runtime Argument Expediter questions using a hybrid strategy: rules for known patterns, LLM fallback for unknowns. Architecture: WebSocket listener → notification router → strategy chain (ExpediterRuleStrategy + LLMFallbackStrategy) → REST API response submission. 4 test profiles (deep_research, podcast, research_to_podcast, minimal). 49 unit tests, 10 test classes. Package: `src/cosa/agents/notification_proxy/`. Extensible to Use Case 2 (meta-orchestrator proxy for all agent notifications). Session 171, commit e485bb1.

### 2026.02.10 - vLLM Upgrade Analysis: Should We Go from 0.8.5 → 0.9.2 for Qwen3-4B?
- **Research Document**: [2026.02.10-vllm-upgrade-analysis-qwen3-performance.md](2026.02.10-vllm-upgrade-analysis-qwen3-performance.md) - **📊 ANALYSIS COMPLETE — Stay on 0.8.5** - Qwen3-4B-Base (4B params, 4-bit GPTQ) runs 1.7x slower than Ministral-8B (8B params) on vLLM 0.8.5 despite having half the parameters. Root causes: kernel maturity gap (Mistral has 2+ years of CUDA optimization vs <1 year for Qwen3), GPTQ kernel selection (Marlin-GPTQ is 2.6x faster than regular GPTQ per JarvisLabs benchmarks), small model overhead. Upgrading to 0.9.2 would **make things worse**: V1 engine shows -28% throughput on small models (GitHub #19499), Qwen3-specific TTFT collapse (GitHub #20469), 9.5x AllReduce overhead (GitHub #21852). Recommendation: check Marlin kernel selection, try `--no-enable-chunked-prefill`, run full 100% training set for accuracy comparison. Follow-up to [Root Cause Analysis](2026.02.10-qwen3-vllm-inference-slowdown-root-cause.md).

### 2026.02.10 - Qwen3-4B vLLM Inference Slowdown Root Cause Analysis
- **Research Document**: [2026.02.10-qwen3-vllm-inference-slowdown-root-cause.md](2026.02.10-qwen3-vllm-inference-slowdown-root-cause.md) - **🔍 ROOT CAUSE IDENTIFIED** - Qwen3-4B-Base shows 20x slowdown (~7,392 ms/item) vs Ministral-8B (~368.7 ms/item) during PEFT validation. Root cause: vLLM 0.8.2 has no native `Qwen3ForCausalLM` support — falls back to unoptimized HuggingFace Transformers engine. Architecture comparison rules out model design (Qwen3 is smaller in every compute dimension). Fix: upgrade vLLM to >= 0.8.5 where native Qwen3 support was added. Community confirmation via vLLM Issue #17630.

### 2026.02.09 - Everyday Calculator Agent Implementation
- **Implementation Plan**: [2026.02.09-everyday-calculator-agent-implementation.md](2026.02.09-everyday-calculator-agent-implementation.md) - **PENDING** - Intent-dispatched deterministic calculator agent using CRUD-style pattern. LLM extracts intent into CalcIntent XML model, pure Python functions execute the operation (no code generation, no sandbox). Three capability domains: (1) Unit conversions (km/miles, F/C, grams/pounds — hub-and-spoke conversion tables), (2) Unit price comparison (normalize dissimilar product sizes to common cost-per-unit), (3) Mortgage calculator (amortization formula). Single routing command `agent router go to calculator`, CalculatorAgent inherits AgentBase, MathAgent fallback for exotic queries. Package: `src/cosa/agents/calculator/`. 4 implementation phases, 22 steps.

### 2026.02.09 - Expeditor Default Values Design
- **Design Document**: [2026.02.09-expeditor-default-values-design.md](2026.02.09-expeditor-default-values-design.md) - **IMPLEMENTED** - Default values for RuntimeArgumentExpeditor batch question inputs. Pre-populates text fields with sensible defaults (budget: "no limit", audience: "academic", languages: "en,es-MX") so users can accept by hitting Submit All. Three-tier override chain: config INI > agent_registry fallback_defaults > None. Key files: `agent_registry.py` (fallback_defaults dict), `expeditor.py` (_resolve_default method), `notification_utils.py` (default_value passthrough), `notifications.js` (value attribute on inputs), `lupin-app.ini` (config overrides).

### 2026.02.09 - PEFT Trainer Enhancements: Dual Quantization, Markdown Dashboard, Multi-LLM
- **Implementation Document**: [2026.02.09-peft-trainer-enhancements-dual-quant-multi-llm.md](2026.02.09-peft-trainer-enhancements-dual-quant-multi-llm.md) - **✅ IMPLEMENTED** - Three enhancements to the PEFT training pipeline: (1) Dual quantization — compare 4-bit vs 8-bit via `--quantize-bits {both,4,8}` flag. (2) Markdown training results — versioned files with YAML frontmatter in `io/peft/`. (3) Multi-LLM support — `--llm {ministral-8b,qwen3-4b}` flag with Qwen3-4B-Base config. Files: `peft_trainer.py` (~200 net new lines), `qwen3_4b.py` (NEW), `model_config_loader.py`, `run-agentic-intent-training.sh`, config files.

### 2026.02.09 - Gist Embeddings Analysis: Keep vs. Jettison
- **Research Document**: [2026.02.09-gist-embeddings-analysis-keep-vs-jettison.md](2026.02.09-gist-embeddings-analysis-keep-vs-jettison.md) - **📊 ANALYSIS COMPLETE** - Comprehensive analysis of gist embedding system value in the retrieval pipeline. Finding: gist _text_ is valuable (Level 3 exact matching), but gist _embeddings_ are dead code — never searched in Level 4 vector similarity, `threshold_gist` parameter accepted but never applied, `get_snapshots_by_solution_gist_similarity()` has zero callers. Recommends 3-phase cleanup: Phase 1 remove dead code paths, Phase 2 stop generating gist embeddings at snapshot creation, Phase 3 optionally re-enable with proper integration if needed. Key files: `lancedb_solution_manager.py`, `solution_snapshot.py`, `todo_fifo_queue.py`.

### 2026.02.07 - PEFT Training Optimization Plan — Part 3
- **Optimization Plan**: [2026.02.07-peft-trainer-optimization-plan-part-3.md](2026.02.07-peft-trainer-optimization-plan-part-3.md) - **📋 PLANNED** - Principled augmentation for 4 under-sampled simple commands (automatic routing mode: 60, none: 214, math: 450, todo list: 443 — all targeting 1500). Hybrid strategy: expand templates to ~200-500 lines each for semantic diversity, then apply controlled augmentation factor (3-8x) via new `augmentation_config` parameter in `build_simple_agent_router_training_prompts()`. Avoids pure factor multiplication which degrades LORA generalization. Cross-references [Part 2](2026.02.07-peft-trainer-optimization-plan-part-2.md).

### 2026.02.07 - Runtime Argument Expeditor Confirmation Loop Plan
- **Implementation Plan**: [2026.02.07-runtime-argument-expeditor-confirmation-loop-plan.md](2026.02.07-runtime-argument-expeditor-confirmation-loop-plan.md) - **IMPLEMENTED** - Confirmation loop feature for the Runtime Argument Expeditor. Two deliverables: (1) `_confirm_and_iterate()` method in `expeditor.py` — summarize args → user approves/modifies/cancels via voice → iterate with LLM-parsed `ArgConfirmationResponse`. (2) 9-scenario smoke test matrix covering all 3 agents (Deep Research, Podcast Generator, Research-to-Podcast), audience params, missing args, and cancellation. Also standardized `audience_context` fallback questions across all agents. Session 151, commit b7c191f, 482/482 unit tests passing.

### 2026.02.07 - PEFT Training Optimization Plan — Part 2
- **Optimization Plan**: [2026.02.07-peft-trainer-optimization-plan-part-2.md](2026.02.07-peft-trainer-optimization-plan-part-2.md) - **🔄 IN PROGRESS** - Continuation of PEFT training optimization. Phase 2 achieved 99.0% pre-quant / 95.6% post-quant exact match. Three workstreams: Part A (Training Results Dashboard — consolidated comparison of pre/post-training/post-quantization stages), Part B (Explicit Agent Routing Data — "Switch to math mode" phrases for all agents + new automatic routing mode command), Part C (Strengthen Quantization-Degraded Commands — supplement podcast generator, math, todo list, none with stronger anchors). Sample size increase 1200 → 1500 samples/command. Cross-references [Part 1](2026.02.05-peft-trainer-optimization-plan.md).

### 2026.02.06 - DataFrame CRUD Storage Layer (Phase 1)
- **Implementation Directory**: [2026.02.04-headless-cc-for-dataframe-crud/](2026.02.04-headless-cc-for-dataframe-crud/) - **🔄 PHASE 1 IN PROGRESS** - Per-user parquet-backed DataFrame CRUD storage layer. Layer 1 of 3-layer architecture (Storage → Intent Extraction → Dispatcher). Contains layer docs, implementation tracker, and cross-phase progress. Code at `src/cosa/crud_for_dataframes/`.
  - [layer-1.md](2026.02.04-headless-cc-for-dataframe-crud/layer-1.md) - Storage + schemas + CRUD + XML models
  - [layer-2.md](2026.02.04-headless-cc-for-dataframe-crud/layer-2.md) - Phi-4 14B intent extraction (stub)
  - [layer-3.md](2026.02.04-headless-cc-for-dataframe-crud/layer-3.md) - Dispatcher + caching + voice I/O (stub)
  - [implementation-tracker.md](2026.02.04-headless-cc-for-dataframe-crud/implementation-tracker.md) - Cross-phase progress

### 2026.02.05 - Agentic Voice Workflow Skill Expansion Plan
- **Planning Document**: [2026.02.05-agentic-voice-workflow-expansion-plan.md](2026.02.05-agentic-voice-workflow-expansion-plan.md) - **📋 READY TO IMPLEMENT** - Plan to expand the `lupin-new-claude-agent-sdk-voice-workflow` skill from ~1,100 lines (BUILD only) to ~2,500 lines covering CONCEPT → BUILD → TEST lifecycle. Gap analysis reveals current workflow covers only ~30% of real agent complexity. Key additions: Part I CONCEPT (architecture overview, decision criteria), Part II BUILD phases 5-10 (LLM client integration, cost tracking, rate limiting, external service integration, advanced orchestration, async/callback architecture), Part III TEST phases 11-16 (inline smoke tests, dry-run mode, API smoke tests, unit tests, integration tests, manual verification checklist). Full templates for all new phases. Reference agents: Deep Research (~4,000 lines), Podcast Generator (~2,500 lines).

### 2026.02.05 - PEFT Training Optimization Plan
- **Optimization Plan**: [2026.02.05-peft-trainer-optimization-plan.md](2026.02.05-peft-trainer-optimization-plan.md) - **✅ PHASES 1-2 COMPLETE** - Three-phase plan to improve PEFT training accuracy from 85% to 96%+. Phase 1 achieved 92.2% exact match (target: 89%). Phase 2 achieved 99.0% pre-quant / 95.6% post-quant. Continued in [Part 2](2026.02.07-peft-trainer-optimization-plan-part-2.md). Target: Ministral-8B-Instruct-2410 model.

### 2026.02.05 - DataFrame CRUD with Voice I/O Implementation
- **Implementation Plan**: [2026.02.05-crud-for-dataframes-implementation.md](2026.02.05-crud-for-dataframes-implementation.md) - **🔄 PHASE 1 IN PROGRESS** - Voice-driven DataFrame CRUD operations with per-user parquet storage. Pattern 1 (Multi-Phase) implementation. Phase 1: Storage layer + Pydantic models (`src/cosa/crud_for_dataframes/`). Phase 2: Agent implementation (CrudForDataFramesAgent inheriting AgentBase). Phase 3: Queue integration + RuntimeArgumentExpeditor reuse. Phase 4: Voice I/O + confirmation flows. Reuses existing patterns: BaseXMLModel for XML parsing, ConfigurationManager for paths, snapshot_mgr for semantic caching, todo_fifo_queue routing.

### 2026.02.05 - Runtime Argument Expeditor Testing Plan
- **Testing Plan**: [2026.02.05-runtime-argument-expeditor-testing-plan.md](2026.02.05-runtime-argument-expeditor-testing-plan.md) - **✅ UNIT + AUTOMATED SMOKE COMPLETE, INTERACTIVE PENDING** - Comprehensive testing plan for the Runtime Argument Expeditor. 49 unit tests (5 classes: ExpeditorResponse model, _parse_lora_args, _inject_system_args, agent registry, agentic_job_factory) all passing in 0.54s. 3/5 smoke tests automated and passing (login, health, mock job). 2 interactive smoke tests pending (`LUPIN_INTERACTIVE_TESTS=true` required — expeditor voice routing + dry-run verification need LLM and user present for voice prompts).

### 2026.02.04 - Rebalancing XML Training Datasets
- **Planning Document**: [2026.02.04-rebalancing-xml-training-datasets.md](2026.02.04-rebalancing-xml-training-datasets.md) - **📋 READY TO IMPLEMENT (after first full training run review)** - Plan to rebalance all 32 routing commands to 400 samples/command in the pre-split dataset. Current state: 19x imbalance (1,600 max vs 83 min). Root cause: compound commands cross-multiply while simple commands have ~200 raw lines with no augmentation. Changes: unified `sample_size_per_command` parameter, add interjections/salutations to `build_simple_vox_cmd_training_prompts()`, fix 2 copy-paste `len()` bugs, add distribution verification. Target: 12,800 pre-split → ~10,240 train / ~1,280 test / ~1,280 validate. Analysis script: `src/scripts/analyze-training-distribution.py`.

### 2026.02.04 - Runtime Argument Expeditor Design
- **Design Document**: [2026.02.04-runtime-argument-expeditor-design.md](2026.02.04-runtime-argument-expeditor-design.md) - **✅ IMPLEMENTED** - Runtime argument disambiguation layer between LORA intent classification and agentic job creation. Detects missing CLI arguments via LLM gap analysis against `--help` output, asks user for missing info via synchronous voice notifications, then creates the job with complete args. Covers 3 agents: Deep Research, Podcast Generator, Research-to-Podcast. 8 implementation phases complete: agent registry, XML response model, core expeditor, prompt template, config, router template extension, TodoFifoQueue integration, testing integration (shared agentic_job_factory, REST endpoint refactor, mock job expeditor test mode). All smoke tests passing.

### 2026.01.30 - Defensive Attribute Access Anti-Pattern Research
- **Research Document**: [2026.01.30-defensive-attribute-access-anti-pattern.md](2026.01.30-defensive-attribute-access-anti-pattern.md) - **✅ IMPLEMENTED** - Comprehensive analysis and refactoring of the `hasattr()`/`getattr()` anti-pattern in the queue system. **Phases 1-4 complete**: Protocol validation at boundaries (FifoQueue, TodoFifoQueue, RunningFifoQueue), replaced ~89 `getattr` chains with direct attribute access, replaced ~15 `hasattr` type checks with `isinstance()`. Updated QueueableJob Protocol with user_email, started_at, completed_at, is_cache_hit, status, error attributes. All smoke tests passing. Phase 5 (static analysis) deferred to v0.2.0 CI.

### 2026.01.29 - Math Agent TTS Bug Investigation
- **Bug Investigation**: [2026.01.29-math-agent-tts-bug-investigation.md](2026.01.29-math-agent-tts-bug-investigation.md) - **🔧 ROOT CAUSE IDENTIFIED** - Investigation of Math Agent TTS not working while Mock Jobs work. Two issues found: (1) Race condition where `associate_job_with_user()` called after `push()` - FIXED. (2) Missing `user_email` attribute on agents causing TTS to route to wrong user - FIX PENDING. Includes code locations, notification flow tracing, and implementation plan for setting `user_email` on agents at creation time.

### 2026.01.20 - Podcast Generator Agent (Phase 2 Complete)
- **Implementation**: [src/cosa/agents/podcast_generator/](../cosa/agents/podcast_generator/) - **🔄 PHASE 2 COMPLETE, PHASES 3-4 PENDING** - "Dynamic Duo" podcast generator transforming Deep Research documents into conversational audio podcasts. **Phase 1** (Script Generation): PodcastOrchestratorAgent async state machine, PodcastConfig with customizable host personalities (Nora/Quentin defaults, ElevenLabs voice mappings Sarah/Arnold), PodcastScript/ScriptSegment Pydantic models with prosody annotations, PodcastAPIClient (firewalled API pattern, cost tracking), cosa_interface.py (voice I/O), CLI entry point. **Phase 2** (TTS Audio Generation - Session 80-82): `tts_client.py` (~350 lines) with ElevenLabs WebSocket batch generation, retry logic with exponential backoff, progress callbacks with ETA tracking, retry notifications. `audio_stitcher.py` (~150 lines) with pydub-based PCM→MP3 concatenation, 300ms silence on speaker changes. Orchestrator updated with Phase 5 (GENERATING_AUDIO) and Phase 6 (STITCHING_AUDIO). **CLI Modes**: `--research` (full workflow), `--edit-script` (resume review), `--generate-audio` (audio-only from existing script). **Smoke Tests**: 10/10 passing (config, state, prompts.script_generation, prompts.personality, cosa_interface, voice_io, api_client, tts_client, audio_stitcher, orchestrator). **State Machine**: LOADING_RESEARCH → ANALYZING_CONTENT → GENERATING_SCRIPT → WAITING_SCRIPT_REVIEW → GENERATING_AUDIO → STITCHING_AUDIO → COMPLETED. **Remaining Phases**: Phase 3 (Voice CLI), Phase 4 (COSA Router integration). Pattern 6 research-driven implementation following Deep Research Agent architecture.

### 2026.01.14 - Semantic Session Names Design
- **Design Document**: [2026.01.14-semantic-session-names-design.md](2026.01.14-semantic-session-names-design.md) - **📋 READY TO IMPLEMENT** - Comprehensive design for enhancing notification UI session identification. Features: smarter auto-naming algorithm (action verbs + key nouns extraction instead of first 4 words), localStorage persistence for session names, inline edit capability (click to rename), and "Generate Gist" button calling backend Gister for LLM-powered summarization. Solves the problem of generic session names like "Hello, I need help" by extracting meaningful terms like "Fix Authentication Bug". Includes design space exploration, algorithm implementation, and verification steps.

### 2026.01.14 - Deep Research Agent Implementation Status
- **Design Document**: [cosa-deep-research-agents.md](cosa-deep-research-agents.md) - **🔄 PHASE 1 COMPLETE, PHASE 2 IN PROGRESS** - Voice-driven deep research agent integrating COSA, async orchestration, and Claude API for multi-agent research. Phase 1 complete: ResearchOrchestratorAgent skeleton, OrchestratorState enum (13 states), Pydantic models (SubQuery, ResearchPlan, SubagentFinding), cosa_interface.py async wrappers, all smoke tests passing. Phase 2 (Direct Anthropic API): Architecture chosen after analysis showed Claude Code CLI lacks web search/model selection. Will implement api_client.py with web search tool, cost_tracker.py for exact per-request cost tracking, and prompt templates. Located at `src/cosa/agents/deep_research/`.

### 2026.01.13 - Conversation Identity Architecture Implementation
- **Implementation Spec**: [2026.01.13-conversation-identity-phases-1-3.md](2026.01.13-conversation-identity-phases-1-3.md) - **✅ IMPLEMENTED** - Full specification and implementation of Phases 1-3 of Conversation Identity Architecture. Enables parallel Claude Code sessions to be distinguished in notification UI. Phase 1: Session Identity (SESSION_ID generation at MCP startup, new sender_id format `claude.code@{project}.deepily.ai#{session_id}`). Phase 2: Active Conversation Routing (get_active_conversation() repository method, API endpoints, WebSocket broadcast). Phase 3: Notification UI Updates (parseSenderId() JS helper, sender card session display, active indicators ●/○). All code implemented and tested, ready for live UI verification.

### 2026.01.13 - Job Queue Progressive Disclosure Design
- **Design Document**: [2026.01.13-job-queue-progressive-disclosure-design.md](2026.01.13-job-queue-progressive-disclosure-design.md) - **📋 DESIGN COMPLETE** - Comprehensive design for enhancing Job Queues section with progressive disclosure UI. Features: expandable queue categories (TODO/Running/Done/Dead), full job cards with question/status/timestamps/agent/runtime stats, and user interaction history showing notifications exchanged during job processing. Solves the job-notification correlation problem (linking jobs to their MCP notification conversations). Includes 6 implementation phases, MVP option (~1 week, UI only) and Full option (~2-3 weeks, with interaction history). Ready for future implementation.

### 2026.01.12 - COSA Unified Agent Architecture
- **Architecture Design**: [2026.01.12-cosa-unified-agent-architecture.md](2026.01.12-cosa-unified-agent-architecture.md) - **🔄 IN PROGRESS** - Comprehensive architecture document covering three areas: (1) **Agent Architecture Analysis** - Comparative analysis of COSA agents vs Claude Code Dispatchers with 5 commonalities, 5 differences, and "Parallel with Shared Contracts" recommendation; (2) **Integration Patterns** - Code generation failure escalation to Claude Code, queue integration options; (3) **Conversation Identity Architecture** - Process-centric model for multi-session tracking, active conversation routing, notification UI nested accordion design, AgentBase conversation history integration. Enables distinguishing parallel Claude Code sessions in same project.

### 2026.01.12 - User-Level Mode System
- **Design Document**: [2026.01.12-user-level-mode-system-design.md](2026.01.12-user-level-mode-system-design.md) - **📋 READY TO IMPLEMENT** - Comprehensive design for user-level mode switching. Allows users to bypass LLM router and route directly to specific agents (math, calendar, weather, etc.). Features: in-memory state storage, 4 API endpoints, UI mode selector, session-only persistence. Includes architecture diagrams, API specification, UI mockups, and testing strategy.

### 2026.01.12 - Claude Code CLI Docker Installation
- **Docker Installation Guide**: [2026.01.12-claude-code-cli-docker-installation.md](2026.01.12-claude-code-cli-docker-installation.md) - **✅ IMPLEMENTED** - Level 2 implementation adding Claude Code CLI to Lupin Docker container. Enables Claude Code Dispatcher feature in containerized environments. Covers: Node.js 20.x + npm installation, cosa-voice MCP configuration with container paths, API key handling patterns (local dev prompt-style paste vs GCP Secret Manager), verification procedures. No secrets baked into image. ~200MB image size increase.

### 2026.01.09 - Claude Code Dispatcher Docker Deployment
- **Docker Deployment Analysis**: [2026.01.09-claude-code-dispatcher-docker-deployment.md](2026.01.09-claude-code-dispatcher-docker-deployment.md) - **📊 ANALYSIS COMPLETE** - Comprehensive analysis of deployment options for Claude Code Dispatcher feature. Documents 4 streaming fixes (output format, async subprocess, background task scheduling, CLI environment). Includes trade-off matrix for 4 deployment options: Install CLI in Docker (recommended), Run FastAPI locally, Use Anthropic SDK directly, Hybrid API proxy. Implementation checklist for Docker CLI installation.

### 2026.01.05 - Directory Rename Planning
- **Directory Rename Plan**: [2026.01.05-directory-rename-genie-to-lupin-plan.md](2026.01.05-directory-rename-genie-to-lupin-plan.md) - **⏳ PENDING** - Comprehensive plan for renaming project directory from `lupin` to `lupin`. Covers 76+ internal files, 6 external configs, 2 virtual environments, backup directories. 100% removal of "genie" naming (except legacy Jupyter notebooks). Estimated ~90 minutes execution time. 24-step checklist with rollback plan.

### 2026.01.02 - Claude Code Voice MCP Integration
- **Design Document**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2025.12.30-claude_code_voice_mcp_guide.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2025.12.30-claude_code_voice_mcp_guide.md) - **📋 DESIGN COMPLETE** - Comprehensive 935-line architecture guide for voice-enabled MCP server. Covers two operational modes: Option A (Print Mode for bounded tasks) and Option B (SDK Client for interactive sessions), plus Cold Call voice-initiated sessions.
- **Implementation Trajectory**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-00-mcp-voice-implementation-trajectory.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-00-mcp-voice-implementation-trajectory.md) - **📊 STATUS REPORT** - Design-to-implementation journey documenting what was built (MCP Server), what exists but isn't integrated (cosa_dispatcher.py), and gap analysis for remaining work.
- **Option A Planning**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-01-option-a-print-mode-planning.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-01-option-a-print-mode-planning.md) - **📋 READY TO IMPLEMENT** - Roadmap for bounded task execution via `claude -p "task"`. 5 phases: move dispatcher to production, update configs, smoke tests, E2E tests, CI/CD examples. Estimated 6-10 hours.
- **Option B Planning**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-02-option-b-sdk-client-planning.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-02-option-b-sdk-client-planning.md) - **⏸️ DEFERRED (SDK TBD)** - Roadmap for interactive SDK Client sessions. Depends on `claude-agent-sdk` availability. 5 phases covering session lifecycle, inject/interrupt, voice integration.
- **Cold Call Planning**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-03-cold-call-flow-planning.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-03-cold-call-flow-planning.md) - **⏸️ DEFERRED (needs A or B)** - Roadmap for voice-initiated session spawning. 6 phases: voice grammar, intent parser, daemon, wake word, dispatcher integration, E2E testing.
- **MCP Server**: `src/lupin_mcp/` - **✅ COMPLETE** - Production MCP server (372 lines) with 4 tools: notify(), converse(), ask_yes_no(), get_session_info(). Dynamic project detection, 10 smoke tests passing.

### 2025.12.30 - Sender-Aware Notification System
- **Implementation Tracker**: [2025.12.30-sender-aware-notification-tracker.md](2025.12.30-sender-aware-notification-tracker.md) - **🔄 IN PROGRESS** - Execution tracker for 8-phase sender-aware notification system implementation. Adds sender identification (`claude.code@{project}.deepily.ai`) enabling multi-project notification grouping, chat-style UI with collapsible sender cards, and conversation history persistence.
- **Design Document**: [2025.12.29-sender-aware-notification-system-design.md](2025.12.29-sender-aware-notification-system-design.md) - **📋 DESIGN COMPLETE** - Comprehensive 513-line implementation plan covering Queue Layer, CLI Layer, API Layer, PostgreSQL persistence, Frontend JS/CSS, and testing strategy.

### 2025.11.20 - Admin Solution Snapshots Dashboard
- **Admin Interface Planning**: [2025.11.20-admin-snapshots-dashboard.md](2025.11.20-admin-snapshots-dashboard.md) - **📋 READY TO IMPLEMENT** - Comprehensive implementation plan for admin solution snapshots search dashboard. Features: Simple text search (Question/Normalized/Gist), table display with view details modal, delete with confirmation, JWT admin role enforcement. Architecture: 3 new admin.py endpoints (search/details/delete), vanilla HTML/JS/CSS following Fresh Queue patterns. Developed through interactive requirements elicitation (7 questions), includes 5 implementation phases, testing checklists, 7-11 hour timeline. Foundation for future admin tools.

### 2025.11.20 - Math Agent XML Schema Mismatch Investigation
- **XML Pipeline Debugging**: [2025.11.20-math-agent-xml-schema-mismatch.md](2025.11.20-math-agent-xml-schema-mismatch.md) - **🔍 INVESTIGATION IN PROGRESS** - Comprehensive analysis of pydantic_ai integration revealing two-stage XML pipeline schema mismatch. Math agent uses CodeBrainstormResponse (7 required fields) for code generation, but formatter's simple RephraseResponse (`<rephrased-answer>`) is being validated against wrong schema. Includes complete pipeline flow analysis, 4 hypotheses, investigation checklist, and debugging roadmap. Follows successful pydantic_ai 0.6.2 API migration (ModelSettings, `.output`). Ready for next session's debugging.

### 2025.10.17 - SSE Phase 2 Design Session
- **Notification System**: [2025.10.15-sse-notifications/05-phase2-design-decisions.md](2025.10.15-sse-notifications/05-phase2-design-decisions.md) - **🚧 DESIGN IN PROGRESS** - Interactive design session for Phase 2 SSE notification system (response-required notifications). Completed: Database schema (persistent storage), response types (yes/no with LLM interpretation, open-ended), timeout behavior (multi-modal countdown). Pending: SSE architecture, return value propagation, UI/UX, MVP scoping. Resume point: Area 3 Q3.2 (Timeout handling). Session 1 of design Q&A complete (3/9 areas).
- **Design Questions**: [2025.10.15-sse-notifications/98-notification-design-draft.md](2025.10.15-sse-notifications/98-notification-design-draft.md) - Original design questions document (answers being captured in 05-phase2-design-decisions.md)

### 2025.10.16 - JWT Token Proactive Refresh
- **Authentication Enhancement**: [2025.10.16-jwt-token-proactive-refresh.md](2025.10.16-jwt-token-proactive-refresh.md) - **✅ COMPLETE** - Hybrid proactive token refresh system eliminating 401 errors during idle periods. Implements dual-mechanism refresh (periodic monitor + heartbeat-triggered), server-driven configuration with explicit unit naming, comprehensive testing strategy (17/17 tests passing). Solves high-priority notification playback after >1 hour inactivity. Production validated!

### 2025.10.04 - Admin User Management Implementation
- **Admin Interface**: [2025.10.04-admin-user-management-implementation-plan.md](2025.10.04-admin-user-management-implementation-plan.md) - **📋 READY TO IMPLEMENT** - Complete MVP plan for administrative user management interface. Includes user listing/search, role management, account status control, and admin password reset. Backend (admin_service.py, routers/admin.py), Frontend (admin/users.html, admin-users.js, admin.css), comprehensive API specs, security requirements, and integration testing strategy. Estimated 6-8 hours implementation.

### 2025.10.03 - User-Filtered Queue Views Implementation
- **Multi-Tenant Feature**: [2025.10.03-user-filtered-queue-views-implementation-plan.md](2025.10.03-user-filtered-queue-views-implementation-plan.md) - **✅ PHASE 1 COMPLETE** - Role-based queue filtering backend infrastructure with 32/32 unit tests passing (100%). Multi-tenant isolation with admin override capability. Phase 2 (Admin UI) and Phase 3 (Documentation) pending.

### 2025.09.28 - Three-Level Testing Framework Design
- **Testing Strategy**: [2025.09.28-three-level-testing-design-and-progress.md](2025.09.28-three-level-testing-design-and-progress.md) - **✅ COMPLETE** - Comprehensive testing implementation complete: 47 unit tests across 6 files, 100% success rate, all phases 1-3 finished

### 2025.09.27 - Three-Level Question Representation Architecture COMPLETE
- **Architecture Implementation**: [2025.09.27-three-level-question-representation-architecture.md](2025.09.27-three-level-question-representation-architecture.md) - **✅ COMPLETE** - Comprehensive implementation fixing critical search failures with hierarchical Verbatim → Normalized → Gist architecture
- **Session-End Automation**: [/src/rnd/2025.09.27-prompts/lupin-session-end.md](2025.09.27-prompts/lupin-session-end.md) - Automated end-of-session ritual extracted from configuration files

### 2025.09.23 - Smoke Test Prompt Infrastructure
- **Smoke Test Prompts**: [/src/rnd/2025.09.27-prompts/](2025.09.27-prompts/) - Comprehensive baseline and remediation testing infrastructure with Claude Code integration
- **Universal Templates**: [/src/rnd/2025.09.27-prompts/templates/](2025.09.27-prompts/templates/) - Reusable smoke test templates for any project
- **Claude Code Commands**: [/src/cosa/.claude/commands/](../cosa/.claude/commands/) - Intelligent slash commands for automated testing workflows

## Project Architecture Overview

Lupin is built on/uses:
- **FastAPI** server architecture
- **PydanticAI** for Agent-based abstractions & data validation
- **WebSockets** support for real-time communication

Lupin contains multiple sub repos:
- **CoSA** support for real-time communication
- **Lupin Mobile** implements queue UI for agent-to-user communication
- **Lupin Plugin for Firefox** provides browser integration for Lupin features

Lupin does a lot of things:
- **Notification system** for agent-to-user feedback
- **Voice drives Firefox with plugin**
- **Text-to-Speech (TTS)** streaming and caching of TTS audio responses
- **Speech-to-Text (STT)** for voice input
- **Abstracted access to LLMs** both local and industrial strength
- **Easy PEFT** High level training object performs all the things before during and after training a new LoRA for you
- **Code is memory** 

## Project Goals for v0.1.0
- **JWT authentication** using firebase? (See RND docs for details)
- **PydanticAI** data validation for XML-based I/O interactions with agents
- **Agentic frameworks** implement high-level abstraction for running the same query on multiple agentic frameworks
  - Google ADK 
  - OpenAI
  - Anthropic 
  - Perplexity 
- **Host on GCP** (Google Cloud Platform) for demoing and R&D purposes
- 

For implementation details, see the specific documents listed below.

## Active Documents

### Current Development (2025.09)

#### 🚀 Authentication System Design
- **[2025.09.29-jwt-oauth-implementation-design-and-tracker.md](2025.09.29-jwt-oauth-implementation-design-and-tracker.md)** - **📋 PLANNING**: Comprehensive JWT/OAuth authentication system design with 10-phase implementation plan, backward-compatible migration strategy, and complete tracking framework for upgrading from mock authentication to production-ready security (⏳ Phase 1-2 ready to begin)

#### 🎉 Major Infrastructure Completions
- **[2025.09.28-three-level-testing-design-and-progress.md](2025.09.28-three-level-testing-design-and-progress.md)** - **🔄 ACTIVE**: Comprehensive testing framework design for three-level representation system with progress tracking, testing patterns documentation, and critical test case specifications (📋 design complete - implementation in progress)
- **[2025.09.27-three-level-question-representation-architecture.md](2025.09.27-three-level-question-representation-architecture.md)** - **✅ COMPLETE**: Comprehensive three-level question representation architecture (Verbatim → Normalized → Gist) with ultrathinking analysis and six-phase implementation plan for systematic question indexing refactoring (🚀 implementation complete - search failures resolved)
- **[2025.09.22-cosa-agents-v010-migration-plan.md](2025.09.22-cosa-agents-v010-migration-plan.md)** - ✅ **COMPLETED**: Comprehensive zero-risk migration plan for moving 25 agent files from v010 subdirectory to main agents directory (✅ successfully executed - all agents consolidated)
- **[2025.09.20-memory-corruption-incident-report.md](2025.09.20-memory-corruption-incident-report.md)** - Complete incident report and recovery documentation for LanceDB database deletion and restoration (✅ completed - 44/44 snapshots recovered, all 4 tables operational with enhanced robustness)
- **[2025.08.22-solution-snapshot-lancedb-interface-migration-plan.md](2025.08.22-solution-snapshot-lancedb-interface-migration-plan.md)** - **🏆 MAJOR MILESTONE**: Complete LanceDB migration project from file-based JSON to vector database (✅ 100% COMPLETE - Phase 5 production deployment finished, enhanced table creation robustness)

### Previous Development (2025.08)

#### 🎉 Major Infrastructure Completions
- **[2025.08.13-smoke-test-data-collection-strategy.md](2025.08.13-smoke-test-data-collection-strategy.md)** - Comprehensive data-collection-first smoke testing methodology for systematic diagnostics (✅ completed - reusable framework established for future test runs)
- **[2025.08.13-smoke-test-execution-report.md](2025.08.13-smoke-test-execution-report.md)** - Complete analysis of 72-test smoke test suite with failure patterns and remediation priorities (✅ completed - critical API endpoint failures identified)
- **[2025.08.13-session-state-for-tomorrow.md](2025.08.13-session-state-for-tomorrow.md)** - Detailed continuation plan for immediate pickup of smoke test remediation work (✅ completed - ready for tomorrow's session)
- **[2025.08.12-template-rendering-investigation.md](2025.08.12-template-rendering-investigation.md)** - Investigation of prompt template rendering approaches: Python dictionaries vs Pydantic objects (✅ completed - current approach documented, future enhancement opportunities identified)
- **[2025.08.12-phase-6-complex-agent-requirements.md](2025.08.12-phase-6-complex-agent-requirements.md)** - Phase 6 complex agent migration requirements for IterativeDebuggingAgent and BugInjector (✅ completed - all complex agents migrated successfully to production)
- **[2025.08.10-xml-compatibility-investigation-findings.md](2025.08.10-xml-compatibility-investigation-findings.md)** - Analysis of baseline vs Pydantic XML parsing discrepancies and data integrity improvements (✅ completed - critical data loss issues resolved)
- **[2025.08.09-pydantic-xml-migration-plan.md](2025.08.09-pydantic-xml-migration-plan.md)** - **🏆 MAJOR MILESTONE**: Complete Pydantic XML migration from legacy util_xml.py to modern structured parsing (✅ 100% COMPLETE - all agents migrated to production with full type safety and zero issues)

#### Audio & UI Systems
- **[2025.08.06-tts-audio-caching-implementation.md](2025.08.06-tts-audio-caching-implementation.md)** - Lightweight TTS audio caching system with cross-mode compatibility and SHA-256 hashing (✅ completed - 71.4% hit rate achieved, ready for browser testing)
- **[2025.08.04-fresh-queue-ui-implementation.md](2025.08.04-fresh-queue-ui-implementation.md)** - Modern Fresh Queue UI with notification system and comprehensive job management (✅ completed)
- **[2025.08.03-qa-audio-silence-mystery.md](2025.08.03-qa-audio-silence-mystery.md)** - Critical technical mystery: Q&A responses produce silence while notifications work, despite identical execution paths (🔍 resolved)
- **[2025.08.01-sequential-audio-production-migration.md](2025.08.01-sequential-audio-production-migration.md)** - Production migration plan for Sequential Audio Element Queue from experimental validation to HybridTTS integration (✅ completed)
- **[2025.08.01-audio-chunk-sequential-playback-analysis.md](2025.08.01-audio-chunk-sequential-playback-analysis.md)** - Root cause analysis and implementation strategy for fixing audio chunk overlap issues (✅ completed - experimental validation successful)

### Current Development (2025.07)
- **[2025.07.30-websocket-branch-polish-tracker.md](2025.07.30-websocket-branch-polish-tracker.md)** - Comprehensive tracking document for debugging, polishing, and documenting completed WebSocket functionality (📋 planning phase)
- **[2025.07.24-websocket-async-bridge-implementation.md](2025.07.24-websocket-async-bridge-implementation.md)** - WebSocket implementation progress tracker through Phases 1, 2, and 2.5 (✅ completed)
- **[2025.07.12-progressive-tts-streaming-experimental-tracker.md](2025.07.12-progressive-tts-streaming-experimental-tracker.md)** - Firefox-first experimental implementation of true progressive audio streaming (✅ completed - integrated into main system)
- **[2025.07.12-tts-mode-switching-design.md](2025.07.12-tts-mode-switching-design.md)** - Add dynamic switching between OpenAI batch TTS and ElevenLabs streaming TTS (✅ completed)
- **[2025.07.12-tts-mode-switching-phase1-tracker.md](2025.07.12-tts-mode-switching-phase1-tracker.md)** - Phase 1 implementation tracker for TTS mode switching (✅ completed)
- **[2025.07.12-audio-to-speech-renaming-design.md](2025.07.12-audio-to-speech-renaming-design.md)** - Rename misleading "audio" terminology to accurate "speech" terminology for TTS functionality (✅ completed)
- **[2025.07.11-websocket-user-routing-architecture.md](2025.07.11-websocket-user-routing-architecture.md)** - User-centric event routing architecture to replace ephemeral WebSocket ID dependencies (✅ core phases completed)
- **[2025.07.01-fastapi-clock-events-research.md](2025.07.01-fastapi-clock-events-research.md)** - Research plan for implementing clock update events using existing WebSocketManager (✅ completed)

### Previous Development (2025.06)
- **[2025.06.20-claude-code-notification-system-design.md](2025.06.20-claude-code-notification-system-design.md)** - Real-time notification system design
- **[2025.06.20-claude-code-to-api-and-cli-integration.md](2025.06.20-claude-code-to-api-and-cli-integration.md)** - Claude Code integration documentation
- **[2025.06.03-websocket-tts-streaming-design.md](2025.06.03-websocket-tts-streaming-design.md)** - Real-time text-to-speech streaming over WebSockets

## Archived Documents

### Completed Work (2025.08)
- **[archived/2025.08.01-websocket-smoke-test-suite-design.md](archived/2025.08.01-websocket-smoke-test-suite-design.md)** - Comprehensive WebSocket smoke test suite implementation (✅ completed - 50 tests deployed with 92% success rate, production-ready regression detection)
- **[archived/2025.08.01-design-by-contract-audit.md](archived/2025.08.01-design-by-contract-audit.md)** - Design by Contract documentation implementation (✅ largely completed - 83 functions documented across 7 high/medium priority files, professional-grade specifications)

### Completed Work (2025.07)
- **[archived/2025.07.31-elevenlabs-tts-quality-optimization-plan.md](archived/2025.07.31-elevenlabs-tts-quality-optimization-plan.md)** - ElevenLabs TTS quality optimization implementation (✅ completed - Flash v2.5 model deployed with <200ms latency, provider switching operational)
- **[archived/2025.07.01-todo-and-running-queues-as-producer-consumer.md](archived/2025.07.01-todo-and-running-queues-as-producer-consumer.md)** - Producer-consumer queue implementation (6700x performance improvement)
- **[archived/2025.07.01-fastapi-clock-implementation-success.md](archived/2025.07.01-fastapi-clock-implementation-success.md)** - Success report documenting asyncio.create_task() pattern implementation
- **[archived/2025.07.01-queue-integration-plan.md](archived/2025.07.01-queue-integration-plan.md)** - Plan for connecting running queue and implementing background tasks in FastAPI

### Completed Work (2025.06)
- **[archived/2025.06.29-cosa-lupin-renaming-completion.md](archived/2025.06.29-cosa-lupin-renaming-completion.md)** - Project renaming completion report
- **[archived/2025.06.28-lupin-renaming-plan.md](archived/2025.06.28-lupin-renaming-plan.md)** - Project rebranding from Genie-in-the-Box to Lupin
- **[archived/2025.06.27-flask-elimination-plan.md](archived/2025.06.27-flask-elimination-plan.md)** - Plan to remove deprecated Flask infrastructure (completed)
- **[archived/2025.06.20-claude-code-notification-system-design-implementation-tracker.md](archived/2025.06.20-claude-code-notification-system-design-implementation-tracker.md)** - Implementation tracking for notification system (Phase 2 complete)
- **[archived/2025.06.17-fastapi-queue-implementation-plan.md](archived/2025.06.17-fastapi-queue-implementation-plan.md)** - Queue-based request handling in FastAPI
- **[archived/2025.06.16-fastapi-modular-refactoring-plan.md](archived/2025.06.16-fastapi-modular-refactoring-plan.md)** - Modular architecture refactoring

### Flask Migration (Completed 2025.06.28)
- **[archived/2025.05.19-flask-to-fastapi-migration-plan.md](archived/2025.05.19-flask-to-fastapi-migration-plan.md)** - Comprehensive Flask to FastAPI migration plan
- **[archived/2025.04.05-flask-to-fastapi-migration.md](archived/2025.04.05-flask-to-fastapi-migration.md)** - Early migration planning and considerations

### Early Development (2025.01)
- **[archived/2025.01.24-fastapi-refactoring-plan.md](archived/2025.01.24-fastapi-refactoring-plan.md)** - Initial FastAPI refactoring plans

## Document Conventions

- All documents follow the `YYYY.MM.DD-description.md` naming format
- Active documents represent ongoing or planned work
- Archived documents represent completed initiatives
- Each document should include a clear purpose and current status

