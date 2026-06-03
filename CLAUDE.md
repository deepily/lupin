# LUPIN DEVELOPMENT GUIDE

## COMMANDS
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (Runs on port 7999)
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Docker build: `docker build -f docker/lupin/Dockerfile .`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`
- Install cosa-voice MCP (global): `src/scripts/install-cosa-voice.sh` (user scope, all repos)
- Regenerate API docs: `src/scripts/generate-api-docs.sh` (requires server on port 7999, `--offline` for saved JSON)

## CLAUDE CODE SLASH COMMANDS
- `/smoke-test-baseline [scope]` - Establish comprehensive baseline before changes
  - **scope**: `full` (Lupin + COSA) or `lupin` (Lupin-only), default: `full`
  - Creates timestamped logs and baseline report in `src/rnd/`
  - Pure data collection - no remediation attempts
- `/smoke-test-remediation [baseline_report] [scope]` - Verify and fix post-change issues
  - **baseline_report**: Path to baseline report (auto-detects latest if not provided)
  - **scope**: `FULL|CRITICAL_ONLY|SELECTIVE|ANALYSIS_ONLY`, default: `FULL`
  - Compares against baseline, identifies regressions, performs systematic remediation
- `/lupin-new-claude-agent-sdk-voice-workflow` - Create new agentic services with voice I/O
  - Interactive workflow for building Claude Agent SDK background jobs
  - Guides through phases: discovery, foundation, notifications, queue integration
  - **Canonical doc**: `src/workflow/agentic-voice-workflow.md`
  - **Reference agents**: `src/cosa/agents/deep_research/`, `podcast_generator/`

## CJ FLOW (COSA JOBS FLOW)

CJ Flow is Lupin's unified work queue system. All jobs that implement the `QueueableJob` protocol flow through it.

**Queue Pipeline**: todo → running → done/dead
**Protocol**: `QueueableJob` (22 attrs + 4 methods) — see `src/cosa/rest/queue_protocol.py`

**Dispatch architecture (v0.1.7+)**: `RunningFifoQueue._process_job(job)` dispatches by `isinstance`:
- `AgenticJobBase` → `_submit_agentic_job` → `ThreadPoolExecutor` (the **agentic pool**, size = `cj flow max concurrent agentic jobs` INI key, prod default `= 1`, `[Lupin: Development]`/`[Lupin: Testing]` override to `= 3`). Consumer thread returns immediately; `Future.add_done_callback` fires `_on_agentic_complete` which calls `_transition_to_done` or `_transition_to_dead`.
- `AgentBase` / `SolutionSnapshot` → inline fast-lane on the consumer thread (unchanged). Pool does NOT block fast-lane.

**Thread safety (v0.1.7+)**: `FifoQueue` has `threading.RLock` protecting `queue_list` + `queue_dict`. Pool workers and consumer thread can mutate concurrently. All 9 `self.pop()` sites in `running_fifo_queue.py` migrated to `self.delete_by_id_hash(job.id_hash)` — head-of-queue is no longer deterministic under pool-callback concurrency.

**Ghost-job sweeper (v0.1.7 Phase 3)**: daemon thread on `RunningFifoQueue` runs every `cj flow ghost job sweep interval seconds` (default 30s). Scans `_agentic_futures` for entries whose `Future.done()` is True but whose job is still in running queue — dead-letters them via `_transition_to_dead`. Suspenders to the callback's defensive belt.

**Rate-limit / API contention (v0.1.7 Phase 3)**: `ApiResourceManager` singleton at `src/cosa/utils/api_resource_manager.py` centralizes per-provider waits + call recording. Deep Research migrated (`await get_arm().acquire("anthropic_web_search")` + `get_arm().record_call(...)`). Podcast/Presentation/BFE/TFE/ClaudeCode stay on legacy per-agent `_call_with_retry` patterns; two-path invariant documented in `src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/01-design-review.md §3a`.

**Observability (v0.1.7 Phase 3)**: `GET /api/queue/pool-status` (JWT) returns `{inflight_agentic_jobs, max_agentic_workers, pending_in_pool, api_resource_manager: {...}}`.

**Job Types Handled**:
- **AgentBase** — Traditional sync agents (MathAgent, CalendarAgent, DateAndTimeAgent, etc.) — run inline on consumer
- **SolutionSnapshot** — Cached solution playback from prior runs — run inline on consumer
- **AgenticJobBase** — Long-running async jobs (DeepResearchJob, PodcastGeneratorJob, etc.) — run in agentic pool
- **ClaudeCodeJob** — Claude Agent SDK tasks in BOUNDED (fire-and-forget) or INTERACTIVE (bidirectional) mode — rides the agentic pool

**Key Files**:
- `src/cosa/rest/queue_protocol.py` — QueueableJob protocol definition
- `src/cosa/agents/agentic_job_base.py` — Abstract base for long-running jobs
- `src/cosa/rest/agentic_job_factory.py` — Agentic job creation factory
- `src/cosa/rest/todo_fifo_queue.py` — Ingress queue + agent routing
- `src/cosa/rest/running_fifo_queue.py` — Execution engine + pool + ghost sweeper + transition primitives
- `src/cosa/rest/queue_consumer.py` — Background consumer thread
- `src/cosa/utils/api_resource_manager.py` — ApiResourceManager singleton (v0.1.7 Phase 3)

**Architecture diagrams (before vs after v0.1.7)**: `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` — ✅ Implementation Complete banner with full before/after Mermaid.

**Packaging Guide**: `src/rnd/v0.1.4/2026.02.12-cj-flow-bounded-job-packaging-guide.md`

## COST MODEL — BOUNDED CC vs FIREWALLED SDK

Two LLM-cost paths exist in Lupin. Knowing which one a feature lands on is a design-time concern, not a runtime detail.

| Path | Auth | Billing |
|---|---|---|
| **Bounded `ClaudeCodeJob`** (CJ Flow, `task_type=BOUNDED`) | Claude Code CLI / Claude Agent SDK using Max-subscription OAuth | **Covered by Max 200 plan — zero per-token cost** |
| **Direct Anthropic SDK** (`AsyncAnthropic( api_key=… )`) | `ANTHROPIC_API_KEY_FIREWALLED` env var | **Billed per token against the firewalled Anthropic account** |

**Empirical confirmation (2026-05-12)**: A 10-job probe reported $2.0514 in SDK `cost_usd` telemetry while the Anthropic console credit balance moved **$0.00**. Forensic record: `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md`.

The "firewalled" naming is intentional defense-in-depth: the API key is stored under `ANTHROPIC_API_KEY_FIREWALLED`, **not** the bare `ANTHROPIC_API_KEY` that the Anthropic SDK auto-discovers. The CC CLI ignores the firewalled name and uses OAuth instead. Verbatim per `src/cosa/agents/deep_research/__init__.py:27`: "NEVER use ANTHROPIC_API_KEY - that is reserved for Claude Code CLI."

### Mandate: prefer bounded CC when migrating or designing a new LLM-driven agent

The bounded CC pattern is the cost-optimal default for LLM-driven agents that:

1. Express as a self-contained prompt with bounded turn count
2. Fit Claude Code's tool surface (Read / Write / Bash / Grep / WebSearch / WebFetch / etc.)
3. Tolerate ~1-3s SDK-subprocess spawn overhead per invocation
4. Use Anthropic-backed models only

Already migrated: **BFE** (`src/cosa/agents/bug_fix_expediter/`), **TFE** (`src/cosa/agents/test_fix_expediter/`).

Migration candidates (tracked in TODO.md): **Deep Research**, **podcast script generation**, **presentation content generation**.

**Framing**: this is a **cost-shift, not zero-cost**. The Max 200 plan is a fixed monthly bill. Migrations convert per-token metered spend into already-paid fixed cost. Never describe a migration as "free" — describe it as "covered by existing fixed cost."

### When NOT to migrate

- High-frequency tiny calls (>~10 QPS) — subprocess spawn overhead dominates. Keeps: `notification_proxy/strategies/llm_fallback.py`, `decision_proxy/`.
- Hard latency budget < ~2 seconds.
- Non-Anthropic models required (OpenAI/Groq/Mistral/etc. — Max plan only covers Claude).
- Token-by-token streaming UX (bounded CC returns on completion, no progressive streaming).

### Off-peak scheduling rule (operational)

Max-plan usage has rolling-window limits. Batch bounded jobs running during Rick's interactive peak window can throttle his real Claude Code work.

- **Peak (avoid scheduling here)**: 9 PM – 12 AM EDT
- **Optimal (schedule batch work here)**: 12 AM – 9 AM EDT (Rick asleep, zero interactive use)
- **Acceptable**: 9 AM – 9 PM EDT (some interactive use but well below peak)

**Rule**: any non-interactive bounded job (batch generation, scheduled regression sweeps, podcast/presentation/research) MUST set `scheduled_at` to the post-midnight window via `/api/claude-code/submit` (field defined at `src/cosa/rest/routers/claude_code_queue.py:49`). User-clicked synchronous bounded jobs are exempt.

Example:
```json
{
  "prompt"       : "…",
  "task_type"    : "BOUNDED",
  "scheduled_at" : "2026-05-13T02:30:00-04:00"
}
```

**Mandate for new design**: any proposal for a new LLM-driven feature MUST first answer "can this be a bounded CC job?" and document the answer. If "no", document which guardrail it hits.

## CODE STYLE
- **Imports**: Group by stdlib, third-party, local
- **Naming**: snake_case for functions, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **File Naming**:
  - Python files: Use underscores as separators (e.g., `example_implementation.py`)
  - All other files: Use dashes as separators (e.g., `websocket-design.md`, `lupin-app.ini`)
  - Date prefixes: Use YYYY.MM.DD format (e.g., `2025.06.03-websocket-design.md`)
- **Formatting**: 4 spaces indentation, spaces around operators, spaces inside brackets
- **Error handling**: Catch specific exceptions, include context in error messages
- **Logging**: Currently uses print() statements rather than a logging framework
- **Types**: Dynamic typing is used (no type annotations)
- **Documentation**: Add docstrings to new functions and classes, follow existing style
- **XML Formatting**: Use XML tags for structured responses in agent communication

## CONFIGURATION
- Config files: `src/conf/lupin-app.ini` and `src/conf/lupin-app-splainer.ini`
- Environment variables override config file settings
- Use `ConfigurationManager` to access config values

## PROJECT STRUCTURE
- `/src/fastapi_app/`: FastAPI application directory
  - `/src/fastapi_app/main.py`: Main FastAPI server entry point
  - `/src/cosa/rest/routers/`: API endpoint routers
- `/src/cosa/`: Contains the CoSA (Collection of Small Agents) framework
  - **Folded into the Lupin mono-repo (2026-05-29)**: `src/cosa/` is now a regular
    in-tree directory tracked by the Lupin repository — it is **no longer a separate
    git repo/submodule**. Manage its files AND its git operations exactly like any
    other Lupin source (stage/commit/push normally). The former CoSA repo's full
    history is preserved off-tree at `/mnt/DATA02/cosa-git-archive-2026.05.29/`.
  - CoSA retains its own README.md and CLAUDE.md (historical; the submodule guidance
    inside `src/cosa/CLAUDE.md` is superseded by this mono-repo state).
- `/src/cosa/agents/`: Agent implementations (math, calendar, deep_research, podcast/presentation generators, BFE/TFE, etc.)
- `/src/cosa/orchestration/`: Claude Code dispatch + CJ Flow task orchestration
- `/src/cosa/rest/`: FastAPI routers, queues, and DB repositories (queue pipeline, notifications, auth)
- `/src/cosa/config/`: ConfigurationManager + config cache registry
- `/src/cosa/memory/`: Data persistence and memory management
- `/src/cosa/crud_for_dataframes/`: DataFrame-backed CRUD agents and operations
- `/src/cosa/repo/`: Codebase-analysis tools (branch + directory LoC analyzers)
- `/src/cosa/training/`: Model-training utilities (PEFT trainer, HF downloader, quantizer)
- `/src/cosa/tools/`: External integrations and tools
- `/src/cosa/io/`: Input/output helpers
- `/src/cosa/utils/`: Shared utility functions
- `/src/cosa/docs/`, `/src/cosa/history/`, `/src/cosa/rnd/`, `/src/cosa/tests/`: documentation, history, R&D, and tests
- `/src/lib/clients/`: Client interface implementations

## DEBUGGING
- Set `debug=True` and `verbose=True` parameters in class instantiations
- Use `du.print_banner()` from `utils.py` for formatted console messages

## WEBSOCKET DEVELOPMENT NOTES
- **Architecture**: Dual-session design with user-centric routing (see `/src/docs/websocket-architecture.md`)
- **Event System**: Subscription-based filtering prevents clients from receiving unwanted events
- **Session Management**: localStorage-based persistence across page reloads using "adjective noun" format (e.g., "wise penguin")
- **Authentication**: All connections require `auth_request` with Bearer token: `Bearer mock_token_email_{email}`
- **Endpoints**: 
  - `/ws/queue/{session_id}` - Main application WebSocket (queue, notifications, system events)
  - `/ws/audio/{session_id}` - Audio-only WebSocket (TTS streaming, audio events)
- **Development Tips**:
  - Enable `app_debug = true` in lupin-app.ini for faster time updates (5s vs 60s)
  - Use browser dev tools Network → WS tab to monitor WebSocket traffic
  - Check console for authentication success/failure messages
  - Verify session ID format matches pattern: `wise penguin`, `clever dolphin`, etc.
- **Common Issues**:
  - WebSocket connection fails → Check server running on port 7999
  - No events received → Verify authentication succeeded and events are subscribed
  - Session conflicts → Clear localStorage and refresh page
  - Audio streaming issues → Check both queue and audio WebSocket connections
- **Event Debugging**: See `/src/docs/websocket-troubleshooting.md` for comprehensive debugging procedures
- **Configuration**: All WebSocket settings in lupin-app.ini under websocket_* keys

## NOTIFICATION SYSTEM
- **API Reference**: `src/docs/notification-api.md` (comprehensive one-stop reference)
- **WebSocket Events**: `src/docs/websocket-events.md` (event catalog)
- **Agentic Voice Integration**: `src/workflow/agentic-voice-workflow.md`
- **Decision Proxy Admin Guide**: `src/docs/proxy-admin-guide.md` (Trust Dashboard + Ratification how-to)
- **Interactive Proxy Testing**: `src/docs/automated-interactive-testing.md` (proxy auto-answer testing guide)
- **R&D Planning Docs**: `src/rnd/v0.1.0/2025.10.15-sse-notifications/` (historical)

## STARTUP PROCEDURE
- The first thing you should do when you start a session is read the global Claude configuration file and follow its instructions.
- **HISTORY FILE READING**: Read the main history file (`/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`) which contains recent 30-day context and links to archived periods
- **IMPLEMENTATION DOCUMENT**: Read the current implementation document referenced at the top of history.md
- **ARCHIVE ACCESS**: If deeper historical context needed, follow links to `history/YYYY-MM-history.md` files
- **IGNORE SUB-REPO HISTORIES**: Do NOT read these sub-repository history files as they are managed separately:
  - `src/lupin-plugin-firefox/history.md` (Firefox plugin sub-repo)
  - `src/lupin-mobile/history.md` (Mobile app sub-repo)
  - (`src/cosa/history.md` is **no longer** a sub-repo history — CoSA folded into the mono-repo 2026-05-29; it is now a normal in-tree doc.)

## PROJECT SHORT NAMES
- This repo's SHORT_PROJECT_PREFIX is [LUPIN]

## REPOSITORY RELATIONS
- There is another repo that's a part of the larger project contained in the directory `lupin-plugin-firefox`
- This repo must be managed separately and cannot be managed by Claude

## RUNNING/TESTING FASTAPI APPLICATIONS
- Please assume that there is a Fast API server instance bound to port 7999. I will start and stop it if needed. You never need to spin up another instance unless it's for a ephemeral use on port 8000.
- **Before clicking Resume on any TFE/BFE stalled job, or before scheduling a live E2E run on `:8000`**, run `src/scripts/preflight-test-container.sh` (or `pytest src/tests/smoke/test_container_preflight.py -v`). This catches docker-compose.yml drift — cases where a `.git`, credentials, or other bind-mount change has not been applied to the running container because only `docker rm -f` + `docker compose up -d` picks up new mounts (not `docker restart`). Failure output includes the exact remedy.
- **Server lifecycle (when does a change land? when do I bounce? which command?)**: See skill `server-lifecycle` — encodes the per-server decision matrix (`:7999` dev with `--reload` ON vs `:8000` test with `reload=False` for snapshot isolation), the "never volunteer a `:7999` bounce" rule, the queue-check courtesy, and the `:8000` monopolize-mode protocol. Auto-fires on bounce/restart/refresh/rebuild phrasing including ASR variants ("doctor" → "Docker").

## GIT REPOSITORY MANAGEMENT

**CRITICAL**: This project contains multiple nested Git repositories that must be managed separately.

### Repository Structure

**Parent Repository** (Manage with /plan-session-end):
- **Name**: Lupin (evolved from Genie-in-the-Box)
- **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/`
- **Prefix**: [LUPIN]
- **Git Operations**: Managed normally via `/plan-session-end` workflow

