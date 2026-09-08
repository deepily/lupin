# Lupin development guide

> Rules only. Where a rule came from — the measurements, the reconciliations, the corrections —
> is archived in `src/docs/doctrine/` and is not required reading.

## Commands
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (Runs on port 7999)
- Docker build: `docker build -f docker/lupin/Dockerfile .`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`
- Install cosa-voice MCP (global): `src/scripts/install-cosa-voice.sh` (user scope, all repos)
- Regenerate API docs: `src/scripts/generate-api-docs.sh` (requires server on port 7999, `--offline` for saved JSON)

## Claude Code slash commands
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

## CJ Flow (CoSA jobs flow)

CJ Flow is Lupin's unified work queue system. All jobs that implement the `QueueableJob` protocol flow through it.

**Queue Pipeline**: todo → running → done/dead
**Protocol**: `QueueableJob` (22 attrs + 4 methods) — see `src/cosa/rest/queue_protocol.py`

**Dispatch architecture (v0.1.7+)**: `RunningFifoQueue._process_job(job)` dispatches by `isinstance`:
- `AgenticJobBase` → `_submit_agentic_job` → `ThreadPoolExecutor` (the **agentic pool**, size = `cj flow max concurrent agentic jobs` INI key, prod default `= 1`, `[Lupin: Development]`/`[Lupin: Testing]` override to `= 3`). Consumer thread returns immediately; `Future.add_done_callback` fires `_on_agentic_complete` which calls `_transition_to_done` or `_transition_to_dead`.
- `AgentBase` / `SolutionSnapshot` → inline fast-lane on the consumer thread (unchanged). Pool does NOT block fast-lane.

**Thread safety (v0.1.7+)**: `FifoQueue` has `threading.RLock` protecting `queue_list` + `queue_dict`. Pool workers and consumer thread can mutate concurrently. All 9 `self.pop()` sites in `running_fifo_queue.py` migrated to `self.delete_by_id_hash(job.id_hash)` — head-of-queue is no longer deterministic under pool-callback concurrency.

**Ghost-job sweeper (v0.1.7 Phase 3)**: daemon thread on `RunningFifoQueue` runs every `cj flow ghost job sweep interval seconds` (default 30s). Scans `_agentic_futures` for entries whose `Future.done()` is True but whose job is still in running queue — dead-letters them via `_transition_to_dead`. Suspenders to the callback's defensive belt.

**Rate-limit / API contention (v0.1.7 Phase 3)**: `ApiResourceManager` singleton at `src/cosa/utils/api_resource_manager.py` centralizes per-provider waits + call recording. Deep Research migrated (`await get_arm().acquire("anthropic_web_search")` + `get_arm().record_call(...)`). Podcast/Presentation/BFE/TFE/ClaudeCode stay on legacy per-agent `_call_with_retry` patterns; two-path invariant documented in `src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/01-design-review.md §3a`.

**Observability (v0.1.7 Phase 3)**: ⚠️ **These fields describe the POOL, not the venue — do not derive idleness from them (row `e6b8fe56`); use `cosa.rest.venue_idle` / `GET /api/busy`, see §TESTING VENUES.** `GET /api/queue/pool-status` (JWT) returns `{inflight_agentic_jobs, max_agentic_workers, pending_in_pool, monopolize_inflight, monopolize_id, api_resource_manager: {...}}`. **Shape-B (bug fe375cf6)**: a monopolize job runs on a DEDICATED single-worker executor (`_monopolize_pool`), NOT the shared pool, so it is EXCLUDED from `inflight_agentic_jobs`/`pending_in_pool` (those keep their exact prior meaning = shared-pool occupancy) and surfaced instead via `monopolize_inflight` (bool) + `monopolize_id` (id or null). At most one monopolizer exists at a time (Gate B defers a 2nd at intake).

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

## Cost model — bounded CC vs firewalled SDK

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

Already migrated: **BFE** (`src/cosa/agents/bug_fix_expediter/`), **TFE** (`src/cosa/agents/test_fix_expediter/`), **Podcast script generation** (`src/cosa/agents/podcast_generator/` — Phase 1, 2026-06-18; in-process `sdk_query`, `tools=[]`, D6-lenient parsers), **Presentation content generation** (`src/cosa/agents/presentation_generator/` — Phase 2, 2026-06-18; 7 methods → `sdk_query`, D6-STRICT parsers, Gemini path untouched), **Deep Research** (`src/cosa/agents/deep_research/` — Phase 3, 2026-06-18; lead agent `tools=[]` + research subagents `tools=[WebSearch, WebFetch]` replacing native `web_search_20250305`, ARM web-search gating dropped, D6-STRICT parsers).

Migration candidates (tracked in TODO.md): the three ratified bounded-CC migrations (Podcast → Presentation → Deep Research) are all complete. Remaining opportunities are deferred per D4/D5 (OpenAI call sites, Runtime Argument Expeditor) — not yet ratified for migration.

**Framing**: this is a **cost-shift, not zero-cost**. The Max 200 plan is a fixed monthly bill. Migrations convert per-token metered spend into already-paid fixed cost. Never describe a migration as "free" — describe it as "covered by existing fixed cost."

### When not to migrate

- High-frequency tiny calls (>~10 QPS) — subprocess spawn overhead dominates. Keeps: `notification_proxy/strategies/llm_fallback.py`, `decision_proxy/`.
- Hard latency budget < ~2 seconds.
- Non-Anthropic models required (OpenAI/Groq/Mistral/etc. — Max plan only covers Claude).
- Token-by-token streaming UX (bounded CC returns on completion, no progressive streaming).

### Off-peak scheduling rule (operational)

Max-plan usage has rolling-window limits, and the host is not up around the clock. Any non-interactive
bounded job — batch generation, scheduled regression sweeps, podcast, presentation, research — must set
`scheduled_at` inside a window the box is up for. User-clicked synchronous jobs are exempt.

| window (EDT) | verdict |
|---|---|
| ~11 PM – 10 AM | ☠️ dead — the host is usually powered off. A job here does not run late, it does not run at all until boot |
| 9 PM – 11 PM | ❌ peak — Rick's interactive window |
| **10 AM – 1 PM** | ✅ **optimal — schedule batch work here** |
| 1 PM – 9 PM | 🟡 acceptable |

Rick ruled 2026-08-31 that the boot window is a real constraint, not a record of his habit. The box also
goes down mid-day sometimes, so "optimal" means *most likely up*, never *guaranteed up* — a long job must
tolerate a restart.

Re-derive the window rather than trusting the table; use `journalctl --list-boots --no-pager`, not
`last -x reboot`, whose `wtmp` rotates and can report a single boot with nothing saying so.

Submit through `/api/v2/submit`, naming the command `agent router go to claude code`. `scheduled_at` is
top-level — it tells the queue *when* to run, and is not part of the command's argument contract. The old
`/api/claude-code/submit` door and its alias answer **410 Gone**.

```json
POST /api/v2/submit
{
  "command"      : "agent router go to claude code",
  "args"         : { "prompt": "…", "task_type": "BOUNDED" },
  "scheduled_at" : "2026-08-22T11:00:00-04:00"
}
```

A job that lands in the dead window drains late but not silently — `job_persistence.py` emits a
`[CJ-CATCHUP-LATE]` line naming `scheduled_at`, the actual time, and the hours late.

## Code style
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
- **XML formatting**: Use XML tags for structured responses in agent communication

## Configuration
- Config files: `src/conf/lupin-app.ini` and `src/conf/lupin-app-splainer.ini`
- Environment variables override config file settings
- Use `ConfigurationManager` to access config values

## Project structure
- `/src/lupin_app/`: FastAPI application directory
  - `/src/lupin_app/main.py`: Main FastAPI server entry point
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

> **`/src/lib/` was DELETED 2026-08-26** (Rick's ruling, row `e2099400` §3b). It held the desktop
> client — `lupin_client.py`, `lupin_client_cmd.py`, `lupin_client_gui.py`, 1,454 lines — which had
> been unimportable since `pyaudio` left the environment, was last touched 2026-01-28, and carried
> 524 statements at 0% inside a 100% coverage mandate. Its only live caller,
> `src/scripts/run-lupin-gui.sh`, went with it: a Mac-only launcher invoking `python3.10` over SSHFS
> in a 3.13 repo. **Recover either with `git checkout 71d5efaa -- src/lib src/scripts/run-lupin-gui.sh`.**

## Debugging
- Set `debug=True` and `verbose=True` parameters in class instantiations
- Use `du.print_banner()` from `utils.py` for formatted console messages

## WebSocket development notes
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

## Notification system
- **API reference**: `src/docs/notification-api.md` (comprehensive one-stop reference)
- **WebSocket Events**: `src/docs/websocket-events.md` (event catalog)
- **Agentic Voice Integration**: `src/workflow/agentic-voice-workflow.md`
- **Decision Proxy Admin Guide**: `src/docs/proxy-admin-guide.md` (Trust Dashboard + Ratification how-to)
- **Interactive Proxy Testing**: `src/docs/automated-interactive-testing.md` (proxy auto-answer testing guide)
- **R&D Planning Docs**: `src/rnd/v0.1.0/2025.10.15-sse-notifications/` (historical)

## Startup procedure
- The first thing you should do when you start a session is read the global Claude configuration file and follow its instructions.
- **History file**: Read the main history file (`/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`) which contains recent 30-day context and links to archived periods
- **Implementation document**: Read the current implementation document referenced at the top of history.md
- **Archive access**: If deeper historical context needed, follow links to `history/YYYY-MM-history.md` files
- **Ignore sub-repo histories**: do not read these sub-repository history files as they are managed separately:
  - `src/lupin-plugin-firefox/history.md` (Firefox plugin sub-repo)
  - `../lupin-mobile/history.md` (Mobile app — a SIBLING of lupin since 2026-08-30, no longer under `src/`)
  - (`src/cosa/history.md` is **no longer** a sub-repo history — CoSA folded into the mono-repo 2026-05-29; it is now a normal in-tree doc.)

## Project short names
- This repo's SHORT_PROJECT_PREFIX is [LUPIN]

## Repository relations
- There is another repo that's a part of the larger project contained in the directory `lupin-plugin-firefox`
- This repo must be managed separately and cannot be managed by Claude

## Running and testing FastAPI applications
- Please assume that there is a Fast API server instance bound to port 7999. I will start and stop it if needed. You never need to spin up another instance unless it's for a ephemeral use on port 8000.
- **Before clicking Resume on any TFE/BFE stalled job, or before scheduling a live E2E run on `:8000`**, run `src/scripts/preflight-test-container.sh` (or `pytest src/tests/smoke/test_container_preflight.py -v`). This catches docker-compose.yml drift — cases where a `.git`, credentials, or other bind-mount change has not been applied to the running container because only `docker rm -f` + `docker compose up -d` picks up new mounts (not `docker restart`). Failure output includes the exact remedy.
- **Server lifecycle (when does a change land? when do I bounce? which command?)**: See skill `server-lifecycle` — encodes the per-server decision matrix, the restart-vs-`--force-recreate` distinction, the queue-check courtesy, and the `:8000` monopolize-mode protocol. Auto-fires on bounce/restart/refresh/rebuild phrasing including ASR variants ("doctor" → "Docker").
  - ⚠️ **CHANGED 2026-08-01 — two policy changes the same day.** (1) `uvicorn --reload` is now **OFF by default on `:7999`**, opt-in via `LUPIN_RELOAD` and gated by `reload_enabled()` in `bootstrap_helpers.py` — watching the tree was taking the server down for the whole fleet whenever anyone touched a watched file. **A `.py` change no longer goes live on its own; both servers need a bounce now.** (2) The old "never volunteer a `:7999` bounce" rule is **retired** — anybody may bounce `:7999`, within reason, to pick up fresh code.
  - **Use the sanctioned path**: `./src/scripts/bounce-dev-server.sh` (`--quiet` for a one-liner). It posts an **ack-confirmed** warning broadcast so the fleet holds notifications *before* the server dies, restarts the container, and polls `/health`; the **all-clear is emitted by the restarted server's own startup hook**, so it covers every restart path.
  - **`restart` ≠ `--force-recreate`**: mount specs and env resolve at container **CREATE**. Changed `docker-compose.yml`, a bind mount, or an env var? Use `docker compose up -d --force-recreate <svc>` — a restart reuses the old values and your change silently does not land. (This is also why re-arming `LUPIN_RELOAD` needs a recreate.)

## Git repository management

**CRITICAL**: This project contains multiple nested Git repositories that must be managed separately.

### Repository structure

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
   - **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin-mobile/` — a **SIBLING** of the Lupin repo since 2026-08-30, moved out of `src/`. It is no longer nested, so it will not appear in Lupin's `git status` at all.
   - **Management**: Separate repository, managed independently
   - **History**: Has own history.md (DO NOT read from Lupin context)

