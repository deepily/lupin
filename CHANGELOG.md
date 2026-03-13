# Changelog

All notable changes to the Lupin project are documented in this file.

---

## v0.1.5 (March 2026) — Voice-First Human in the Loop

### Claude Code Voice Loop (Flagship)
- **6 System Hooks** — Full bidirectional voice inside Claude Code sessions: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `PermissionRequest`, `UserPromptSubmit`
- **cosa-voice MCP Server** — 5 voice tools (`notify`, `converse`, `ask_yes_no`, `ask_multiple_choice`, `ask_open_ended_batch`) bridging voice I/O into every coding session
- **Session Bridge** — Automatic registration and lifecycle management with stable session IDs across context clears
- **Voice Injection** — tmux-based voice input into idle Claude Code sessions
- **Stop Hook Gisting** — Ultra-short TTS summaries of completed work via frontier model distillation
- **JSONL Stream Logging** — Structured hook event logging for debugging and analytics
- **Hook Credentials** — Unified credential access for all hook scripts

### Trust-Aware Decision Proxy
- **Universal Prediction Engine** — 7 prediction slices with 87 unit tests and 21 end-to-end tests
- **Bayesian Beta-Bernoulli Trust Model** — Per-agent trust learning with conjugate prior updates
- **Thompson Sampling** — Exploration-exploitation balance for auto-approve vs. escalate decisions
- **Conformal Prediction** — Calibrated confidence intervals with statistical guarantees
- **LanceDB Preference Embeddings** — Semantic similarity with response_type filtering to prevent cross-type contamination
- **L1-L5 Trust Escalation** — Five trust levels from "always ask" to "full autonomy" with circuit breaker pattern

### Credential Consolidation
- **Unified `~/.lupin/config`** — Three credential stores (`~/.lupin/credentials.ini`, `~/.notifications/config`, deprecated `~/.lupin/config`) collapsed into one file
- **lupin-config CLI** — `init`, `migrate`, `show` subcommands with automatic backup and `chmod 600` enforcement
- **Fail-hard on missing config** — Removed all legacy fallbacks; missing config raises `FileNotFoundError` with migration instructions

### Session Identity Architecture
- **Stable Session ID Lockfile** — Write-once atomic `open('x')` (O_CREAT|O_EXCL) prevents ID drift across context clears
- **Hook Session ID Drift Fix** — All 6 hooks resolve transient CC session_id to stable lockfile ID via `resolve_stable_session_id()`
- **Listener Drift Fix** — `accepted_ids` set allows WebSocket listeners to match on both stable and transient hashes
- **Duplicate Session Card Fix** — Env file now writes stable ID instead of transient, preventing split identity after context clear

### Integration Test Infrastructure
- **Hot-Swap Config** — Running dev server toggles between `[Lupin: Development]` and `[Lupin: Testing]` config blocks at runtime via `/api/init?config_block_id=...`
- **`GET /api/server-info`** — Unauthenticated introspection endpoint returning config block, masked DB URL, and environment
- **Database Disambiguation** — `lupin_db` split into `lupin_db_dev` and `lupin_db_prod` with updated Docker, shell scripts, and 16 documentation references
- **Hardened `clean_test_db`** — Safety assertion verifies `lupin_db_test` in engine URL before destructive operations

### Testing Expansion (1,170 to 2,075+ unit tests)
- +905 unit tests across trust engine, session bridge, hooks, credentials, prediction engine, and more
- WebSocket tests: 50/50 maintained
- Integration tests: 43 to 136+ (comprehensive auth, admin user management, queue filtering)
- Interactive proxy tests: 12 scenarios across Calculator, CRUD, and Expediter agents
- Smoke test remediation: 27/27 Lupin smoke tests passing

### Infrastructure
- **MCP Strict Project Detection** — Repository account validation at startup with urgent notification on failure
- **Dead WebSocket Event Cleanup** — Removed `active_conversation_changed` and unhandled event types
- **History Archival System** — Automated history.md management with token budgeting and monthly archives
- **Human-Readable Hook Timestamps** — Reformatted to `2026.03.12 @ 17:28 18,805ms` format

---

## v0.1.4 — End-to-End Voice I/O for Agentics