**Nested Repositories** (DO NOT manage from parent context):

> **CoSA was folded into the Lupin mono-repo (2026-05-29)** and is **no longer a
> nested repo** — manage `src/cosa/` as normal in-tree Lupin source. Only the two
> repos below remain nested/separately-managed.

1. **Firefox Plugin**
   - **Location**: `/src/lupin-plugin-firefox/`
   - **Management**: Separate repository, managed independently
   - **History**: Has own history.md (DO NOT read from Lupin context)

2. **Mobile App**
   - **Location**: `/src/lupin-mobile/`
   - **Management**: Separate repository, managed independently
   - **History**: Has own history.md (DO NOT read from Lupin context)

### How /plan-session-end Handles Nested Repos

The `/plan-session-end` workflow has been configured with nested repository awareness:

**During session-end workflow**:
1. Wrapper passes nested repo paths to canonical workflow
2. Canonical workflow detects changes in nested repos
3. Nested repo changes are acknowledged but NOT committed
4. Only parent Lupin repo changes are staged/committed
5. User is reminded to manage nested repos separately

**What you'll see**:
```
⚠️ Detected changes in nested repositories:
• /src/lupin-mobile/ (1 new file)

These are separate Git repositories and will not be included in this commit.
Reminder: Manage nested repositories in their own sessions/contexts.
```