### How /plan-session-end handles nested repos

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
• ../lupin-mobile/ (1 new file — sibling repo, detected only if explicitly scanned)

These are separate Git repositories and will not be included in this commit.
Reminder: Manage nested repositories in their own sessions/contexts.
```

**Git Safety Rules**:
- ✅ Stage/commit/push changes in parent Lupin repo
- ❌ Never run git commands in nested repo directories from parent context
- ✅ Nested repos must be managed when working directly in their contexts
- ✅ `/plan-session-end` automatically filters nested paths from git operations

### Detection command

If you need to verify nested repositories:
```bash
# Find all nested .git directories
find . -name ".git" -type d | grep -v "^./.git$"
```

### Working in nested repositories

**When working in Firefox Plugin** (`cd src/lupin-plugin-firefox/`):
- Manage as independent project
- Has own git history and workflows

**When working in Mobile App** (`cd ../lupin-mobile/`):
- Manage as independent project
- Has own git history and workflows

### Committing — never attach a heredoc to the `git commit` line

Commit with `git commit -F <file> -- <paths>`. Write the message file first; a heredoc *there* is fine.

Never attach a heredoc or here-string to the `git commit` invocation itself — `-F /dev/stdin <<EOF`,
`-F - <<EOF`, `<<< 'body'`. The commit scope guard reads the tail after the `git commit` match to find
which paths you are committing; a `<<` in that tail makes it decline, print
`⚠️ Commit scope guard: NOT REVIEWED`, and let the commit through unexamined.

The rule is about attachment, not about heredocs. If you do see `NOT REVIEWED`, either re-run in the
reviewed shape or check the commit yourself with `git show --stat <sha>` — and say which you did.

## Testing venues

Every automated test runs on exactly one of two servers. Pick by rubric, never by habit.

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
- `src/tests/smoke/test_memory_cap_binds.py` — ⚠️ it runs `systemd-run` and gets a process
  SIGKILLed, which reads like a :8000 suite and is not one. Routed by the rubric: the scope is
  transient (`--scope --collect`, dies with the command), so nothing persists; ~0.5s; and the only
  process it kills is the allocator it started, inside a cgroup it owns — which is the very
  property one of its cases asserts. It needs no monopoly and takes none.
- `src/tests/websocket_smoke/` (run via `src/scripts/run-websocket-smoke-tests.sh`)

### :8000 (test) — monopolize mode, scheduled only

Submit via `POST /api/test-suite/submit`, and only that way. Never inject through ad-hoc curl, a direct
queue push, or in-process server instantiation — a side door collides with in-flight scheduled runs and
poisons both.

Eligible if **any** of: it mutates persistent state (DB rows, shared files, LLM API spend, enqueued jobs);
it runs over 2 minutes; it needs server monopoly.

Suites that qualify:
- `src/tests/smoke/test_proxy_integration.py` (any scenario — CRUD and expediter mutate state)
- `src/tests/run-integration-tests.sh` (final merge gate)
- `src/scripts/run-e2e-ui-tests.sh` (functional and visual)
- `src/tests/run-presentation-regression.sh` (all variants)

A verified-idle `:8000` is bounce-then-schedule self-authorized — the user is not a gate, and neither
budget approval nor an idle-slot ask is required. The only user gate is **killing a live in-flight job**.

**Verify idle with one command and read its exit code:**

```bash
PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000 ; echo "exit=$?"
```

`0` idle · `1` busy · `2` unknown. It reads the unfiltered, unauthenticated `GET /api/busy` — run depth,
todo depth, shared-pool inflight, monopolize slot — and every lane must be empty.

**Unknown is not idle.** If only `todo_queue_size` is missing, that container predates the field and
cannot see waiting work; bounce it to pick up the code, not `--force-recreate`.

Do not verify idle from `pool-status` or the queue listings. `monopolize_id` only moves for a
monopolize-flagged job that has already started, so it names which job holds the slot and says nothing
about queued or inline work; `/api/get-queue/{q}` is user-filtered and `?user_filter=*` answers 403 for
this account, so a peer's queued job is not in your listing at all.

**Then place it**: empty queue → bounce, schedule, run now. Something already scheduled → still
self-authorized, but set `scheduled_at` after it; never jump an expected-next run. Something running →
queue behind it, no bounce.

### The `src/tests/smoke/` caveat

The directory name is not a venue marker. Files living in `src/tests/smoke/` can still be destructive or long-running (e.g. `test_proxy_integration.py`). Route each file by the rubric above, not by folder.

### When in doubt → :8000

:7999 is an optimization for truly fast, truly read-only work. If you cannot prove a test meets all three :7999 criteria, schedule it on :8000.

## 100% coverage mandate

**A Lupin-wide hard gate.** Ratified 2026-05-06 (multiplexer-only), **scope-expanded Lupin-wide 2026-05-16** ("Everything has to pass at 100%. Full stop."). CoSA inherits it as of the 2026-05-29 mono-repo fold, on a grandfathering ramp — see the TODO.md top entry (deadline 2026-06-05).

**The rule**: **100% coverage — lines AND branches AND functions** on all Lupin code. Python via `pytest --cov` (`--cov-fail-under=100`); TypeScript via `c8 --100`.

- **Exceptions**: `# pragma: no cover` (Python) / `c8 ignore` (TS) only for genuinely-unreachable defensive branches, and only with a same-line comment giving the reason. "No time to test" is never valid — fix the test, not the gate.
- **In plan ACs**: write "100% lines/branches/functions" — never ≥90%/≥95%.
- **Excludes**: sub-repos `lupin-mobile`, `lupin-plugin-firefox`, and external-project bind-mounts.
- **Canonical record**: auto-memory `feedback_100pct_coverage_multiplexer.md` (directive + Lupin-wide expansion). Origin doc: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/08-phase6a-jobs-surface-design.md` AC6.

## Testing

Three-tier strategy (unit → integration → E2E). Venue routing (`:7999` vs `:8000`) per § Testing venues above; every suite is tagged with its venue. `:8000 (scheduled)` = submit via `POST /api/test-suite/submit`; **self-authorized on a verified-idle server** (place behind any already-scheduled/running job — see § Testing venues).

| Suite | Venue | Command | Notes |
|---|---|---|---|
| Unit | :7999 | `pytest src/tests/unit/` | Fast isolated tests, mocked deps |
| TypeScript | :8000 (scheduled) | `./src/tests/run-typescript-tests.sh` | 119 `*.test.ts` under c8 at 100%; ~8-25 min, no server. Runs inside the capped `jstest.slice` cgroup (RSS watchdog 2048 MB fires before the 8 G `MemoryMax`). **Tier ban LIFTED 2026-08-25** (row 92e94cb7) — all four doors are capped, so `test_types: ["all"]` is safe again. ⚠️ A full run may still HANG on leaked transports (row f8055be3) — an RC=124 is that defect, not memory |
| Smoke (inline) | :7999 | `python -m cosa.rest.<module>` | `quick_smoke_test()` blocks; non-destructive. `src/tests/smoke/` files are heterogeneous — route each by the §TESTING VENUES rubric, not the folder |
| WebSocket smoke | :7999 | `src/scripts/run-websocket-smoke-tests.sh` | 50 tests; connection/auth/events |
| Integration | :8000 (scheduled) | `./src/tests/run-integration-tests.sh --bg -v` | 43 tests; **FINAL merge gate**; always `--bg` |
| E2E UI (Playwright) | :8000 (scheduled) | `./src/scripts/run-e2e-ui-tests.sh --bg -v` | ~285 functional + visual; ~17min; `-k visual` (visual only), `--update-snapshots` (rebaseline); snapshots version-controlled |
| Interactive proxy | :8000 (scheduled) | `python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm` | 12 scenarios; mutates state, ~180s/scenario |
| Presentation regression | :8000 (scheduled) | `./src/tests/run-presentation-regression.sh --bg` | render→Sonnet→(Opus); real LLM spend; `--include-opus` / `--all` variants |

**`--bg` mandate**: integration, E2E UI, and presentation regression exceed the 10-min Bash timeout — always launch with `--bg` from Claude Code; monitor the matching `/tmp/*-latest.log`. PID-file overlap guards prevent concurrent runs.

## PR merge requirements

All must pass before merging to main. Run in this order; each requires 100% pass. Venues and commands are
in § TESTING above.

| # | gate | venue |
|---|---|---|
| 1 | unit — `pytest src/tests/unit/` | :7999 |
| 2 | cosa — `src/tests/run-cosa-tests.sh` | :7999 |
| 3 | coverage — `src/tests/run-coverage-gate.sh` | :7999 |
| 4 | typescript — `src/tests/run-typescript-tests.sh` | :8000 scheduled |
| 5 | smoke | :7999 |
| 6 | serial bridge guard — `src/scripts/run-serial-bridge-guard.sh` | :7999 |
| 7 | websocket smoke | :7999 |
| 8 | E2E UI + visual regression | :8000 scheduled |
| 9 | **integration — the final gate** | :8000 scheduled |

The coverage gate re-runs nothing: the unit and cosa tiers append to one isolated data file, and it renders
that, checks `fail_under`, and checks the frame still measures every file it claims.

Wait for E2E to finish before launching the integration gate — PID-file guards block concurrent runs.
Integration is last because it exercises complete user workflows across API, DB and auth on a real server.

**Reading the serial bridge guard.** It is the whole-directory contact check the concurrent unit run
deselects, because a live peer's bridge write would false-accuse it. Do not wait for a quiescent box —
there is no such state, and the seat running the guard writes its own bridge while it executes. Read a red
this way instead: re-run and compare the **named file** — the same filename every run means real contact, a
different file or none means peer noise. Then read that file's `session_id` / `cc_pid` and check
`ls /proc/<cc_pid>`; if it belongs to a live seat that is not you, it is noise. One green is also one
sample: the discriminator is determinism, not the colour.

**Test counts move.** Re-derive them rather than quoting one — the cosa tier has read 8,622 · 8,668 · 8,671
· 8,788 across a fortnight, every figure correct when taken, with tests added in between.

**On failure**: do not merge. Fix the failing tests, then re-run the full suite. A genuinely-flaky failure
that is not your code gets documented plus a separate fix — never a merge bypass.

### Test credentials

Any smoke test hitting authenticated endpoints, any integration test that logs in, and any protocol
verification test needs these. Test and proxy must authenticate as the same user, or they land on
different WebSocket channels and the run fails with "Operation cancelled".

```bash
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
```

```python
email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

if not email or not password:
    raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
```

Patterns: `src/tests/AUTH-TESTING-GUIDE.md`. For pipeline testing use the automated smoke tests, never curl.

## Working rules

Hard-won, and stated as rules rather than argued. The measurements behind them are archived in
`src/docs/doctrine/` for anyone tracing where one came from; you do not need them to follow the rule.

### Reporting a measurement

- Say what you measured and when. A bare figure ages without ever changing, and a reader cannot tell.
- Name the population before you trust a result. An empty answer from the wrong population looks exactly
  like an empty answer from the right one.
- Prove your instrument can find something. A negative result is worth nothing until you have watched the
  same search return a positive one.
- A census carries a timestamp whether you write one or not. "I looked and found one" and "there can only
  be one" print the same in a summary, and only the second closes a question. Say which you mean.
- Read your conjunctions one at a time. For every *because*, *so*, *which means*, ask whether you measured
  the link or only the two ends. If only the ends, state them as two facts — the reader can draw the arrow.
- Name a gap rather than bridging it. An inferred bridge cannot be audited; a named gap is searchable, and
  whoever holds the other half can close it.
- Never assert a mental state from an artifact. An artifact shows you what was produced, never why.
- Leave an unmeasured lead out of anything durable. A caveat protects the reader of the conversation; only
  omission protects the reader of the artifact. A *measured* don't-know stays — that is a finding.
- A wrong number gets re-derived by the next reader. A wrong mechanism sends them into innocent code, so
  the explanation earns the deeper check.
- Say which you corrected. "4 → 3" reads as a population shrinking even when the floor got firmer.
- Report a partial re-derivation side by side, never as one verdict. Half-refreshed reads as refreshed.

### Pointing at something

- Name the content, not the coordinate. A line number, a `stash@{N}`, a PID, "the file I edited earlier" —
  all go stale between your reading and someone else's acting, and in a fleet someone always edits.
- Cite a heading or a symbol name over a line number; a heading survives an edit above it.
- When you must point at a position, make the pointer self-checking: give the anchor text, say it must
  match exactly once, and say what to do when it matches zero or twice — come back, never guess.
- Say which space a hash indexes. Row id, content sha, git commit — same shape, three different lookups.
- Mark a closed row as closed when you cite it, or the reader inherits a constraint that no longer exists.
- Identify a process by a property it carries — its cwd, its `comm` — never by a handle you captured when
  it was true. The OS recycles PIDs.
- Send a to-be-pasted artifact bare, one per message. Text between sessions is condensed in transit, and a
  paragraph explaining the paste is what absorbs it.

### Searching

- A hit is not a use. A name travels through comments, docstrings, route strings and other tests' prose;
  the code that uses it appears once. Open the matches and read what they do.
- Use fixed-string searches. A character class or an alternation quietly under-reports.
- A git pathspec is not shell globstar: `src/docs/**/*.md` requires an intervening directory and silently
  drops every file sitting directly in `src/docs/`. Count the population first — `git ls-files <pathspec> |
  wc -l` — and sanity-check it against what you believe is there.
- `git grep` cannot see untracked or ignored files. Say so when reporting a zero.
- Read the program when the question is what the program does. A corpus of its outputs cannot tell a value
  that was frozen from one regenerated to the same bytes. A corpus is right for *how many* and *how
  widespread*; it can never answer *why*.
- Ask what population your command walks. `src/cosa/.venv` is a vendored virtualenv inside the source tree
  and is about 92% of any disk-derived sweep, so exclude `.venv`, `node_modules` and `site-packages`, or
  derive the population from git.

### Tests

- Coverage tells you a line ran. It never tells you the test could have noticed it running wrong.
- A fake that ignores its input answers the same however the code behaves, and every assertion written over
  it inherits that. Replace the code under test with a constant; if the fixture still yields the same data,
  the suite is measuring the fixture.
- Read the data before the assertions. If two quantities can be swapped without changing the expected
  output, the test asserts their sum, not their identity — whatever its name says.
- Capture at least one fixture from the real producer through the real reader. A hand-written fixture is
  better-formed than reality, exactly where a parser depends on the mess.
- An assertion satisfiable by more than one path cannot tell you which one ran. Name the path in the
  assertion; when you find several sufficient causes, go and eliminate one rather than reaching for
  sharper words.
- Trace both sides of a comparison back to their origin. If they meet, it is a tautology wearing an
  assertion's clothes — pin one side to a literal, a committed fixture, or a count from `git ls-files`.
- Two sides that derive one value by different routes are coinciding, not agreeing. Ask what would make
  them differ and whether it has ever happened. You cannot fix one side of a coincidence.
- Enter at the layer the incident entered at. A real component exercised at the wrong altitude is still
  the wrong measurement, and it looks like a green end-to-end test.
- Drive the assembled app, not only the class. A component can be complete, correct, fully covered and
  never mounted, and every test that builds the component stays green.
- Enumerate the surface, not the traffic. What got exercised is a history of somebody's clicking. State
  how many siblings exist and how many are watched; a guard that cannot state its denominator is telling
  you about its corpus.
- Assert the loop found something before looping. A loop over nothing passes every assertion in it.
- Unguarded is a third state: the code is right and no test could see it break. Prove which state you are
  in by deleting the guard and watching a named passing test redden. A break list proves unwatched, never
  absent.
- A projection of a gate must ask the gate, not restate its rule. Two pieces of code deciding one rule
  agree until they do not, and the restatement is usually off by one to begin with.

### Coverage

- 100% lines, branches and functions on all Lupin code — `pytest --cov --cov-fail-under=100`, `c8 --100`.
  Exceptions only via `# pragma: no cover` / `c8 ignore` with a same-line reason. "No time to test" is
  never valid. Write "100% lines/branches/functions" in plan ACs, never ≥90%.
