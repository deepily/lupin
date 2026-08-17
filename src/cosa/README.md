# CoSA: Collection of Small Agents

CoSA is a modular framework for building, training, and deploying specialized LLM-powered agents. It provides the infrastructure for [Lupin](https://github.com/deepily/lupin), a voice-first conversational AI system with trust-aware human-in-the-loop decision making.

<a href="docs/images/5-microphone-genie-robots.png" target="_blank">
  <img src="docs/images/5-microphone-genie-robots.png" alt="Genie robots with microphones" width="1024px">
</a>

## Overview

CoSA implements a collection of targeted agents, each specialized for specific tasks:
- Text generation and completion
- Mathematics and calculations
- Calendar management and scheduling
- Weather reporting
- Todo list management
- Code execution and debugging
- **Hybrid TTS Streaming**: Fast, reliable text-to-speech with no word truncation
- And more...

### TTS Implementation Architecture

The system includes two high-performance TTS solutions optimized for different use cases:

#### Hybrid TTS (OpenAI)
**Architecture**: `OpenAI TTS → FastAPI → WebSocket → Client`
- Server: `stream_tts_hybrid()` - forwards OpenAI chunks via WebSocket
- Client: Collects all chunks, then plays complete audio file
- **Benefits**: 50% faster than complete file approach, zero truncation, universal compatibility

#### Instant Mode TTS (ElevenLabs)
**Architecture**: `ElevenLabs Streaming API → FastAPI → WebSocket → Client`
- Server: Direct WebSocket streaming with progressive chunk delivery
- Client: Immediate playback of audio chunks as received
- **Benefits**: Ultra-low latency, real-time streaming, significantly faster than hybrid mode
- **Use Case**: Interactive conversations requiring immediate audio response

**Endpoints**: 
- `/api/get-audio` - Hybrid OpenAI approach for reliability
- `/api/get-audio-elevenlabs` - Instant ElevenLabs streaming for speed

## Project Structure

- `/agents`: Individual agent implementations
  - `agent_base.py`: Abstract base class for all agents
  - `llm.py`, `llm_v0.py`: LLM service integration (legacy)
  - `/v010`: Current agent architecture with Pydantic XML processing
  - `/io_models/`: Pydantic XML models and utilities
    - `xml_models.py`: Core XML response models with template generation
    - `utils/prompt_template_processor.py`: Dynamic template processing
  - `/v1`: New modular LLM client architecture
    - `llm_client.py`: Unified client for all LLM providers
    - `llm_client_factory.py`: Factory pattern for client creation
    - `token_counter.py`: Cross-provider token counting
  - Specialized agents for math, calendaring, weather, etc.
- `/app`: Core application components
  - `configuration_manager.py`: Settings management with inheritance
  - `util_llm_client.py`: Client for LLM service communication
- `/memory`: Data persistence and memory management
- `/rest`: REST API infrastructure
  - Queue management, WebSocket routers, authentication
  - Producer-consumer pattern with event-driven processing
- `/tools`: External integrations and tools
  - `search_gib.py`: Internal search capabilities
  - `search_kagi.py`: Integration with Kagi search API
- `/training`: Model training infrastructure
  - `peft_trainer.py`: PEFT (Parameter-Efficient Fine-Tuning) implementation
  - `quantizer.py`: Model quantization for deployment
  - `xml_coordinator.py`: Structured XML training data generation/validation
- `/utils`: Shared utility functions

## Getting Started

### Prerequisites

- Python 3.9+
- PyTorch
- Transformers library
- Hugging Face account (for model access)

For a complete list of dependencies, see the [requirements.txt](./requirements.txt) file.

### Installation

```bash
# Clone the repository
git clone git@github.com:deepily/cosa.git
cd cosa

# Install dependencies
pip install -r requirements.txt
```

### Usage

CoSA is designed to be used as a submodule/subtree within the parent "Lupin" project (formerly genie-in-the-box), but can also be used independently for agent development.

**TBD**: Usage examples and API documentation will be provided in future updates.

## LLM Model Training

CoSA includes tools for fine-tuning and deploying LLM models using Parameter-Efficient Fine-Tuning (PEFT):

```bash
# Example: Fine-tune a model using PEFT
python -m cosa.training.peft_trainer \
  --model "mistralai/Mistral-7B-Instruct-v0.2" \
  --model-name "Mistral-7B-Instruct-v0.2" \
  --test-train-path "/path/to/training/data" \
  --lora-dir "/path/to/output/lora" \
  --post-training-stats
```

For detailed instructions on using the PEFT trainer, including all available options, data format requirements, and advanced features like GPU management, please refer to the [PEFT Trainer README](./training/README.md).

## COSA Framework Code Flow Diagram

Based on analysis of the codebase, here's how the COSA (Collection of Small Agents) framework works:

### 1. Entry Points (FastAPI)

```
FastAPI Server (lupin_app/main.py) - CURRENT
     |
     ├── WebSocket endpoints
     ├── REST API endpoints
     └── Async handlers
     
Flask Server (app.py) - DEPRECATED/REMOVED
     ├── /push endpoint (migrated to FastAPI)
     ├── /api/upload-and-transcribe-* (migrated)
     └── Socket.IO connections (replaced with WebSockets)
```

### 2. Request Flow Architecture

```
User Request (voice/text)
     |
     v
MultiModalMunger (preprocessing)
     |
     v
TodoFifoQueue.push_job()
     ├── Check for similar snapshots
     ├── Parse salutations
     ├── Get question gist (via Gister)
     └── Route to agent via LLM
          |
          v
     Agent Router (LLM-based)
          ├── "agent router go to calendar" → CalendaringAgent
          ├── "agent router go to math" → MathAgent
          ├── "agent router go to todo list" → TodoListAgent
          ├── "agent router go to date and time" → DateAndTimeAgent
          ├── "agent router go to weather" → WeatherAgent
          └── "agent router go to receptionist" → ReceptionistAgent
```

### 3. Queue Management System

```
TodoFifoQueue (pending jobs)
     |
     v
RunningFifoQueue.enter_running_loop()
     ├── Pop from TodoQueue
     ├── Execute job (Agent or SolutionSnapshot)
     └── Route to appropriate queue:
          ├── DoneQueue (successful)
          └── DeadQueue (errors)
```

### 4. Agent Execution Flow

```
AgentBase (abstract)
     |
     ├── run_prompt() → LlmClient → LLM Service
     ├── run_code() → RunnableCode → Python exec()
     └── run_formatter() → RawOutputFormatter
          |
          v
     do_all() orchestrates the complete flow
```

### 5. Core Components

**ConfigurationManager**
- Singleton pattern
- Manages `lupin-app.ini` settings (formerly gib-app.ini)
- Environment variable overrides

**LlmClient/LlmClientFactory**
- Unified interface for multiple LLM providers
- Supports OpenAI, Groq, Google, Anthropic
- Handles streaming/non-streaming modes

**SolutionSnapshot**
- Serializes successful agent runs
- Stores code, prompts, responses
- Enables solution reuse

**Memory Components**
- `InputAndOutputTable`: Logs all I/O
- `EmbeddingManager`: Manages embeddings (singleton)
- `GistNormalizer`: Text preprocessing (singleton)
- `SolutionSnapshotManager`: Manages saved solutions

### 6. Data Flow Example

```
1. User: "What's the weather today?"
2. FastAPI receives request
3. MultiModalMunger processes input
4. TodoFifoQueue:
   - Checks for similar snapshots
   - No match found
   - Routes to weather agent via LLM
5. WeatherAgent created and queued
6. RunningFifoQueue executes:
   - Calls agent.do_all()
   - Agent queries weather API
   - Formats response
7. Results sent to DoneQueue
8. Audio response generated via TTS
9. Response sent to user
```

### Key Design Patterns

- **Singleton**: ConfigurationManager, EmbeddingManager, GistNormalizer
- **Abstract Factory**: LlmClientFactory
- **Template Method**: AgentBase.do_all()
- **Queue-based Architecture**: Async job processing
- **Serialization**: SolutionSnapshot for persistence

The framework elegantly handles voice/text input, routes to specialized agents, executes code dynamically, and maintains a memory of successful solutions for reuse.

## Development Guidelines

Please refer to [CLAUDE.md](./CLAUDE.md) for detailed code style and development guidelines.

## Research and Development

For current research and planning documents, see the [RND directory](./rnd/), which includes:

### Architecture and Refactoring
- [LLM Client Architecture Refactoring Plan](./rnd/2025.06.04-llm-client-architecture-refactoring-plan.md): Comprehensive plan for improving the v010 LLM client architecture
- [LLM Client Refactoring Progress](./rnd/2025.06.04-llm-client-refactoring-progress.md): Progress tracker for the LLM client refactoring project
- [LLM Refactoring Analysis](./rnd/2025-04-14_llm_refactoring_analysis.md): Analysis of LLM component refactoring needs
- [Agent Migration v000 to v010 Plan](./rnd/2025-05-13_agent_migration_v000_to_v010_plan.md): Migration strategy for agent architecture

### Implementation Plans
- [Screen Reader Agent Implementation Plan](./rnd/2025-04-14_screen_reader_agent_implementation_plan.md): Plan for screen reader accessibility agent
- [Agent Factory Testing Plan](./rnd/2025-05-15_agent_factory_testing_plan.md): Testing strategy for agent factory components
- [CI Testing Implementation Plan](./rnd/2025-05-19_ci_testing_implementation_plan.md): Continuous integration testing setup

### Analysis and Strategy
- [LLM Prompt Format Analysis](./rnd/2025-04-16_llm_prompt_format_analysis.md): Analysis of prompt formatting approaches
- [Prompt Templating Strategies](./rnd/2025-04-16_prompt_templating_strategies.md): Strategies for prompt template management
- [Python Package Distribution Plan](./rnd/2025-05-16_python_package_distribution_plan.md): Plan for package distribution strategy
- [Versioning and CI/CD Strategy](./rnd/2025-05-28_versioning_and_cicd_strategy.md): Version management and deployment strategy

### Release Notes
- [v0.1.7 PR Body — Tracking Branch](./rnd/2026.05.29-pr-body-v0.1.7-tracking.md): Compare URL + copy-paste PR body for the v0.1.7 → main merge

## Cross-Session AI Collaboration via cosa-voice MCP (May 2026)

CoSA now hosts a working substrate for multiple Claude Code sessions to coordinate
directly through directed messaging — a development practice we've started calling
**DM-as-mini-design-doc**.

On 2026-05-16, María 🌸 (Lupin session `3c9fce51`) and Tiberius 🌑 (planning-is-prompting
session `b714e138`) co-authored a discovery-surface expansion for the cosa-voice MCP
server entirely through cross-session DMs, using nothing but the `commons_send_to` /
`commons_ask_async` / `commons_post` tools that this repo provides:

- **María** drafted the MCP `instructions` field — grown from ~3k chars to ~21k
  chars across 10 sections (toolkit nav map, startup protocol, 3-tier autonomy
  model, DM workflow with receipt etiquette, interactive tool routing, 7
  failure-mode debugging patterns, cross-reference footer).
- **Tiberius** ran a 5-point prose review via DM. Five iterations of correction
  and counter-correction produced the **5-surface framework** — CLAUDE.md /
  MCP `instructions` / planning-is-prompting workflow / per-tool docstrings /
  per-turn rider — split by reading timing, not content type.
- **Two real bugs surfaced during the DM thread itself**: topic-file case
  fragmentation (`dm-Tiberius` vs `dm-tiberius` splitting one logical thread
  across two files) and `commons_post` body truncation observed mid-write at
  the topic-file level. Both filed durably to the Lupin bug-fix queue.
- **Six commons_* docstrings** were upgraded (`commons_who`, `commons_read`,
  `commons_post`, `commons_ask_sync`, `commons_ask_async`, `commons_send_to`)
  with tier markers, examples, inline failure-mode hints, threading callouts,
  and cross-reference footers — all per Tiberius's 7-priority review.

The CoSA-side infrastructure that makes this possible:

- `cosa/rest/commons_topic_watcher.py` — abstract base for daemon watchers
- `cosa/rest/commons_ack_watcher.py` — broadcast-ack tracker subclass
- `cosa/rest/commons_question_watcher.py` — register-question + answer-received tracker
- `cosa/rest/commons_activity_watcher.py` — Recent Activity WS push path (with consumer-side dedupe added 2026-05-16)
- `cosa/rest/commons_rate_limiter.py` — per-user + global caps
- `cosa/rest/routers/commons.py` — REST surface (broadcast, ack, register-question, DM dispatch with `_resolve_dm_recipient` + `RecipientResolutionError` contract)

The cosa-voice MCP wrapper itself lives in the parent Lupin repo
(`src/lupin_mcp/cosa_voice_mcp.py`); the cross-session collaboration substrate
that it exposes is what CoSA provides.

This workflow — DM thread as mini-design-doc, paired-by-DM-paired-by-commit,
iterative correction loop converging on sharper output than either persona
would produce alone — is now a replicable template for future cross-session
work. María and Tiberius plan to publish a workflow R&D doc covering the
template explicitly.

## What's New in v0.1.7 — Concurrent Jobs, Cross-Session Coordination & Multi-Repo Docs

The v0.1.7 cycle (2026-04-24 → 2026-05-28) is the largest CoSA development cycle to date,
organized around five feature pillars plus a broad hardening pass.

### CJ Flow Async Multi-Lane
- **Agentic pool** — `AgenticJobBase` jobs dispatch to a `ThreadPoolExecutor` (sized by the
  `cj flow max concurrent agentic jobs` INI key); the consumer thread returns immediately and a
  `Future.add_done_callback` drives the done/dead transition. Fast-lane `AgentBase` /
  `SolutionSnapshot` work stays inline and is never blocked by the pool.
- **Thread safety** — `FifoQueue` guards `queue_list` + `queue_dict` with a `threading.RLock`;
  all 9 `pop()` sites migrated to `delete_by_id_hash()` (head-of-queue is no longer deterministic
  under pool-callback concurrency).
- **Ghost-job sweeper** — daemon thread dead-letters jobs whose `Future` completed but never
  transitioned.
- **`ApiResourceManager`** — singleton centralizing per-provider rate-limit waits + call recording.
- **`GET /api/queue/pool-status`** — inflight/max workers, pending-in-pool, ApiResourceManager state.
- **Error-path hardening** — dead-queue refactor, consumer heartbeat, `do_all` re-raise across 8 subclasses.

### Inter-Session Commons (Phases 2–3)
- Daemon watchers: `commons_topic_watcher` (abstract base), `commons_ack_watcher`,
  `commons_question_watcher`, `commons_activity_watcher` (consumer-side dedupe).
- `commons_rate_limiter` (per-user + global caps) and `routers/commons.py` (broadcast, ack,
  register-question, DM dispatch with `_resolve_dm_recipient` + `RecipientResolutionError` 422 contract).
- Broadcast munger preserving `@-mention` syntax; broadcast fan-out dedupe across HTTP + WS push paths.

### Per-Session Voice Personas
- Voice allocation router + helpers with notification stamping.
- `/clear` preservation (re-assigns the prior persona on context clear); env-var allocator +
  pool expansion; **Sam-as-overflow** allocator; stale-bridge prune with mtime TTL guard.
- `/sample` endpoint for the dev-tools persona-reference page; `display_name` plumbing.

### Speakerphone Solo/Chorus Refactor
- Router rename `conversation_mode` → `speakerphone`; `get_tts_interaction_mode` helper;
  mutex auto-displace + WS dispatch dedup; symmetric self-exit signal fix.

### Doc-Viewer Multi-Repo Scope Unification
- `_scope_registry` + `_dir_listing`; JWT-gate + ~30-pattern secrets/floor blocklist.
- Path-prefix URL routing (`?path=<project>/<rel>`); legacy `ALLOWED_FILES` / `?scope=` retired.
- Pydantic docview manifest authority; image/PNG rendering via `FileResponse`;
  `/api/docs/file` + `/api/docs/health` with whitelist + traversal protection.

### Tooling & Hardening
- **Bounded-CC billing** — `ClaudeCodeJob` BOUNDED path surfaces `cost_summary`; CC card
  normalization Phase 4 (canonical `/api/claude-code/submit`).
- **Daily LoC Delta tool** — `git_loc_delta` package + CLI, per-branch `--plot`, cross-repo aggregator.
- **Model-server carve-out** — `SpeechToTextProvider` + `EmbeddingProvider` URL resolver, process-aware routing.
- **Multiplexer** — `/app/multiplexer` page route + `GET /api/multiplexer/config`.
- **BFE/TFE test-suite remediation** — Phase 1–3 cluster fixes, INI proposal-cap, verifier retry.
- **Misc**: bcrypt pinned to 4.3.0, cross-job `sender_id` ContextVar isolation, `ask_yes_no`
  "Neither" affordance, WS reconnect circuit-breaker Phase 5 (close codes 4001/4002),
  notification dispatch unification, history.md archive (2026-02-28 → 2026-04-24).

## What's New in v0.1.5 — Voice-First Human in the Loop

### Trust-Aware Decision Proxy
- **Universal Prediction Engine (UPE)** — 7 prediction slices with response_type filtering to prevent cross-type contamination
- **Bayesian Beta-Bernoulli Trust Model** — Per-agent trust learning with conjugate prior updates
- **Thompson Sampling** — Exploration-exploitation balance for auto-approve vs. escalate decisions
- **Conformal Prediction** — Calibrated confidence intervals with statistical guarantees
- **pgvector Preference Embeddings** — Semantic similarity search with `response_type` filtering and MC option validation
- **L1-L5 Trust Escalation** — Five trust levels from "always ask" to "full autonomy" with circuit breaker pattern

### Integration Test Infrastructure
- **Hot-Swap Config** — Running dev server toggles between config blocks at runtime via `/api/init?config_block_id=...`
- **`GET /api/server-info`** — Unauthenticated introspection endpoint (config block, masked DB URL, environment)
- **`swap_database()`** — Runtime database environment switching (development/testing/production)
- **Database Disambiguation** — `lupin_db` split into `lupin_db_dev` and `lupin_db_prod`

### Credential Consolidation
- **Unified `~/.lupin/config`** — Three credential stores collapsed into one file
- **Fail-hard on missing config** — Removed all legacy fallbacks; `FileNotFoundError` with migration instructions
- **Strict Project Detection** — `KNOWN_PROJECTS` registry + `is_known_project()` for MCP validation

### Voice & Notification Infrastructure
- **`user_initiated_message`** type for voice input routing
- **`QualifierClassification`** model + `display_qualifier_widget` notification field
- **Programmatic session ID** regex tightened to require hyphen
- **Dead event cleanup** — Removed `active_conversation_changed` (emitted but never subscribed)

### New Agents & Agent Enhancements
- **SWE Team Agent** — 4-phase agentic software development with trust-aware decision proxy
- **Everyday Calculator Agent** — Natural language calculator with MathAgent fallback
- **CRUD for DataFrames Agent** — Voice-controlled create/read/update/delete for Pandas DataFrames
- **Notification Proxy Agent** — Phi-4 LLM fuzzy script matching for automated interactive testing

### CJ Flow (COSA Jobs Flow)
- **Agentic Job System** — Background execution engine for long-running Claude Agent SDK tasks
- **Deep Research + Podcast Generator** — Research-to-podcast chained pipeline
- **Dry-Run Mode** — Test agentic jobs without API costs
- **`job_state_transition`** events for real-time job status via WebSocket

### Testing (2,075+ unit tests)
- +905 unit tests across trust engine, session bridge, hooks, credentials, prediction engine
- WebSocket tests: 50/50 passing
- Integration tests: 136 passed (comprehensive auth, admin, queue filtering)
- Interactive proxy tests: 12 scenarios across Calculator, CRUD, and Expediter agents

### Earlier Milestones

- **v0.1.4** — cosa-voice MCP Server, Runtime Argument Expeditor, batch voice questions
- **v0.1.3** — CJ Flow agentic job system, JWT WebSocket auth, unified LoRA training
- **v0.1.2** — LanceDB migration with 100% feature parity
- **v0.1.1** — WebSocket FastAPI test suite
- **v0.1.0** — Complete Flask elimination, FastAPI-only architecture

### Infrastructure Foundation (pre-v0.1.0)
- **Pydantic XML Migration** — All 8 agents migrated with 4 core models and 3-tier strategy
- **Design by Contract Documentation** — 100% coverage across all 73 Python modules
- **Modular LLM Client Architecture** — Vendor-agnostic support for OpenAI, Groq, Anthropic, Google
- **Producer-Consumer Queue** — 6,700x performance improvement via event-driven processing
- **WebSocket User Routing** — Persistent user-centric event routing with multi-session support

## License

This project is licensed under the terms specified in the [LICENSE](./LICENSE) file.