**Git Safety Rules**:
- ✅ Stage/commit/push changes in parent Lupin repo
- ❌ Never run git commands in nested repo directories from parent context
- ✅ Nested repos must be managed when working directly in their contexts
- ✅ `/plan-session-end` automatically filters nested paths from git operations

### Detection Command

If you need to verify nested repositories:
```bash
# Find all nested .git directories
find . -name ".git" -type d | grep -v "^./.git$"
```

### Working in Nested Repositories

**When working in Firefox Plugin** (`cd src/lupin-plugin-firefox/`):
- Manage as independent project
- Has own git history and workflows

**When working in Mobile App** (`cd src/lupin-mobile/`):
- Manage as independent project
- Has own git history and workflows

## TESTING VENUES

**MANDATE**: Every automated test runs on exactly one of two servers. Pick by rubric, never by habit.

### :7999 (dev) — AI-discretionary

The AI may run these at any time without asking the user.

Eligible **iff all three**:
- No persistent-state mutation (no DB writes outliving the test, no writes outside `/tmp`, no real-work queue enqueues).
- Runtime ≤ 2 minutes end-to-end.
- No monopoly requirement.

Suites that qualify:
- `pytest src/tests/unit/`
- Inline `quick_smoke_test()` blocks + `py_compile` + import-chain checks
- `src/tests/smoke/test_calculator_live_pipeline.py`
- `src/tests/smoke/test_container_preflight.py`
- `src/tests/websocket_smoke/` (run via `src/scripts/run-websocket-smoke-tests.sh`)