- Never scope a run whose output you will read as a list. `--cov=<path>` does not narrow the report, it
  narrows what was ever measured, and absence from a scoped report means never-measured, not zero. Scoping
  is fine for one file's number — per-file counts are scope-invariant.
- `--cov=` needs a target that is both importable *and* actually imported by that run. A `.py` path always
  measures zero. Three warnings fire and the run still exits 0, so read the table and grep for
  `module-not-imported`.
- Coverage goes stale from a merge, not a commit. Unmerged work moves nobody's coverage but its author's,
  so state the sha with the list and report "done" and "landed" as separate columns.

### Mutation testing

- Take a green baseline first and record the failing set. The kill signal is the failing set: a named test
  that was passing now fails. Exit codes 4 and 5 mean pytest could not run the node, and on a branch with a
  deliberate red, `rc == 1` scores every mutant as killed.
- Compare the assertion that fired, not just the test id. An assertion placed behind a currently-failing
  one is carried, not exercised — put a new guard in its own test.
- Assert the mutation applied: the anchor matched exactly once, the on-disk sha changed. End with a restore
  control you actually read.
- Isolate every arm. Rebuilding the sandbox per arm is strongest; `src/scripts/purge-pycache.sh` is the
  practical choice in a working tree. A raw `find … __pycache__ -delete` re-opens the defect.