### cosa-voice MCP Server
- Full voice I/O integration for Claude Code workflows via MCP protocol
- Notification Proxy Agent for automated proxy during testing and production
- Runtime Argument Expeditor — LLM-powered gap analysis that asks users for missing arguments via voice
- Batch Open-Ended Questions — multi-question voice collection on a single screen (`ask_open_ended_batch`)
- Yes/No Comments — optional qualifying comments on yes/no blocking notifications

### New Agents
- **SWE Team Agent** — 4-phase agentic software development team (foundation, delegation, tester verification, trust-aware decision proxy) with L1-L5 trust tracking, circuit breaker, and ratification API
- **Everyday Calculator Agent** — Natural language calculator with MathAgent fallback, 508 LoRA templates, full voice routing (31 implementation steps complete)
- **CRUD for DataFrames Agent** — Voice-controlled create/read/update/delete for Pandas DataFrames with confirmation dialogs for destructive operations
- **Notification Proxy Agent** — Phi-4 LLM fuzzy script matching for automated interactive testing with Q&A scripts

### Testing Expansion (881 to 1170 unit tests)
- +289 unit tests across SWE Team (214), Calculator (94), CRUD (73+), Expeditor (123), Proxy (49+)
- 12-scenario proxy integration test combining Calculator, CRUD, and Expediter agents
- Automated interactive testing framework with 3-tier strategy chain (exact, fuzzy, fallback)
- Comprehensive testing documentation (`automated-interactive-testing.md`, smoke test README)

### Training Pipeline
- 39,871 training examples — 35 commands including Calculator (1,500 templates) and Claude Code intents
- PEFT Phase 2 — results dashboard, explicit routing phrases, quantization strengthening (1,200 to 1,500 samples/command)
- Post-quantization GPU memory fix — explicit `release_gpu_memory()` for vLLM OOM prevention

### Infrastructure
- Local GPU Embeddings — CodeRankEmbed + nomic-embed-text-v1.5 (7-398x faster than OpenAI API)
- LanceDB Dimension Standardization — all providers on 768 dims with validation
- CJ Flow Bounded Job Packaging — complete guide for packaging new QueueableJob types
- Consolidated Notification API Reference — 4,033-line comprehensive doc with 5 Mermaid diagrams

---

## v0.1.3 — Agentic Job System (CJ Flow)

### Core
- **Claude Code Job Integration** — Full Claude Agent SDK integration with QueueableJob protocol (22 attributes + 3 methods)
- **Deep Research Agent** — Background research jobs with automatic report generation
- **Podcast Generator** — Convert research documents to audio podcast format
- **Research-to-Podcast Workflow** — Chained pipeline from research to podcast in one click
- **Dry-Run Mode** — Test all agentic jobs without API costs (enabled by default in UI)

### WebSocket Infrastructure
- JWT Authentication for secure WebSocket connections (replaces mock tokens)
- `job_state_transition` events for real-time job status updates
- 100% WebSocket test coverage — all 50 smoke tests passing (up from 46%)

### Testing and Quality
- Unit Tests: 195/195 (100%) — complete test infrastructure remediation
- WebSocket Tests: 50/50 (100%) — JWT auth migration complete
- Integration Tests: comprehensive API endpoint testing with auth

### Training Pipeline
- Unified LoRA training — single pipeline for voice commands + agentic job intents
- 40,258 training examples including 600 agentic command examples
- Agentic intent recognition — "Go to deep research", "make a podcast about..."

### Notifications UI
- Compact dropdown controls — Task Type and Flow Type selectors (replaces cluttered radio buttons)
- cosa-voice MCP integration — voice I/O for Claude Code workflows via MCP server

---

## v0.1.2 — LanceDB Migration

- **LanceDB Migration Complete** — Successfully migrated solution snapshots from file-based storage to LanceDB vector database with 100% feature parity and massive performance improvements
- **Configuration-Based Backend Switching** — Seamless switching between storage backends via simple configuration change (`solution snapshots manager type = lancedb | file_based` in `lupin-app.ini`)

---

## v0.1.1 — WebSocket Test Suite

- **WebSocket FastAPI Test Suite** — Comprehensive diagnostic and testing tools for WebSocket functionality

---

## v0.1.0 — FastAPI Migration

- **Complete Flask Elimination** — FastAPI-only architecture running on port 7999
- **COSA Integration** — Modular agent framework with WebSocket support for real-time communication