### :8000 (test) — monopolize mode, scheduled only

Submit via `POST /api/test-suite/submit` with a `scheduled_at` the user has confirmed does not overlap other scheduled runs. **Never** inject via ad-hoc curl, direct queue push, or in-process server instantiation — side-door injection collides with in-flight scheduled runs and poisons both.

Eligible if **any**:
- Mutates persistent state (DB rows, shared files, LLM API spend, enqueues jobs).
- Runtime > 2 minutes.
- Needs server monopoly (E2E UI, integration, regression sweeps).

Suites that qualify:
- `src/tests/smoke/test_proxy_integration.py` (any scenario — CRUD + expediter mutate state)
- `src/tests/run-integration-tests.sh` (final merge gate)
- `src/scripts/run-e2e-ui-tests.sh` (functional + visual)
- `src/tests/run-presentation-regression.sh` (all variants)

The user-ask for :8000 is **slot availability**, not budget approval or tester-duty deferral. The AI owns executing the test; the user owns calendar coordination.

### The `src/tests/smoke/` caveat

The directory name is not a venue marker. Files living in `src/tests/smoke/` can still be destructive or long-running (e.g. `test_proxy_integration.py`). Route each file by the rubric above, not by folder.

### When in doubt → :8000

:7999 is an optimization for truly fast, truly read-only work. If you cannot prove a test meets all three :7999 criteria, schedule it on :8000.