- A surviving mutant has four explanations — a weak test, a broken harness, an equivalent mutant, or a
  fixture that cannot discriminate. Only the first earns a new test, and the fourth is invisible to
  re-reading the test body.
- Put a ceiling on a kill count as well as a floor. A break aimed at one line should redden the tests that
  reach it; near-total kill is a syntax error until proven otherwise. Compare the run count to baseline,
  not just the failures.
- "I repaired a fixture" is not "I proved the repair discriminates". Two arms off one mutated sha: the old
  fixture survives, the new one is killed by the named test. Neither arm alone counts.
- A clean pass samples the mutation space; it does not survey it. Exchange shas with another harness to
  catch a disagreement, never to manufacture a confirmation.
- Never mutate in a peer's live worktree, or in the shared main tree. Check the sha out into a detached
  worktree of your own — a `cp` restore from your own backup carries the same race as `git checkout`.

### Bytecode

The tree uses checked-hash invalidation. Without it CPython validates a `.pyc` on the source's
whole-second mtime plus size, so a same-size edit inside one second runs the previous arm's bytecode.

- `src/scripts/purge-pycache.sh` purges **and** reconverts, and refuses before deleting if it cannot
  reconvert. It takes only `--dry-run`. It resolves its tree from its own location, so run the copy that
  lives in the tree you mean; `LUPIN_ROOT` is inert for it, but `PYTHON` is not.
- `src/scripts/migrate-pyc-to-checked-hash.sh --verify` is the read-only report, and it scans
  `$LUPIN_ROOT/src` — not where you are standing. Read its `scanned roots:` line, not its checkmark. Pin
  both `LUPIN_ROOT` and `PYTHON`, since `PYTHON` derives from the root and many worktrees have no `.venv`.
- Its exits: 0 clean, 1 timestamp pycs present (the real finding), 2 it never ran. Only stderr separates
  2's causes.
- A `0` from a tree that has never been used is vacuous, not clean. Use a new worktree once,
  purge-and-reconvert, then verify.
- `-f` is the whole migration — without it `compileall` converts nothing and reports success.
- `PYTHONDONTWRITEBYTECODE` suppresses writing, never trusting. Editing a test file inside a test still
  needs `tests.helpers.pyc_freshness`.

### Worktrees

- Pin all three, every time. `LUPIN_ROOT` is inherited from your shell and silently keeps naming the main
  repo:

  ```bash
  cd <worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python -m pytest src/tests/unit/ -q
  ```

- `LUPIN_ROOT` decides which tree paths resolve against; `PYTHONPATH` decides which tree modules are
  imported from. Pin one and not the other and your modules come from two checkouts — a tree that exists
  nowhere on disk, pointing toward a false green.