## 100% COVERAGE MANDATE

**Lupin-wide hard gate.** Ratified 2026-05-06 (multiplexer-only), **scope-expanded Lupin-wide 2026-05-16** ("Everything has to pass at 100%. Full stop."). CoSA inherits it as of the 2026-05-29 mono-repo fold, on a grandfathering ramp — see the TODO.md top entry (deadline 2026-06-05).

**The rule**: **100% coverage — lines AND branches AND functions** on all Lupin code. Python via `pytest --cov` (`--cov-fail-under=100`); TypeScript via `c8 --100`.

- **Exceptions**: `# pragma: no cover` (Python) / `c8 ignore` (TS) ONLY for genuinely-unreachable defensive branches, and ONLY with a same-line comment giving the reason. "No time to test" is never valid — fix the test, not the gate.
- **In plan ACs**: write "100% lines/branches/functions" — never ≥90%/≥95%.
- **Excludes**: sub-repos `lupin-mobile`, `lupin-plugin-firefox`, and external-project bind-mounts.
- **Canonical record**: auto-memory `feedback_100pct_coverage_multiplexer.md` (directive + Lupin-wide expansion). Origin doc: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/08-phase6a-jobs-surface-design.md` AC6.

## TESTING

Three-tier strategy (unit → integration → E2E). Venue routing (`:7999` vs `:8000`) per §TESTING VENUES above; every suite is tagged with its venue. `:8000 (scheduled)` = submit via `POST /api/test-suite/submit` with a user-confirmed `scheduled_at`.

| Suite | Venue | Command | Notes |
|---|---|---|---|
| Unit | :7999 | `pytest src/tests/unit/` | Fast isolated tests, mocked deps |
| Smoke (inline) | :7999 | `python -m cosa.rest.<module>` | `quick_smoke_test()` blocks; non-destructive. `src/tests/smoke/` files are heterogeneous — route each by the §TESTING VENUES rubric, not the folder |
| WebSocket smoke | :7999 | `src/scripts/run-websocket-smoke-tests.sh` | 50 tests; connection/auth/events |
| Integration | :8000 (scheduled) | `./src/tests/run-integration-tests.sh --bg -v` | 43 tests; **FINAL merge gate**; always `--bg` |
| E2E UI (Playwright) | :8000 (scheduled) | `./src/scripts/run-e2e-ui-tests.sh --bg -v` | ~285 functional + visual; ~17min; `-k visual` (visual only), `--update-snapshots` (rebaseline); snapshots version-controlled |
| Interactive proxy | :8000 (scheduled) | `python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm` | 12 scenarios; mutates state, ~180s/scenario |
| Presentation regression | :8000 (scheduled) | `./src/tests/run-presentation-regression.sh --bg` | render→Sonnet→(Opus); real LLM spend; `--include-opus` / `--all` variants |

**`--bg` mandate**: integration, E2E UI, and presentation regression exceed the 10-min Bash timeout — always launch with `--bg` from Claude Code; monitor the matching `/tmp/*-latest.log`. PID-file overlap guards prevent concurrent runs.

**Coverage**: `pytest --cov=cosa --cov-report=html src/tests/` (Python). See §100% COVERAGE MANDATE for the hard gate.

**Docs**: `src/tests/README.md` (overview), `src/tests/integration/README.md`, `src/docs/automated-interactive-testing.md` (proxy), `src/tests/smoke/README.md`, `src/tests/AUTH-TESTING-GUIDE.md` (credentials), presentation strategy `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.07-e2e-testing-strategy.md`.

## PR MERGE REQUIREMENTS

**All must pass before merging to main** (venues + commands per §TESTING above), run in this order: unit (:7999) → WebSocket smoke (:7999) → E2E UI + visual regression (:8000 scheduled) → **integration (:8000 scheduled — FINAL GATE)**. Each requires 100% pass. Wait for E2E to complete before launching the integration gate; PID-file guards block concurrent runs.

Integration is the final gate because it exercises complete user workflows across API + DB + auth on a real server — catching regressions unit tests miss.

**On failure**: do NOT merge. Fix the failing tests first, then re-run the full suite. A genuinely-flaky-not-your-code failure gets documented + a separate fix — never a merge bypass.

**Testing anti-patterns** (NEVER):
- `curl` for pipeline/integration testing, or manual `/api/push` + poll `/api/get-queue/done` — use the automated scripts (`LivePipelineTestBase`), never bespoke curl.
- Running :8000-bucket suites (integration, E2E UI, proxy-integration, presentation regression) against :7999 — they depend on server monopoly; the dev server is not a stand-in.
- Side-door injecting :8000 tests via curl / direct `/api/push` / in-process instantiation / anything but `POST /api/test-suite/submit` with a user-confirmed `scheduled_at` — collides with in-flight runs and poisons both.
- Curl is acceptable ONLY for: API-reference docs, deployment health checks, one-off debugging (never committed).
- New agent? Add an automated smoke test (see `.claude/skills/agentic-voice-workflow/SKILL.md`).

## TEST CREDENTIALS

**CRITICAL**: Never hardcode test credentials. Always use environment variables.

### Required Environment Variables

```bash
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
```

> **Session 267 unification**: All smoke tests, proxy tests, and pipeline tests now use the
> `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` prefix. This ensures test and proxy authenticate as the
> same user (same WebSocket channel), preventing "Operation cancelled" failures.

### Usage Pattern (Python)

```python
import os

email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

if not email or not password:
    raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables" )
```

### When to Use

- Any smoke test that calls authenticated API endpoints
- Integration tests that require login
- Manual testing scripts
- Protocol verification tests that need real user context

**Reference**: See `src/tests/AUTH-TESTING-GUIDE.md` for credential patterns. For pipeline testing, always use automated smoke tests — never manual curl.

## DOCUMENTATION TOUCHPOINTS

When modifying code in these areas, update the corresponding documentation:

| Code Area Changed | Update These Docs |
|-------------------|-------------------|
| `routers/*.py` endpoint decorators | `/docs` auto-updates; run `src/scripts/generate-api-docs.sh` to update `src/docs/fastapi/` |
| `websocket_manager.py` | `src/docs/websocket-architecture.md` |
| `routers/websocket.py` | `src/docs/websocket-events.md`, `websocket-architecture.md` |
| `routers/notifications.py` architecture | `src/docs/notification-api.md` |
| `lupin-app.ini` WebSocket keys | `src/docs/websocket-configuration.md` |
| `lupin-app.ini` `websocket available events` | `src/docs/websocket-events.md`, `websocket-configuration.md` |
| New router added | `src/docs/rest-api-reference.md` quick-reference table |
| Auth services (`jwt_service`, `user_service`, etc.) | `src/docs/auth/architecture-overview.md` |
| Decision proxy / trust logic | `src/docs/proxy-admin-guide.md` |
| Frontend page routes | `src/docs/rest-api-reference.md` (Pages section) |
| `src/cosa/agents/bug_fix_expediter/` | `src/docs/agents/bug-fix-expediter-guide.md` |
| `src/cosa/agents/test_fix_expediter/` | `src/docs/agents/test-fix-expediter-guide.md` |
| `src/cosa/agents/shared/` (PlanWriter, GitStrategist, FixExecutor) | `src/docs/agents/shared-fix-primitives-reference.md` |
| `src/cosa/agents/test_suite/` | `src/docs/agents/test-suite-scheduling-guide.md` |
| `src/cosa/rest/test_suite_completion_watchdog.py` | `src/docs/agents/test-fix-expediter-guide.md` |
| `lupin-app.ini` `bug fix expediter *` keys | `src/docs/agents/bug-fix-expediter-guide.md` INI Reference |
| `lupin-app.ini` `test fix expediter *` keys | `src/docs/agents/test-fix-expediter-guide.md` INI Reference |
| BFE/TFE endpoint rows | `src/docs/rest-api-reference.md` sections 17/17a/17b |
| `routers/voice_persona.py` + `voice_persona_helpers.py` | `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` (architecture, allocation flow, /clear preservation, conversation-mode orthogonality) + `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` (host-side prune at SessionStart, mtime TTL guard, Sam-as-overflow allocation) |
| `lupin-app.ini` `cc session voice persona *` keys | Same R&D docs — base pool reference in 2026.04.28 §3 (Voice Pool); Sam-overflow keys (`sam icon/color/profile/display name`) + `stale threshold seconds` in 2026.05.16 §Solution Design Layer 3 |
| `lupin_cli/claude_code/hooks/lib/session_bridge.py` `prune_dead_persona_bridges` + `find_active_voice_persona_sessions` TTL guard | `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` (Layers 1–3: host-side prune + mtime TTL) |
| New LLM-driven agent OR migration of an existing agent between bounded-CC and firewalled-SDK paths | `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md`, R&D doc `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md`, auto-memory `feedback_prefer_bounded_cc_over_anthropic_sdk.md`, and CLAUDE.md § "COST MODEL — BOUNDED CC vs FIREWALLED SDK" if guardrails or candidate list change |
| `src/cosa/rest/routers/_scope_registry.py` + `docs_files.py` + `io_files.py` + `lupin-app.ini` `external repo *` keys + `docker-compose.yml` bind-mounts | `src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md` (scopes table, mount lines, blocklist patterns). Adding a new external scope requires the four-step checklist in auto-memory `feedback_multi_repo_doc_viewer.md`. |

**Documentation index**: `src/docs/README.md` — lists all docs with verification dates.

**Principle**: FastAPI `/docs` and `/redoc` are the authoritative API reference. Hand-written docs cover architecture, concepts, and operations only.

## HISTORY STRUCTURE NOTES
- **Project Span**: December 2024 - Present (Lupin evolution from Genie-in-the-Box)
- **Key Archived Periods**: 
  - 2024.12-2025.05: PEFT training, agent migrations, Flask→FastAPI transition
  - 2025.06: Lupin renaming, notification system, WebSocket foundation
  - 2025.07: Progressive TTS streaming, user routing architecture
  - 2025.08: Unit testing framework, Fresh Queue UI, audio debugging
- **Current Implementation Docs**: Referenced in history.md header
- **Archive Location**: `history/` directory with monthly organization

## Doc Viewer Scope (unified path-prefix routing — 2026-05-15)

**URL format**: `/app/docs?path=<project>/<rel>` where the first path segment names a registered project. The legacy `?scope=` query param is **RETIRED** — its presence triggers HTTP 400 with an educational pointer to this section (policy flipped from silent-ignore to aggressive-400 on 2026-05-21 per amendment to AC4b.7 of `src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md`).

- **Lupin files**: `/app/docs?path=lupin/<rel>` — e.g. `/app/docs?path=lupin/bug-fix-queue.md`, `/app/docs?path=lupin/src/rnd/foo.md`. Whitelist authority is `lupin/.docview.yml` at repo root.
- **Other registered repos**: `cosa-voice`, `planning-is-prompting`, `lookml`, `par-pacific`, `claude-plans`, `retail-ai-location-strategy`, `lupin-mobile` — same URL shape, scope name is the project name.
- **Source of truth**: `src/conf/lupin-app.ini` § `external repos` plus each repo's `.docview.yml` (when present).
- **Runtime discovery**: `GET /api/docs/scopes` (admin endpoint, JWT-auth) returns the full registry; cosa-voice MCP `get_session_info()` exposes a single `project_name` string for the current session.
- **Floor blocklist**: ~46 universal regex patterns block `.env`, `.venv`, `node_modules`, `__pycache__`, `CLAUDE.local.md`, `.ssh/`, etc. across EVERY scope — defense-in-depth; cannot be weakened by any repo's manifest.
- **Supported file types**: text (`.md`, `.txt`, `.json`, `.yaml`/`.yml`), source code (`.py`, `.ts`/`.tsx`, `.js`/`.jsx`, `.css`, `.html`, `.sh`, `.sql`, `.toml`, `.ini`/`.cfg`, `.xml`), and images (`.png`, `.jpg`/`.jpeg`, `.gif`, `.svg`, `.webp` — added 2026-05-21). Image MIMEs serve via `FileResponse` (binary); text/code via `PlainTextResponse`. The SPA dispatches on `Content-Type.startsWith('image/')` to render inline `<img>` tags.

**Examples**:
- `/app/docs?path=lupin/src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md` ✅
- `/app/docs?path=lupin/bug-fix-queue.md` ✅ (formerly 404 — fixed in this milestone)
- `/app/docs?path=lupin/CLAUDE.local.md` → 400 (floor blocks)
- `/app/docs?path=bug-fix-queue.md` → 400 (missing project prefix)
- `/app/docs?path=docs/anything` → 400 (unknown project — `docs` retired)
- `/app/docs?path=lupin/CLAUDE.md&scope=docs` → 400 "The `?scope=` query parameter is RETIRED..." (aggressive-400 since 2026-05-21; scope-presence check fires BEFORE path validation)

**For sessions emitting links**: ALWAYS prefix with the project name. `scope=` is dead — do not include it. The endpoint will 400 immediately if you do, with an educational message naming the canonical form + the live registered-project list.