- A worktree is git-identical to the main tree and environment-identical to nothing. Subtract the
  artifacts; do not chase them. `ls -L` first — the file is the coordinate and the count derives from it,
  and every borrowed artifact is a symlink, so a bare `ls -l` reports the link's size.

  | missing | unit-tier failures |
  |---|---|
  | `src/scripts/cloud-run.env` | 9 absent, 0 present |
  | `.venv` | 33 |
  | terraform provider cache | 1 |
  | `LUPIN_ROOT` unpinned | 1 |

- Provisioning runs in the Python spawn path only, so a hand-typed `git worktree add` gets nothing — run
  `src/scripts/link-worktree-artifacts.sh` yourself there.
- Never symlink anything under `src/conf/keys/**` or the repo-root `.env` into a worktree. A venv is a
  build artifact; a key is a secret, and a worktree gets deleted, copied and shared.
- A failure that passes in the main tree has two explanations — a worktree artifact, or a fix you do not
  have yet. Name the commit to tell them apart:
  `git log --oneline <your-sha>..<main-HEAD> -- <the failing test's path>`.
- A red count or a coverage list about "the tree" must be run at the main line. Your own branch is blind to
  exactly the defects its unmerged work repairs.
- While a tier is running, that worktree is read-only — whatever your reason for touching it. A mutation
  arm feels like measuring, not editing, and the run cannot tell the difference.
- The tier stamp's `run-span=unmoved` compares two HEAD shas; `tracked-dirty` is one sample at the end with
  untracked rows stripped. Neither certifies that the run measured the tree you think it did. Name a run by
  what it measured, not by the sha you asked for.

### Reading a result

- A clean exit is not evidence the work happened. A tool that no-ops and a tool that succeeds print the
  same status, so read the tool's own account: does the coverage table list the file, does the verify name
  your tree, does the purge report a count matching what you planted.
- A tool that cannot finish should refuse the whole operation and name what it did not do, rather than
  half-finishing and returning a status the caller reads as success.
- In a two-arm comparison, give each arm its own freshly built state. An arm that no-ops because the
  previous one consumed its input is indistinguishable from an arm that failed.
- `--bg` makes the exit code meaningless by design — the launcher exits 0 before pytest exists. Read the
  log's summary line and its `FAILED` lines. (`run-presentation-regression.sh` is the exception: `--bg` is
  a no-op there and its code is real.)
- Capture an exit code immediately and re-raise it at the end. A bash command's status is its last
  command's, so the `echo "EXIT=$?"` you added to surface the code is what replaces it:
  `pytest … > /tmp/tier.log 2>&1; rc=$?; tail -20 /tmp/tier.log; exit $rc`.
- A multi-file pytest invocation reports a union. Quote a per-file result from a per-file run, or quote the
  invocation with the number.
- Before offering a mechanism for someone else's number, ask which test produced it and whether your
  mechanism can reach that test. A mechanism true of the file is not thereby true of the assertion.
- Check how old the process you are testing through is. A stdio MCP server is a subprocess started when
  your seat started, so a fix landing afterwards does not reach it — and the stale subprocess reproduces
  an already-fixed defect on demand, forever. No peer can catch this for you.

### Writing a rule or a guard

- Write the predicate the enumeration is approximating. Any separator run, not four separators; not a word
  character, not eleven characters; the repos the config registers, not the four you remembered. When the
  fix for an enumeration defect is itself an enumeration, you have moved the defect.
- A rule that depends on remembering is not installed. Prefer a tool that refuses.
- Say what a check matches on, and whether your predicate is the whole key or a prefix of it. A check and
  the thing it checks can agree on the field and disagree on the key, and both look correct.
- Sweep for two populations when you retire a name: the passages that *use* it, and the passages that
  *vouch for* it. A wrong instruction gets caught the first time someone follows it; a wrong reassurance
  disarms the reader who would have caught it.
- A row body is the plan as of its writing, not a status. Re-measure before you act on a figure in one.

### Owning the work

- A red you accept is a row you owe. A finding filed as a state, with no owner, reads as closed —
  acceptance without an owner is deferral wearing acceptance's clothes.
- Wait for the worker to say the memento is on disk, with its path and session id, before calling
  `dismiss_sessions`. A reap reports `prior_holder_present` and proceeds, and a stale file in the slot
  looks exactly like a fresh one.
- A memento has two slots and the two doors read different ones: `self_respin` reads the root slot
  (`.claude-memento-<persona>.md`), a manager's reap reads `io/`. Name the slot when you write:
  `memento_io.py write --slot root|io`. Two records for one session is the normal steady state.
- A spawn brief is the one document a seat cannot check on arrival, so the obligation is the writer's.
  Give the population a claim was measured on, and mark inherited claims as inherited.
- Declare a hold with the verb, never by hand-writing JSON:
  `python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io write --session-id <id> …`. A hand-written
  hold lands in the repo root where no reader looks, so the session parks invisibly.


## Documentation touchpoints

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
| `src/lupin_arbiter_app/*` import graph (any NEW third-party import) | **Run `src/scripts/check-arbiter-venv.py` in the arbiter venv and add the package to `src/scripts/requirements-arbiter.txt`.** The standalone `:8001` arbiter runs on a deliberately LIGHT host venv, so an import the venv lacks kills a worker THREAD while the process stays `active (running)` and `/health` returns 200 — invisible for two days on 2026-08-08. Also update `src/rnd/v0.1.9/2026.07.22-arbiter-bringup-on-lupin-host-test.md` §7 and `src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md` |
| A feature gated by an INI flag that imports a heavy/optional module | Read the flag **before** the import (pattern: `fleet_arbiter_loop.make_follow_through_watcher_factory`). A disabled feature must not impose its dependencies — that is what took the fleet loop down while `follow through escalation enabled = false` |
| `lupin-app.ini` `bug fix expediter *` keys | `src/docs/agents/bug-fix-expediter-guide.md` INI Reference |
| `lupin-app.ini` `test fix expediter *` keys | `src/docs/agents/test-fix-expediter-guide.md` INI Reference |
| BFE/TFE endpoint rows | `src/docs/rest-api-reference.md` sections 17/17a/17b |
| `routers/voice_persona.py` + `voice_persona_helpers.py` | `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` (architecture, allocation flow, /clear preservation, conversation-mode orthogonality) + `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` (host-side prune at SessionStart, mtime TTL guard, Sam-as-overflow allocation) |
| `lupin-app.ini` `cc session voice persona *` keys | Same R&D docs — base pool reference in 2026.04.28 §3 (Voice Pool); Sam-overflow keys (`sam icon/color/profile/display name`) + `stale threshold seconds` in 2026.05.16 §Solution Design Layer 3 |
| `lupin_cli/claude_code/hooks/lib/session_bridge.py` `prune_dead_persona_bridges` + `find_active_voice_persona_sessions` TTL guard | `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` (Layers 1–3: host-side prune + mtime TTL) |
| New LLM-driven agent OR migration of an existing agent between bounded-CC and firewalled-SDK paths | `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md`, R&D doc `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md`, auto-memory `feedback_prefer_bounded_cc_over_anthropic_sdk.md`, and CLAUDE.md § "COST MODEL — BOUNDED CC vs FIREWALLED SDK" if guardrails or candidate list change |
| `src/cosa/rest/routers/_scope_registry.py` + `docs_files.py` + `io_files.py` + `lupin-app.ini` `external repo *` keys + `docker-compose.yml` bind-mounts | `src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md` (scopes table, mount lines, blocklist patterns). Adding a new external scope requires the four-step checklist in auto-memory `feedback_multi_repo_doc_viewer.md`. |

**Documentation index**: `src/docs/README.md` — lists all docs with verification dates.

**Fleet liveness + unified task-store architecture (top-to-bottom)**: `src/docs/fleet-liveness-and-task-store-architecture.md` — the canonical reference for the one-store/three-readers design (Stop-hook self-poke · `:8001` arbiter · human UI card), the heartbeat seam + `heartbeat.owed_source_from_store` cutover flag + fail-safe, the arbiter detectors (staleness 2700s / tap-ACK 600s / whole-fleet-stall 1800s) + how to bounce it (`systemctl --user restart lupin-arbiter-app.service`), the manager/worker spawn→worktree→review→merge-held→push lifecycle, and the migration drain. Read this before touching the liveness path, the task store, or the arbiter.

**Declaring a hold (parking a session) — use the VERB, never hand-write the JSON**: to park a session with a hold, run the `heartbeat_hold_io.py` **write** verb — it records the hold AND verify-reads it back so the hook will actually honor it. **Never hand-write a `.heartbeat-hold-*.json` file** (Write tool or `>`): a hand-written hold lands in the **repo root**, where no reader looks — the arbiter and the Stop hook both resolve holds under `fleet_data_root()` — so the session parks **invisibly** and the poke keeps coming (row `011f1f90`). One example beats a paragraph:

```bash
python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io write \
  --session-id <id> --persona "You 😎" --reason "<why holding>" \
  --ttl-seconds 14400 --awaiting "user:<name>"
```

> **History — the instruction was already correct, and was ignored anyway.** `planning-is-prompting → workflow/fleet-pause-resume.md` did once prescribe hand-writing the JSON, and that was corrected on **2026-07-21** (commit `0f39b03`). Since then line 77 has read *"Write the hold with the VERB, not by hand"*, line 87 *"Do not hand-write `.heartbeat-hold-<id>.json`"*, and the schema block is explicitly fenced *"Schema reference only — NOT the instruction, do not hand-author it."*
>
> **All 14 lupin repo-root holds are dated 2026-07-31 to 08-04 — every one written AFTER that fix.** Fleet-wide the split is about half: of 33 misplaced files, 16 predate the fix and 16 postdate it. So a correct doc changed nothing for half the population, and nothing at all for lupin.
>
> That is why this note is not the remedy. **The remedy is the detector** (`hold_is_misplaced` + the `misplaced` field in the arbiter's sweep, row `011f1f90`), which catches the file regardless of what anyone read. A rule that is written down but not enforced is a rule that half the fleet will break — treat the doc as a courtesy and the detector as the control.

**Principle**: FastAPI `/docs` and `/redoc` are the authoritative API reference. Hand-written docs cover architecture, concepts, and operations only.

## History structure notes
- **Project Span**: December 2024 - Present (Lupin evolution from Genie-in-the-Box)
- **Key Archived Periods**: 
  - 2024.12-2025.05: PEFT training, agent migrations, Flask→FastAPI transition
  - 2025.06: Lupin renaming, notification system, WebSocket foundation
  - 2025.07: Progressive TTS streaming, user routing architecture
  - 2025.08: Unit testing framework, Fresh Queue UI, audio debugging
- **Current Implementation Docs**: Referenced in history.md header
- **Archive Location**: `history/` directory with monthly organization

## Doc viewer scope (unified path-prefix routing)

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
