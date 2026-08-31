# LUPIN DEVELOPMENT GUIDE

## COMMANDS
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (Runs on port 7999)
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

Already migrated: **BFE** (`src/cosa/agents/bug_fix_expediter/`), **TFE** (`src/cosa/agents/test_fix_expediter/`), **Podcast script generation** (`src/cosa/agents/podcast_generator/` — Phase 1, 2026-06-18; in-process `sdk_query`, `tools=[]`, D6-lenient parsers), **Presentation content generation** (`src/cosa/agents/presentation_generator/` — Phase 2, 2026-06-18; 7 methods → `sdk_query`, D6-STRICT parsers, Gemini path untouched), **Deep Research** (`src/cosa/agents/deep_research/` — Phase 3, 2026-06-18; lead agent `tools=[]` + research subagents `tools=[WebSearch, WebFetch]` replacing native `web_search_20250305`, ARM web-search gating dropped, D6-STRICT parsers).

Migration candidates (tracked in TODO.md): the three ratified bounded-CC migrations (Podcast → Presentation → Deep Research) are all complete. Remaining opportunities are deferred per D4/D5 (OpenAI call sites, Runtime Argument Expeditor) — not yet ratified for migration.

**Framing**: this is a **cost-shift, not zero-cost**. The Max 200 plan is a fixed monthly bill. Migrations convert per-token metered spend into already-paid fixed cost. Never describe a migration as "free" — describe it as "covered by existing fixed cost."

### When NOT to migrate

- High-frequency tiny calls (>~10 QPS) — subprocess spawn overhead dominates. Keeps: `notification_proxy/strategies/llm_fallback.py`, `decision_proxy/`.
- Hard latency budget < ~2 seconds.
- Non-Anthropic models required (OpenAI/Groq/Mistral/etc. — Max plan only covers Claude).
- Token-by-token streaming UX (bounded CC returns on completion, no progressive streaming).

### Off-peak scheduling rule (operational)

Max-plan usage has rolling-window limits. Batch bounded jobs running during Rick's interactive peak window can throttle his real Claude Code work.

⚠️ **CORRECTED 2026-08-17 (Rick's ruling, row `f0b3f630`). The old window pointed at hours the box is powered OFF.** It read "Optimal: 12 AM – 9 AM EDT (Rick asleep, zero interactive use)" — true about Rick, false about the machine. Measured boot history, unbroken since Aug 5: the host is **DOWN ~10:53 PM – 7:17 AM**. Every seat that followed the rule correctly still had its job sit dead until the next boot and drain hours late — two jobs scheduled for 00:30 and 01:15 ran at ~10:07 the next morning.

⚠️ **CORRECTED AGAIN 2026-08-20 (Rick's ruling). The 08-17 correction replaced hours the box was OFF with hours it is usually NOT UP YET — same failure, one step smaller.** It named **7:30 AM** as the start, derived from a single boot at 07:17 on Aug 6. **Measured across the 12 morning boots since Aug 4** — `08:52 · 09:27 · 07:17 · 09:14 · 09:52 · 09:56 · 09:20 · 10:52 · 09:48 · 09:03 · 09:17 · 09:43` — the **median is 09:24 and eleven of twelve are after 08:52**. A job placed at 7:30 sits dead ~1.5–2.5h on almost every day.

⚠️ **RE-MEASURED 2026-08-30 (Krishna 🦚, row 9078a035 · commit 2df3aefb). THE WINDOW HOLDS; THE FIGURES BELOW ARE NOW OPTIMISTIC — AND THIS IS AN UPDATE, NOT A CONTRADICTION.** Taking `last -x reboot | head -20` afresh gives **16 morning boots** spanning Aug 10–30: `09:27 · 10:15 · 09:35 · 09:27 · 11:58 · 11:01 · 09:53 · 09:19 · 09:43 · 09:17 · 09:03 · 09:48 · 10:52 · 09:20 · 09:56 · 09:52` — **median 09:45, earliest 09:03, latest 11:58**, shutdowns clustering 22:26–00:20.

**The two samples RECONCILE rather than disagree**, which is the only reason to trust either: the 08-20 list starts Aug 4 and includes the 07:17 outlier from Aug 6 that sits outside this window; this list adds six newer days and no boot in it is before 09:03. **The distribution moved later — median 09:24 → 09:45 — so 10 AM – 1 PM is more right than when it was written, not less.** What is now stale is the **9 AM** boundary in the DEAD row and the "well past 8:52 AM" phrasing: on this sample the box is usually still down at 9:30, and on two of sixteen days past 11:00. Read the dead window as ending at **10 AM**.

⇒ **This is the third measurement of the same rule and the first one that did not move the recommendation.** That is what a stabilising figure looks like — but it is still 16 samples, so re-derive rather than quote this paragraph too.

🔴 **DO NOT TRUST THIS TABLE EITHER — RE-DERIVE IT.** This rule has now been wrong twice, both times because someone generalised from too few boots. **Measure before you schedule:**

```bash
last -x reboot | head -20      # read the morning boot times yourself
```

**The constraint is the box, not just Rick's sleep:**

| Window (EDT) | Verdict | Why |
|---|---|---|
| ~11 PM – 10 AM | ☠️ **DEAD — never schedule here** | Host is usually powered off, and on most days is still down past 09:30 (16 boots to Aug 30: median 09:45, earliest 09:03, two past 11:00). A job here does not run late — it does not run at all until boot. |
| 9 PM – 11 PM | ❌ Peak — avoid | Rick's interactive window; competes with his real work. |
| **10 AM – 1 PM** | ✅ **OPTIMAL — schedule batch work here** | Comfortably after the median boot (09:24 on the Aug-4 sample, 09:45 on the Aug-30 one — it moved later, so this window got safer). Rick is barely on. The only window reliably both up and quiet. |
| 1 PM – 9 PM | 🟡 Acceptable | Box up, some interactive use, well below peak. |

**Rule**: any non-interactive bounded job (batch generation, scheduled regression sweeps, podcast/presentation/research) MUST set `scheduled_at` inside a window the box is UP for — **prefer 10 AM – 1 PM EDT** — via `/api/v2/submit` (field defined on `SubmitRequest` at `src/cosa/rest/routers/v2_ask.py`). User-clicked synchronous bounded jobs are exempt.

⚠️ **CHANGED 2026-08-21.** This line used to name `/api/claude-code/submit`. That door and its `/api/claude-code/queue/submit` alias are now tombstones answering **410 Gone** (Rick's ruling: the Claude Code job is *upgraded* to the v2 front door, not left to die on the vine). The work enters through `/api/v2/submit` naming the command `agent router go to claude code`; `scheduled_at` stays TOP-LEVEL because it tells the queue *when* to run, and `args` is checked against the command's own argument contract, which no scheduling instruction is in.

⚠️ **And the box goes down mid-day too.** On 2026-08-20 it was down **14:34–18:07**. "Optimal" means *most likely up*, never *guaranteed up* — a long job should still tolerate a restart.

**If a job does land in the dead window**, the catch-up is no longer silent: `job_persistence.py` emits a `[CJ-CATCHUP-LATE]` line naming `scheduled_at` vs actual and hours-late (`fef78ce3`, with a negative control at `f0b7c589` proving it stays quiet on every non-catch-up path). A late drain is now visible rather than reported as a normal run — but visible-and-late is still late.

Example:
```json
POST /api/v2/submit
{
  "command"      : "agent router go to claude code",
  "args"         : { "prompt": "…", "task_type": "BOUNDED" },
  "scheduled_at" : "2026-08-22T11:00:00-04:00"
}
```

(This example used to read `02:30` — inside the dead window. A copied example is how a bad window propagates faster than the prose that describes it.)

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
  - `../lupin-mobile/history.md` (Mobile app — a SIBLING of lupin since 2026-08-30, no longer under `src/`)
  - (`src/cosa/history.md` is **no longer** a sub-repo history — CoSA folded into the mono-repo 2026-05-29; it is now a normal in-tree doc.)

## PROJECT SHORT NAMES
- This repo's SHORT_PROJECT_PREFIX is [LUPIN]

## REPOSITORY RELATIONS
- There is another repo that's a part of the larger project contained in the directory `lupin-plugin-firefox`
- This repo must be managed separately and cannot be managed by Claude

## RUNNING/TESTING FASTAPI APPLICATIONS
- Please assume that there is a Fast API server instance bound to port 7999. I will start and stop it if needed. You never need to spin up another instance unless it's for a ephemeral use on port 8000.
- **Before clicking Resume on any TFE/BFE stalled job, or before scheduling a live E2E run on `:8000`**, run `src/scripts/preflight-test-container.sh` (or `pytest src/tests/smoke/test_container_preflight.py -v`). This catches docker-compose.yml drift — cases where a `.git`, credentials, or other bind-mount change has not been applied to the running container because only `docker rm -f` + `docker compose up -d` picks up new mounts (not `docker restart`). Failure output includes the exact remedy.
- **Server lifecycle (when does a change land? when do I bounce? which command?)**: See skill `server-lifecycle` — encodes the per-server decision matrix, the restart-vs-`--force-recreate` distinction, the queue-check courtesy, and the `:8000` monopolize-mode protocol. Auto-fires on bounce/restart/refresh/rebuild phrasing including ASR variants ("doctor" → "Docker").
  - ⚠️ **CHANGED 2026-08-01 — two policy changes the same day.** (1) `uvicorn --reload` is now **OFF by default on `:7999`**, opt-in via `LUPIN_RELOAD` and gated by `reload_enabled()` in `bootstrap_helpers.py` — watching the tree was taking the server down for the whole fleet whenever anyone touched a watched file. **A `.py` change no longer goes live on its own; both servers need a bounce now.** (2) The old "never volunteer a `:7999` bounce" rule is **retired** — anybody may bounce `:7999`, within reason, to pick up fresh code.
  - **Use the sanctioned path**: `./src/scripts/bounce-dev-server.sh` (`--quiet` for a one-liner). It posts an **ack-confirmed** warning broadcast so the fleet holds notifications *before* the server dies, restarts the container, and polls `/health`; the **all-clear is emitted by the restarted server's own startup hook**, so it covers every restart path.
  - **`restart` ≠ `--force-recreate`**: mount specs and env resolve at container **CREATE**. Changed `docker-compose.yml`, a bind mount, or an env var? Use `docker compose up -d --force-recreate <svc>` — a restart reuses the old values and your change silently does not land. (This is also why re-arming `LUPIN_RELOAD` needs a recreate.)

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
   - **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin-mobile/` — a **SIBLING** of the Lupin repo since 2026-08-30, moved out of `src/`. It is no longer nested, so it will not appear in Lupin's `git status` at all.
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
• ../lupin-mobile/ (1 new file — sibling repo, detected only if explicitly scanned)

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

**When working in Mobile App** (`cd ../lupin-mobile/`):
- Manage as independent project
- Has own git history and workflows

## 🔴 A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED

**Five instances in one evening, 2026-08-30, in five different tools.** Written as one rule because
five seats each found it separately and none of them recognised it as the same shape until they were
put side by side.

| tool | the clean-looking result | what it actually meant |
|---|---|---|
| `--cov=<bad target>` | exit 0, no coverage table | **nothing was ever measured** |
| `migrate-pyc…--verify` on a fresh tree | exit 0, ✓ | **nothing there to judge** — vacuous, not converted |
| `purge-pycache.sh --verify` | exit 0 | **flag ignored**, and it purged |
| `purge-pycache.sh` on an emptied tree | exit 0, *"nothing to purge"* | **it never ran** — the previous command had emptied it |
| `rc == 1` as a mutation kill | looks like a kill | the suite was **already red** at baseline |

⇒ **THE FAILURE AND THE SUCCESS PRINT THE SAME THING.** In every case the caller checked the exit
code, saw what they expected, and carried a conclusion forward that the tool had never supported.

🔴 **THE FIX IS A TOOL THAT REFUSES, NOT A CALLER WHO CHECKS** (Rachel 🕊️, correcting the first cut
of this rule, which asked the reader to be vigilant — and a rule that depends on remembering is not a
control, which is this page's own doctrine).

**A tool facing a job it cannot finish has two options, and only one of them is honest:**

| ❌ no-op and report cleanly | ✅ REFUSE and say what it did not do |
|---|---|
| purge, then fail to reconvert, exit 2 with the caches gone | `Refusing to purge: the reconvert would fail. 1 __pycache__ directories left untouched.` |
| apply a mutation at a guessed location | `ANCHOR MATCHED 2x — NOT APPLIED` |
| report coverage for a target never imported | name the target and say it was never imported |

**Both live examples are from tonight and both are ours**: Rio's purge script declines *before* the
`rm` when the reconvert cannot run, and Rachel's mutation harness skips an arm whose anchor matched
twice rather than guessing at placement. **Neither leaves the caller a clean-looking result to
misread**, which is what makes them different in kind from a checking rule.

⇒ **Build this into anything you write.** A step that cannot complete must decline the whole
operation and name the part it did not do — never half-finish and return a status the caller can read
as success.

**Until a tool refuses, the caller's fallback is the tool's own account of what it touched — never
the exit code:**

| ask | not |
|---|---|
| does the coverage table list the file? | did it exit 0? |
| does the verify name **your** tree in *scanned roots*? | did it print ✓? |
| does the purge report a **count** matching what you planted? | did it say nothing to purge? |
| did a **named test that was passing** now fail? | is `rc` non-zero? |

⚠️ **THE SECOND-RUN TRAP, and it is the one that nearly published a wrong result** (Rachel 🕊️): she
ran arm B of a two-arm comparison *after* arm A had already emptied the tree. It printed **"nothing
to purge"** and **exited 0**, and the check afterwards then failed — reading exactly like *arm B does
not work* when arm B **had not run at all**. She caught it because the phrase did not match a tree she
had just populated by hand.

⇒ **In a two-arm comparison, each arm needs its own freshly built state**, and **read the tool's
narration, not just its status.** An arm that no-ops because the previous arm consumed its input is
indistinguishable from an arm that failed — and it is the second arm, the one you are testing, that
gets the blame.

## 🔴 THE OVERCLAIM HIDES IN THE **JOIN**, AND GREP CANNOT FIND IT

**Three seats produced this independently on 2026-08-30**, which is why it is a rule and not a note
about one careless commit. Two true, separately-measured statements get welded with a *because*, a
*so*, or a *which means* — and the weld is a third claim that nobody measured.

| what was measured | what got written |
|---|---|
| a frame was addressed to a stored id · the answer never arrived | *"the answer never arrived **because** the frame was addressed to a stored id"* — the second half had a separate upstream cause |
| a worktree's pycs are timestamp-based · an author's pass reported a kill | *"his pass was wrong **because** his pycs were timestamp-based"* — an innocent path (ran it pinned, misread the exit code) was never ruled out |

**Why it survives review, including your own.** Pocholo 📣 searched his commit for the words he had
withdrawn, found none, and reported the claim as living only in a DM. **It was in three permanent
places.** His diagnosis is the durable part: *he grepped for the WORDS, and the overclaim was in the
causal JOIN, which contains none of them.* A join is made of the relationship between two sentences;
there is no string to search for.

⇒ **Read your conjunctions one at a time.** For every *because* / *so* / *which means* / *therefore*,
ask: **did I measure the LINK, or only the two ends?** If only the ends, state them as two facts and
stop — the reader can draw the arrow, and if the arrow is wrong your facts still stand.

⇒ **It bites hardest where it lasts longest.** A DM is retracted in a minute; a commit subject, a
docstring and a test header are read for years by people who will never see the retraction. **Where
a claim is durable, spend the extra sentence** — and when you withdraw one, *"a retraction must reach
the artifact, not just the conversation"* (Pocholo, on finding his had not).

⚠️ **NAMING A PERSON RAISES THE BAR, IT DOES NOT LOWER IT.** The worst of the three inferred what a
named colleague had done and stated it as a finding. **Strip it to what you measured** — *his pycs
were timestamp-based* is a fact about a tree, and it carries the same rule without assigning anyone
an error you did not observe.

## 🔴 A COORDINATE IS NOT A REFERENCE — NAME THE CONTENT

**Derived independently three times on 2026-08-30** — Tiberius 👑 and Maya 🌻 from different
directions, and a third time when this reviewer handed a peer `CLAUDE.md:888` as an insertion point
for a file that had already moved several times that day, by the very commit under review. Written
here because a lesson three seats reach separately is one the file should have carried already.

**A coordinate says WHERE something sat when you looked. A reference says WHAT it is.** Only the
second survives someone else editing between your reading and their acting — and in a fleet, someone
always does.

| Don't hand over | Hand over |
|---|---|
| `CLAUDE.md:888` | the anchor sentence, verified to match **exactly once** |
| `stash@{2}` | the commit sha (`git rev-parse` it first) |
| "the third finding in the output" | the finding's own text or id |
| "the file I edited earlier" | the path, and the sha or content hash you read |
| "as of tonight" | the sha, or the wall-clock time of the read |

**The tell is mutability, not format.** A line number in a frozen artifact is fine; a line number in
a live file is a bet that nobody edits above it. `stash@{N}` renumbers when any entry is dropped —
that hazard is already in the global CLAUDE.md, and this is the same defect wearing a different
notation, which is exactly why it keeps being re-derived instead of recognised.

**When you must point at a position, make the pointer self-checking**: give the anchor text, say it
must match **exactly once**, and say what to do when it matches zero or twice — *come back to me*,
never *guess at placement*. A pointer that cannot fail is a pointer that silently lands in the wrong
place.

**AND THE SAME RULE GOVERNS THE CHANNEL, NOT ONLY THE POINTER** (Maya 🌻 §1.5.1b — *adapt what you
send to the channel you measured*). Text sent between sessions is **condensed in transit**, and a
condenser reorders and drops. Measured 2026-08-30: an insert handed to a peer for verbatim paste
arrived **summarised**, and he correctly rebuilt it from its three points rather than pasting what
he received — the hand-off worked only because he flagged it. ⇒ **Send a to-be-pasted artifact
BARE — one artifact per message, no surrounding prose for the condenser to fold it into** — and say
plainly that it is verbatim. A paragraph explaining the paste is the thing most likely to absorb it.

⚠️ **THIS DOES NOT CONTRADICT "STATE THE COORDINATES", AND THE TWO ARE EASY TO READ AS OPPOSITES.**
They govern different acts. **Reporting a measurement**: state the coordinates — the sha, the frame,
the root set, the wall-clock time — because without them a reading is not wrong, it is
*unfalsifiable*. **Pointing someone at content**: name the content, because a coordinate is what
goes stale. ⇒ *Coordinates make your reading checkable. Content-names make your pointer durable.*
Say what you measured **and** name what you mean.

## TESTING VENUES

**MANDATE**: Every automated test runs on exactly one of two servers. Pick by rubric, never by habit.

> 🔴 **THE TWO VENUES ALSO HAVE TWO DATABASES, and a host shell silently reads the wrong one.** Neither container sets `DB_NAME`, so each falls through to its own config block: `lupin-rest-dev` → **`lupin_db_dev`**, `lupin-rest-test` → **`lupin_db_test`**. A host shell inherits the *Development* block, so `PYTHONPATH=src python3` on the host queries **dev** even when the job you are chasing ran on `:8000`.
>
> **Measured 2026-08-28**, both directions inside a minute: host/dev returned **205 rows, zero `ts-` rows, nothing newer than the previous day**; the same query inside `lupin-rest-test` returned **4 rows, all same-day**, including the one at issue. The host answer reads exactly like *"test_suite jobs are never persisted"* — which is false, and a correct fix was one message from being retracted on it. **An empty result from the wrong box is not evidence; it is a confident answer to a question you did not ask.**
>
> ⇒ **Go at the database container and NAME the database** — `docker exec lupin-postgres psql -U lupin_dev -d lupin_db_test -c "..."`. Better than "run it inside `lupin-rest-test`", which still depends on standing in the right place — the thing that failed. **There is no default to fall through to**, verified both ways: a wrong name gives `FATAL: database "lupin_db_typo" does not exist`, and *omitting* `-d` errors too (psql tries the username as the database). You either name the box you meant or you are told. The in-container route lacks that property — it reads *a* database successfully either way.

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
- `src/tests/smoke/test_memory_cap_binds.py` — ⚠️ it EXECUTES `systemd-run` and gets a process
  SIGKILLed, which reads like a :8000 suite and is not one. Routed by the rubric: the scope is
  transient (`--scope --collect`, dies with the command), so nothing persists; ~0.5s; and the only
  process it kills is the allocator it started, inside a cgroup it owns — which is the very
  property one of its cases asserts. It needs no monopoly and takes none.
- `src/tests/websocket_smoke/` (run via `src/scripts/run-websocket-smoke-tests.sh`)

### :8000 (test) — monopolize mode, scheduled only

Submit via `POST /api/test-suite/submit`. **Self-authorization rule (2026-06-06): a verified-IDLE `:8000` — nothing running, nothing scheduled — is bounce-then-schedule SELF-AUTHORIZED; the user is NOT a gate.** Only **killing a LIVE in-flight job** needs the user's word. **Never** inject via ad-hoc curl, direct queue push, or in-process server instantiation — side-door injection collides with in-flight scheduled runs and poisons both.

🔴 **HOW YOU VERIFY IDLE — one command, and its exit code (row `e6b8fe56`, 2026-08-25).** This rule already said to read the queue, and a seat that followed it was never reading `monopolize_id` — **the rule itself was not the defect** (Tiberius's caller audit, `7f935140`, `src/rnd/v0.2.0/2026.08.24-monopolize-as-idleness-caller-audit.md`). What was missing is a single reliable way to do what it asks. `pool-status` cannot be that way: **measured** against real queues, `monopolize_id` moves for exactly ONE condition — a monopolize-flagged job that has already **started** — so it answers *which job holds the slot*, an identity question, and says nothing about work that is QUEUED, running INLINE on the consumer thread (row `99b09840`), or in the shared pool. **And the queue listings cannot do it alone either**: `/api/get-queue/{q}` is **user-filtered** and the gate account is not an admin — `?user_filter=*` answers **403**, so a peer's queued job is not in your listing at all.

```bash
PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000 ; echo "exit=$?"
```

**The exit code is the answer: `0` IDLE · `1` BUSY · `2` UNKNOWN.** It reads the unfiltered, unauthenticated `GET /api/busy` — run depth, **todo depth**, shared-pool inflight, monopolize slot — and every lane must be empty. 🔴 **UNKNOWN IS NOT IDLE.** UNKNOWN with only `todo_queue_size` missing means that container predates this row and cannot see waiting work; the remedy is a **bounce** (a code pickup), not a `--force-recreate`. Treating a signal's absence as proof of absence is the defect itself.

**Placement, once you have a `0`:** empty queue → bounce (to clear static-snapshot drift, see §reference) + schedule + run now; something already SCHEDULED (queued, not yet running) → still self-authorized, but set `scheduled_at` AFTER the queued job (never jump an expected-next run); something RUNNING → queue behind it, no bounce.

Eligible if **any**:
- Mutates persistent state (DB rows, shared files, LLM API spend, enqueues jobs).
- Runtime > 2 minutes.
- Needs server monopoly (E2E UI, integration, regression sweeps).

Suites that qualify:
- `src/tests/smoke/test_proxy_integration.py` (any scenario — CRUD + expediter mutate state)
- `src/tests/run-integration-tests.sh` (final merge gate)
- `src/scripts/run-e2e-ui-tests.sh` (functional + visual)
- `src/tests/run-presentation-regression.sh` (all variants)

The AI **self-authorizes** :8000 runs on a verified-idle server (logged, no human gate) and owns both scheduling and executing. The ONLY user-gate is **killing a live in-flight job**. Never budget approval, never tester-duty deferral, never an idle-slot ask.

### The `src/tests/smoke/` caveat

The directory name is not a venue marker. Files living in `src/tests/smoke/` can still be destructive or long-running (e.g. `test_proxy_integration.py`). Route each file by the rubric above, not by folder.

### When in doubt → :8000

:7999 is an optimization for truly fast, truly read-only work. If you cannot prove a test meets all three :7999 criteria, schedule it on :8000.

### 🔴 A TIER RUN FROM A WORKTREE REPORTS 10 OR 11 FAILURES THE MAIN TREE DOES NOT HAVE

**Which of the two you get is decided by ONE thing: whether you exported `LUPIN_ROOT="$PWD"`.** Both numbers below are correct; they are measurements of two different setups, not a disagreement. See the reconciliation under the table.

**Measured 2026-08-29** (row `3d01df71`). Two seats ran the unit tier on the same sha `31b2cfce` within the hour and got **25 failures in a worktree** against **14 in the main tree**. Neither number was wrong. The gap is **exactly 11 in that setup** — INFERRED (not measured) to be without `LUPIN_ROOT="$PWD"` exported, from the fact that its third row fired at all; with the export it is 10, and the two reconcile (see below) — and all of it is state that is present in the main tree and absent from every worktree — so a worktree tier accuses the branch of breakage it does not have.

| n | what is missing | how it surfaces |
|---|---|---|
| 9 | `src/scripts/cloud-run.env` — **gitignored** at `.gitignore:79` | `gcp_project.py:115` `RuntimeError: LUPIN_GCP_PROJECT_ID is not set…` ×8, plus `KeyError: 'dm_tutor/flash_lite'`. The whole flash-lite / vertex family. |
| 1 | `src/terraform/envs/test/.terraform/providers` — untracked local cache | `test_terraform_invariants.py` — "provider plugins are NOT cached at …" |
| 1 | nothing missing — **`LUPIN_ROOT` still names the MAIN repo** while you stand in the worktree | the tests catch this one themselves and print `test file` / `its tree` / `LUPIN_ROOT` side by side |

**Before running a tier from a worktree:**

```bash
cd <your-worktree> && LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/ -q
```

`LUPIN_ROOT="$PWD"` is the one you must not forget — it is inherited from your shell and silently keeps pointing at `/…/lupin`. The other two are unfixable from inside a worktree: **subtract them, do not chase them.**

**RECONCILED 2026-08-30 — a second measurement got 10, and 10 and 11 are the SAME finding.** Rio ⚡
ran the unit tier at sha `cc336880`, root `/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-rio-8593bf65`,
with `LUPIN_ROOT="$PWD"` exported, and measured a gap of **10** — not 11.

| | 2026-08-29 (row `3d01df71`) | 2026-08-30 (Rio, sha `cc336880`) |
|---|---|---|
| `LUPIN_ROOT` exported? | **no** | **yes** |
| flash-lite / vertex (`cloud-run.env`) | 9 | 9 |
| terraform provider cache | 1 | 1 |
| wrong-tree `LUPIN_ROOT` row | **1** | **0 — never fired** |
| **gap** | **11** | **10** |

⇒ **The third row of the table above is the entire difference, and it is the one this section
already tells you to fix.** Follow the remedy and the gap is 10; skip it and the gap is 11. So the
two counts agree completely once you know which setup produced each — which is why this section is
amended to carry BOTH rather than overwritten to the newer one. **Per this section's own closing
rule: two counts get RECONCILED, not adjudicated, and a mismatch that reconciles is not a
disagreement.** A doc that had simply replaced 11 with 10 would have made the next reader who
forgets the export think they had found a new failure.

**Verified both directions, not asserted.** The four files carrying those 10 artifact failures —
`test_dm_tutor_flash_lite_routing.py`, `test_flash_lite_arm_vertex_markers.py`,
`test_phi4_flash_lite_replay.py`, `test_terraform_invariants.py` — were re-run WHOLE in the MAIN tree
at `625665bb`: **120 passed, 1 skipped, 0 failed**. (120 is every test in those four files, not the
10 failures; the 10 are a subset that passed along with the rest.) and the two missing inputs were checked on both
trees: `src/scripts/cloud-run.env` and `src/terraform/envs/test/.terraform/providers` are PRESENT in
the main tree and ABSENT in the worktree.

🔴 **AND A THIRD MEASUREMENT FOUND A THIRD VARIABLE: WHETHER THE WORKTREE HAS A `.venv` AT ALL.
WITHOUT ONE THE GAP IS 43 OR 44, NOT 10 OR 11 — AND THIS IS THE SAME FINDING AGAIN, NOT A NEW
DISPUTE.** Measured by Maya 🌻 2026-08-30 at sha `a4fd4551`, root
`/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-maya-5246-mergecheck`, `LUPIN_ROOT="$PWD"`
exported. **The two rows above silently assume a `.venv` is present** — the remedy block prescribes
`.venv/bin/python`, so a tree without one cannot even run the command this section hands you, and
the reader who hits that has no number here to land on. Now they do.

| | 08-29 (`3d01df71`) | 08-30 (Rio, `cc336880`) | 08-30 (Maya, `a4fd4551`) |
|---|---|---|---|
| `LUPIN_ROOT` exported? | no | yes | **yes** |
| worktree has a `.venv`? | **yes** | **yes** | **NO** |
| flash-lite / vertex (`cloud-run.env`) | 9 | 9 | 9 |
| terraform provider cache | 1 | 1 | 1 |
| wrong-tree `LUPIN_ROOT` row | 1 | 0 | 0 |
| **missing-`.venv` rows** | **0** | **0** | **33** |
| **gap** | **11** | **10** | **43** |

**Verified both directions, in one tree, flipping one variable.** The seven files carrying those 33
— `test_coverage_frame_excludes_non_src.py`, `test_coverage_gate_tier_status.py`,
`test_presentation_regression_tier_classification.py`, `test_runner_collection_diagnosis.py`,
`test_runner_coverage_blindness.py`, `test_runner_venv_pytest_guard.py`,
`test_v2_survives_v1_excision.py` — fail with no `.venv` and give **124 passed, 1 skipped, 0 failed**
the moment the main repo's `.venv` is symlinked in. The failure is a plain
`FileNotFoundError: …/<worktree>/.venv/bin/python`. **And the branch under test was exonerated by a
control, not by subtraction**: the same 33 reproduce identically at the base with the branch's merge
absent — `comm` empty in both directions, not merely equal counts.

⚠️ **THE 44th IS NOT AN ARTIFACT.** The raw tier reported **44 failed**; 43 are environment and the
last is `test_secret_scan::test_a_detector_change_forces_a_full_rescan`, a known branch-level red
held until a credential rotation lands. **Subtract 43, never 44** — folding a real held red into an
artifact count is how a genuine signal gets explained away by its neighbours.

🔴 **AND HERE IS THE PART THAT GENERALISES: A POPULATION CHOSEN BY GREP CANNOT FIND BREAKAGE OUTSIDE
THE GREP.** Row `9b2abfb7` carries an earlier count of **14 → 1** across the 25 unit files whose text
mentions `.venv`, and that number was reached the RIGHT way — by running both ways rather than
assuming. Re-running that same method at `a4fd4551` (30 such files today) gives **19**, while the
whole tier gives **33**. The two do not conflict: the grep-derived failures are a strict **subset**
of the tier's, and the **14** extra live in `test_presentation_regression_tier_classification.py`
and `test_runner_collection_diagnosis.py`, which mention `.venv` **zero times** — they shell out to
a runner that resolves the interpreter for them. ⇒ **Running instead of grepping fixed the
verification and left the SELECTION grep-shaped, so the improved instrument still could not see 14
of its own class.** Widen the population before you widen the trust; the honest scope line is *"14
failures across the files that name it"*, never *"14 failures."*

⇒ **Wiring this symlink into the spawn path is row `9b2abfb7`** (Krishna 🦚, blocked on Rick's word —
the spawn path is shared infrastructure every future seat inherits). Until it is ruled, symlinking is
a manual step, and a step that depends on remembering is not installed. **The measurement above is
what a forgotten step costs: 33 red tests that look like a broken branch.**

⚠️ **AND SUBTRACTING THE ARTIFACTS IS NOT THE WHOLE JOB — CHECK WHETHER THE BRANCH MOVED.** In the
same reconciliation, 8 of the 9 remaining failures also passed in the main tree, and it would have
been wrong to file them as worktree artifacts too: the main tree was a **descendant** of the
worktree's sha, 12 commits ahead, and those 8 had been FIXED in that window (`51950988` for the
manager-figure stamp; the venv-declaration guard across `20dc6b18`, `71637fe1`, `625665bb`). **A
failure that passes in the main tree has TWO explanations — a worktree artifact, or a fix you do not
have yet.** Reporting the second as the first credits your environment for somebody else's repair.

⚠️ **AND THE TWO-STEP THAT SEPARATES THEM IS NOT ONE COMMAND** (Tiberius 👑, reviewing this section
2026-08-30 — the original text said "`git merge-base` tells you which", which OVERSTATES what it
returns). `git merge-base --is-ancestor <your-sha> <main-HEAD>` establishes **ancestry**, which shows
only that a fix **COULD** be missing. What proves one **WAS** is **naming the commit**:
`git log --oneline <your-sha>..<main-HEAD> -- <the failing test's path>`. Ancestry narrows the
suspects; the commit closes it. A section whose whole theme is descriptions drifting from evidence
should not itself claim more than its command returns.

⚠️ **THE SAME MISMATCH IS HARMLESS IN ONE DIRECTION AND SILENT-FATAL IN THE OTHER — SO READ THE
WARNING, THEN ASK WHAT THE CODE WRITES.** Measured by Maya 🌻 2026-08-29, and added here rather than
in a second section because it is a refinement of the three traps above, not a new one. Three cases,
and they are not equally bad:

| What the code writes | With a wrong `LUPIN_ROOT` | How bad |
|---|---|---|
| **Code path** — imports, runs a suite | your edits are not what runs; the tree you stand in is not the tree imported | misreports **your own** work, silently |
| **Shared data, path NOT derived from `LUPIN_ROOT`** | lands correctly anyway | noise — *if* you read the result back |
| **Shared data, path derived from `LUPIN_ROOT`** | writes where nobody reads, or into another repo's state | **worst** — corrupts **another seat**, not you |

🔴 **I FIRST WROTE THIS AS "HARMLESS ON A SHARED-DATA WRITE" AND THAT WAS UNDERBUILT.** Harmless is
a property of the RESOLVER, not of the destination: it holds only when the path does not derive from
`LUPIN_ROOT`, and I had not checked that it doesn't before saying so. The correction is the bottom
row, and it is the one that matters — a code-path mistake misreports your own work, a shared-data
mistake corrupts somebody else's.

**The measured case, and why it is the middle row rather than the bottom one.** The heartbeat-hold
verb printed this section's WRONG-TREE warning at me — shell `LUPIN_ROOT` still naming `/…/lupin`
while the file sat in my worktree — and the hold was still correct. Not by luck: `fleet_data_root()`
calls `_main_repo_path()`, which collapses a worktree to its parent checkout, so the destination is
invariant under the choice. Verified both ways rather than read off the source:

```
LUPIN_ROOT=lupin                    -> …/projects-data/lupin
LUPIN_ROOT=lupin-wt-maya-ba6df71e   -> …/projects-data/lupin      # identical
```

Had that resolver taken `LUPIN_ROOT`'s basename instead, the hold would have gone to
`projects-data/lupin-wt-maya-ba6df71e/`, where the arbiter and the Stop hook never look — a session
parked invisibly, which is the bottom row and the exact failure row `011f1f90` exists to catch.

⇒ **A wrong-tree warning is not one severity.** Ask which row you are in before deciding whether to
act on it — and on the middle row, still read the result back, because "it landed correctly" is a
claim until you have seen it.

⚠️ **AND IT REACHES CONFIGURATION, NOT ONLY COVERAGE.** Measured 2026-08-29: two seats disagreed about whether `"src/scripts"` was in `pyproject.toml`'s coverage source list. It was present at HEAD (1), present in the worktree after a merge (1), absent at that worktree's pre-merge sha (0) — **both readings correct, about different files.** A run under a stale config would have measured none of those files and published an EMPTY zero list, with nothing in the output saying so. ⇒ **Verify the config in the tree you are about to RUN IN, immediately before the run. HEAD is not where the run happens.**

⚠️ **The general shape, which outlives these three:** a worktree is `git`-identical to the main tree and **environment-identical to nothing**. Anything gitignored, untracked, or exported into your shell is a property of *where you are standing*, not of *what you are measuring*. That is why two counts should be **reconciled** rather than adjudicated — 25 − 14 = 11 with every one named is stronger evidence than either count alone, and a mismatch that reconciles is not a disagreement.

⚠️ **Related, same family** — the collected-test-id diff. Some test ids bake an **absolute path** into a parametrize id, so diffing collected ids between two worktrees shows the same test as one removal plus one addition. A raw diff read `+225 / −4` and looked like the merges had deleted four tests; they had not. Compare **counts** as well as ids, and treat the agreement of the two as the check.

### 🔴 "IS ANOTHER SUITE RUNNING?" — MATCH `comm`, NEVER THE COMMAND LINE

Before taking the box for a tier, seats check whether anyone else is mid-run. **Measured 2026-08-29, both wrong answers on the same box within minutes:**

```bash
# ✅ CORRECT — asks what the process IS
ps -eo comm,args --no-headers | awk '$1=="pytest" || ($1 ~ /^python/ && $0 ~ / -m pytest/)' | wc -l
```

| pattern | reported | truth |
|---|---|---|
| `pgrep -f "\-m pytest"` | **0** | missed a live run — the script form `.venv/bin/python3 .venv/bin/pytest` has no `-m pytest` |
| `pgrep -af "pytest"` | **5** | four spurious |
| `comm`-based (above) | **1** | ✅ |

**The two failure modes are opposite, and the second is the dangerous one.**

1. **Too narrow → you take a box someone is using.** Matching only `-m pytest` misses `pytest` invoked as a script, which is how `run-*-tests.sh` launches it.
2. **Too broad → the gate never opens, on an idle box, silently.** `pgrep -f` searches the whole command line, and **a Claude seat's entire spawn briefing is its command line**. Three live seats — Tiberius, Rachel, Rio — matched `pytest` purely because their instructions *discussed* running tests. A briefing about testing is exactly the text most likely to contain the word, so this false positive gets **more** likely the more the fleet coordinates about the box.

⇒ `comm` answers *what this process is*; the command line answers *what someone wrote about it*. A gate must ask the first question. The same trap applies to any `pgrep -f` over a fleet of agent processes — grep for a tool name and you will find every seat that was told about the tool.

### 🔴 A COVERAGE LIST GOES STALE FROM A **MERGE**, NOT FROM A COMMIT

**Measured 2026-08-29** (row `9595aaef`). A manager spent an evening assigning coverage work off a zero-coverage census, then retracted an assignment when the worker showed the file already at 100% with 61 tests by his own commit hours earlier. **The retraction was the error.** Checked by merge-base: that commit — and three others like it — are **not ancestors of HEAD**. They live on the workers' own branches. At HEAD no test imports that module at all, so the file is still at 0% on the branch.

**Nobody was wrong. They measured different trees.**

| question | answer |
|---|---|
| "Is my work done?" | ask the **worktree** — the tests exist and pass there |
| "Is the branch covered?" | ask **HEAD** — and it is not, until the merge lands |

⇒ **Work in an unmerged worktree moves nobody's coverage but its author's.** A seat that re-measures "in my own tree" will contradict a HEAD-derived list every single time, and both parties will have correct numbers for different propositions. That is what every tree-versus-tree argument on this epic has actually been.

**Two obligations follow:**
1. **State the sha with the list.** A coverage list without the sha it was taken at is not a measurement, it is a rumour with a timestamp. Say `at ef6e2bdc`, not "as of tonight".

   ⚠️ **AND IT IS NOT ONLY COVERAGE LISTS — IT COVERS EVERY LINE-NUMBER CITATION YOU SEND A PEER.** Measured 2026-08-30: two seats quoted different `CLAUDE.md` line numbers for the same two sections and spent a round trip finding out why — one was reading numbers from his own branch, uncommitted, where the section had already moved. **A bare `file.py:482` is a pointer into whichever tree the reader happens to be standing in**, and on this fleet that is never reliably yours: peers work in worktrees, branches sit unmerged for hours, and one section can carry three different line numbers before dinner. Write `file.py:482 @ 8bf71a64` — the sha costs eight characters and turns a pointer into a fact. **Better still, cite the section heading or the symbol name: a heading survives an edit above it and a line number does not.**
2. **Report "done" and "landed" as separate columns.** A worker's file can be finished and still be at zero on the branch. Collapsing the two is what turns an honest commit into a phantom reassignment.

**And the durable fix is a command, not a list** — anyone can re-derive the current zero set at HEAD, and a list anyone can quote will outlive the tree it described:

```bash
# from your own worktree, checked out at the sha you mean to describe
COVERAGE_FILE=/tmp/cov-$USER-$$.data LUPIN_ROOT="$PWD" \
  .venv/bin/python -m pytest src/tests/unit/ -q --cov=src/scripts --cov-branch \
  --cov-report=term-missing --cov-fail-under=0
```

⚠️ **Run the WHOLE tier, not a scoped subset.** A subset manufactures false zeros for any file whose only coverage comes from a test you excluded — which is the exact defect a zero list exists to find.

⚠️ **AND NEVER SCOPE A RUN WHOSE OUTPUT YOU INTEND TO READ AS A LIST** — do not pass `--cov=<path>` when the config already defines `source`. Measured 2026-08-29: a census run carried `--cov=src/scripts` out of habit, which **silently overrode** the `source` list in `pyproject.toml` and produced a **61-file** frame instead of **73**. (⚠️ **"Seven" and "thirteen" both describe that list correctly and count different things** — Rachel 🕊️, 2026-08-30: **seven top-level roots**, of which `src/scripts` carries **six non-package subdirectories listed separately**, so the `source` array holds **thirteen entries**. Neither figure is stale; say which you mean. The durable check is neither number — `src/tests/unit/test_coverage_frame_completeness.py` asserts `unreachable_subdirs( … ) == []`, derived from the tree, so it stays true however the list grows.) The twelve subdirectory files were not reported as `0%` — they were **never instrumented at all**, and the report says nothing about a file it never traced. Re-reporting the same `.coverage` data through `--rcfile` cannot recover them either; the data simply is not there.

⇒ **A scoped override does not narrow the REPORT, it narrows what was ever MEASURED — and the difference is invisible in the output.** Both produce a clean table with a plausible total.

⚠️ **NARROWED 2026-08-30, measured by Maya — the ban is on the LIST, not on scoping.** Per-file counts are **scope-invariant**: the same file reads the same statement/branch numbers under two different `--cov` scopes (measured at 163/0 and 44/0 in both frames). So a scoped run is **safe** for *"what is this one file's coverage"* and unsafe **only** for *"which files are at zero"* — because a file's **absence from a scoped report means never-measured, not zero**. Drop the flag when you are producing a list and let the config's `source` govern; if you must scope, say in the same breath which files fell outside the frame, because "not listed" and "at zero" are different facts and only one of them is safe to act on.

## 100% COVERAGE MANDATE

**Lupin-wide hard gate.** Ratified 2026-05-06 (multiplexer-only), **scope-expanded Lupin-wide 2026-05-16** ("Everything has to pass at 100%. Full stop."). CoSA inherits it as of the 2026-05-29 mono-repo fold, on a grandfathering ramp — see the TODO.md top entry (deadline 2026-06-05).

**The rule**: **100% coverage — lines AND branches AND functions** on all Lupin code. Python via `pytest --cov` (`--cov-fail-under=100`); TypeScript via `c8 --100`.

- **Exceptions**: `# pragma: no cover` (Python) / `c8 ignore` (TS) ONLY for genuinely-unreachable defensive branches, and ONLY with a same-line comment giving the reason. "No time to test" is never valid — fix the test, not the gate.
- **In plan ACs**: write "100% lines/branches/functions" — never ≥90%/≥95%.
- **Excludes**: sub-repos `lupin-mobile`, `lupin-plugin-firefox`, and external-project bind-mounts.
- **Canonical record**: auto-memory `feedback_100pct_coverage_multiplexer.md` (directive + Lupin-wide expansion). Origin doc: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/08-phase6a-jobs-surface-design.md` AC6.

### 🔴 A SCOPED `--cov` ANSWERS ONE QUESTION AND CANNOT ANSWER THE OTHER

Measured 2026-08-29. A narrowed scope — `--cov=<module>`, `--source=src/scripts` — does **not**
narrow the REPORT, it narrows what is ever MEASURED. Nothing in the output says so, and that is the
whole hazard.

| Question | Scoped run |
|---|---|
| *"What is THIS file's coverage?"* | ✅ **safe, if the file is inside the scope.** Per-file counts are scope-INVARIANT — the scope decides which files appear, never the numbers for one that does |
| *"WHICH files are at zero?"* | 🔴 **cannot answer it.** Use the project config |

**Why the second one bites**: absence from a scoped report is **not evidence of zero coverage — it
is evidence of never having been measured.** A census run this way returned thirteen files as
UNKNOWN, and unknown read as zero. Same shape as the two-database trap in §TESTING VENUES: **an
empty answer to a narrowed question is indistinguishable from a confident negative.**

**The receipt for the safe half** (this is why the rule is "use the project config for a census",
not "never scope"): `swe_workload_runner.py` was measured under two different scopes the same night
— `--cov=swe_workload_runner` and `--source=src/scripts` — and both report **163 statements / 0
miss, 44 branches / 0 partial**. Identical, because the file was inside both scopes.

⇒ **Scope freely while working a single file. Never scope a run whose output you intend to read as
a LIST.**

#### 🔴 AND A THIRD WAY TO MEASURE **NOTHING** WHILE EXITING 0

Found by Krishna 🦚 2026-08-30 as *"a `.py` path silently measures zero"*; both halves of that
moved under measurement, and the corrected rule is more useful than the original.

**`--cov=<target>` needs BOTH conditions, and fails identically when either is missing: the target
must be spelled as an IMPORTABLE module or directory, AND actually IMPORTED by the tests in that
run.** (Conjunction stated by Krishna 🦚 after the first rewrite — tighter than the two-case table
below, which is kept because it shows which condition each failure breaks.)
Two ways to land there:

| `--cov=` | result | why |
|---|---|---|
| a **`.py` file path** | **always zero** | nothing is ever importable under that name — fails 100% of the time |
| a **dotted module** your tests never import | **zero** | the form is right, the run simply never touched it |
| a **dotted module** your tests do import | correct | |

**Measured at `c91bd1bb`, one test file** (`test_replay_carries_the_requesting_user_id.py`):
`--cov=src/cosa/memory/solution_snapshot.py` → zero, while `--cov=cosa.memory.solution_snapshot`
→ `328 stmts / 262 miss / 82 branch / 17%`. And `--cov=cosa.rest.routers.notifications` → **also
zero**, dotted and well-formed, because that test does not import notifications.
`src.`-prefixed → zero as well; `src` is already on the path here.

⇒ **"Use the dotted form" is NOT the fix, and stopping at the path-vs-dotted framing would have
shipped a rule that still returns zero.** The fix is to check that the run you are about to trust
actually exercises the target.

⚠️ **IT IS NOT SILENT — three warnings fire, and the FIRST one names the file.** Calling it silent
was this reviewer's error, from a `grep -v warning` in the probe that stripped the evidence:

```
CoverageWarning: Module <target> was never imported. (module-not-imported)
CoverageWarning: No data was collected. (no-data-collected)
WARNING: Failed to generate report: No data to report.
```

**The hazard is the EXIT CODE, not the absence of a signal.** Coverage says exactly what is wrong;
the run still exits **0**, so a gate checking `rc == 0` passes on a run that measured nothing, and
a human reading a tail sees a clean finish among deprecation warnings.

⇒ **Read the coverage TABLE, and grep the output for `module-not-imported` before trusting a
number.** This is the third mechanism on this page producing a confident-looking nothing, alongside
the narrowed census and the two-database trap. **And note how this entry got its own count wrong —
a probe that filters warnings cannot report on warnings.**
### 🔴 COVERAGE MEASURES WHETHER A LINE **RAN**, NEVER WHETHER THE TEST COULD HAVE **NOTICED IT
RUNNING WRONG**

Measured three times in three files on one evening, 2026-08-30 (row `9124b70a`, Pocholo 📣 and
Maya 🌻). **Two of those files were at 100% lines and branches with the defect live in them.** The
coverage number was TRUE. It told us nothing.

**The defect**, identical in all three: a paged fetch asked for a flat `limit=PAGE_SIZE` whatever
cap the caller passed, so `--max-rows 100` fetched 500 rows and then announced *"truncated at 100
rows"* — the one figure whose job is to say how partial a scan was.

**Why every suite stayed green.** The fakes were `lambda *a, **k` — they returned their scripted
page WHOLE, whatever was asked. So the line executed on every run, was asserted around, and was
**unfalsifiable**: a capped request and an uncapped one produced byte-identical data.

```python
# BLIND — answers the same however the code behaves. Nothing downstream can recover.
monkeypatch.setattr( mod, "_request", lambda *a, **k: _page( rows, has_more=True ) )

# DISCRIMINATING — honours the input, so a wrong request yields a different observation.
def _request( method, url, api_key, timeout, body=None ):
    calls.append( url )
    return _page( available[ :_limit_of( url ) ], has_more=True )
```

⇒ **A test asks two questions and coverage only ever answers the first**: did the line run, and
*could the fixture have produced a different observation if the code were wrong?* A fake that
ignores its input answers **no** to the second by construction, and **every assertion written over
its output inherits that no.** The assertions here were not weak — they were correct, well-named,
and blind. **An assertion audit passes a blind fixture clean every time**, which is why re-reading
the test body is the wrong move.

🔴 **THE TELL, AND IT IS MECHANICAL:** *replace the code under test with a constant. If the fixture
still yields the same data, the suite is measuring the fixture.*

⚠️ **AND THE DISCRIMINATING CASE USUALLY NEEDS TWO CONDITIONS AT ONCE, WHICH IS WHY ONE FIX IS NOT
ENOUGH.** Measured: a fake that honours `limit` is still blind at `--max-rows 2000`, because
`min( 500, 2000 )` is 500 either way; and a cap of 2 is still blind against a 2-row page, because
both versions return 2. You need **a cap BELOW the page size AND a page LARGER than the cap.** A
seat told only *"assert on a small max_rows"* writes a test that looks like it covers this and does
not.

⚠️ **A related shape, opposite polarity — a fixture can also make a test ENDORSE the defect rather
than merely miss it.** Of the two landed copies, one asserted a result that *only the broken code
produces*; the other was merely blind. **Blind and endorsing are different**: the first goes green
on a correct fix, the second goes RED on one and reads as the patch having broken something. Check
which you have before concluding a fix is wrong.

**This is the fourth reading in § A MUTATION HARNESS CAN LIE, reached from the other direction** —
there, a surviving mutant sends you looking for a fixture that cannot discriminate; here, there is
no mutant and no red at all, only a coverage figure at 100%. **Same defect, and the coverage number
is the more dangerous entry point, because it arrives looking like an answer.**

### 🔴 THERE IS A SECOND VIRTUALENV *INSIDE* `src/`, AND IT IS 92% OF EVERY DISK SWEEP

`src/cosa/.venv` is a full vendored virtualenv living inside the source tree. Measured 2026-08-30:

| population | count |
|---|---|
| `find src -name '*.py'` | **31,734** |
| of which `src/cosa/.venv` (3.11 vendor) | **29,303 — 92%** |
| `git ls-files 'src/**/*.py'` | **2,415** |

It is **untracked and ignore-matched**, which is exactly what decides who it fools:

- **git-derived** sweeps (`git ls-files`, `git grep`) never see it and are **correct as-is**.
- **disk-derived** sweeps (`find`, `rglob`, `compileall`, an unscoped `--cov`, a bare `grep -r`) see
  it and are **inflated ~13×** with third-party code for an interpreter this repo does not run.

**Receipt for why this is not theoretical**: the first cut of `migrate-pyc-to-checked-hash.sh`
targeted `src/` with `rglob`, spent 40+ seconds rewriting vendored 3.11 bytecode, and reported
"30,621 converted" — a five-figure number that read like a thorough migration and was 92% a fact
about somebody else's code. The honest figure was 1,318. Excluding the venv cut the run to 3.5s.

⇒ **Any tree-wide operation must exclude `.venv` / `node_modules` / `site-packages`, or be
git-derived.** This is the same lesson as the collision guard on row `c89cec9b` from the opposite
direction — there, disk-derived counting *added* a machine-local leftover; here it adds 29,303
vendored files. **Ask what population your command actually walks before you read its number.**

## TESTING

Three-tier strategy (unit → integration → E2E). Venue routing (`:7999` vs `:8000`) per §TESTING VENUES above; every suite is tagged with its venue. `:8000 (scheduled)` = submit via `POST /api/test-suite/submit`; **self-authorized on a verified-idle server** (place behind any already-scheduled/running job — see §TESTING VENUES).

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

**Coverage**: `pytest --cov=cosa --cov-report=html src/tests/` (Python). See §100% COVERAGE MANDATE for the hard gate.

**Editing a `.py` file inside a test?** Use `tests.helpers.pyc_freshness` (`mutate_source` fixture / `refresh_source`). CPython validates a `.pyc` on the source's **whole-second** mtime **plus size**, so a mutation edit changes neither and the interpreter keeps running the *old* code after you restore the file and read it back — measured twice on 2026-08-29, on `job_state.py` and on the helper's own module (row `d18ce9ef`). ⚠️ `PYTHONDONTWRITEBYTECODE` does **not** fix it; it only stops pycs being *written*. Debugging a red you cannot explain? Run **`src/scripts/purge-pycache.sh`** before concluding anything. 🔴 **NOT a raw `rm -rf __pycache__` — that now RE-OPENS the very hole it used to plug** (row `866f43ce`, §100% COVERAGE MANDATE below): the tree is on checked-hash invalidation, a pyc written where none exists is timestamp-based, so a bare purge silently reverts the tree with nothing in any output saying so. The script purges **and** reconverts, ~3.5s, so the two cannot be half-done. Detail: `src/tests/README.md` § EDITING A SOURCE FILE INSIDE A TEST, measurement `src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md`.

**Docs**: `src/tests/README.md` (overview), `src/tests/integration/README.md`, `src/docs/automated-interactive-testing.md` (proxy), `src/tests/smoke/README.md`, `src/tests/AUTH-TESTING-GUIDE.md` (credentials), presentation strategy `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.07-e2e-testing-strategy.md`.

## PR MERGE REQUIREMENTS

<!-- merge-pyramid-suites: unit cosa coverage typescript smoke websocket e2e integration -->
**All must pass before merging to main** (venues + commands per §TESTING above), run in this order: unit (:7999) → **cosa (:7999 — in-tree `src/cosa/tests/**`, `src/tests/run-cosa-tests.sh`; joined the pyramid 2026-08-13, row d83d025b)** → **coverage (:7999 — `src/tests/run-coverage-gate.sh`; joined the pyramid 2026-08-29, row e2099400). It does NOT re-run anything: the unit and cosa tiers above append to one isolated data file and this step renders it, checks pyproject's `fail_under`, and checks that the FRAME still measures every file it claims. Before it existed, NOTHING in the build asked for coverage — no addopts, no runner, no injection in `job.py` — so `fail_under` fired only when a human typed `--cov` by hand, and the 100% mandate had teeth on the TypeScript side only.** → **typescript (:8000 scheduled — `src/tests/run-typescript-tests.sh`, c8 at 100%, ~8-25 min so it fails the :7999 two-minute rubric; runs inside the capped `jstest.slice` cgroup — ban lifted 2026-08-25, row 92e94cb7)** → smoke (:7999) → **serial bridge guard (`src/scripts/run-serial-bridge-guard.sh` — read the note below before reading its verdict)** → WebSocket smoke (:7999) → E2E UI + visual regression (:8000 scheduled) → **integration (:8000 scheduled — FINAL GATE)**. Each requires 100% pass. Wait for E2E to complete before launching the integration gate; PID-file guards block concurrent runs.

The **cosa tier's count was being asserted without ever being run.** Now measured **three times across two different trees**:

```
@3a8ce109  8668 passed, 26 skipped  in 280.72s   EXIT=0   (Tiberius, 21:16)
@17e78c98  8668 passed, 26 skipped  in 274.45s   EXIT=0   (Rio)
@17e78c98  8668 passed, 26 skipped  in 274.53s   EXIT=0   (Rio)
@b3c76d55  8671 passed, 26 skipped  in 275.56s   EXIT=0   (Tiberius, tier-wide thread probe)
@b3c76d55  8671 passed, 26 skipped  in 276.67s   EXIT=0   (Rio, independent)
```

**FIVE runs, two seats, three shas — and the two different counts RECONCILE rather than conflict.** `git diff 17e78c98..b3c76d55 -- src/cosa/tests` is **+4 `def test_`, −1 removed = +3**, which is exactly `8668 → 8671`. Verified independently by both of us. A count that moves *and* whose movement is fully explained by the diff is stronger evidence than a count that merely repeats.

The figure in circulation was **8,622/0**, which is simply the count as of **08-22**. Nothing regressed — **zero failures** in both runs — and 7 commits touched `src/cosa/tests` in between, adding a net **+44** `def test_` (`402e528c` `f2be1f6d` `8cb320bb` `0dd919d2` `927076a4` `566cb971` `e38abe43`) against a measured +46; the remainder is parametrization. **Stale expectation, not regression**, proven both ways rather than inferred from the unit tier's similar drift.

**Three samples across two shas, by two seats**, so 8,668 is neither a one-tree artifact nor a one-runner one; wall time is tight too — 274.45 / 274.53 / 280.72s. ⚠️ **What these samples are NOT independent of: the HARNESS** — wider than box-and-interpreter (Rio's correction to my wording). All three share the same `.venv` package set, the same `conftest`, the same runner script, the same env (`LUPIN_UNIT_NETWORK=block`, `LUPIN_ROOT`, `PYTHONPATH`), and the same OS and clock; **Rio's two additionally shared the same uncommitted working tree**, so they are not even tree-independent of each other in the untracked sense. Any one of those could agree wrongly: a defect living in the harness rather than the tree reproduces identically across all three and reads as agreement. ⚠️ **It moved within the same evening** — **8,671**, three more than 8,668, with no failure anywhere. The cause is named rather than guessed: three commits landed cosa tests in that window (`6874aec8`, `b92f663c`, `402e528c`), and the commit carrying this note touches `CLAUDE.md` only. Re-derive rather than quote on sight; that habit is what let `8,622` stand since 08-22, and the number is demonstrably a moving target even across one night — but the number itself now rests on more than one run.

**The stdout-watcher hazard cannot reach this tier, and the durable reason is the ABSENT THREAD, not a count.** Nothing in the cosa tier imports `lupin_mcp.cosa_voice_mcp`, so the daemon watcher never starts in that process and there is no polluting writer at all. Measured, not grepped, and over the WHOLE tier rather than a subdirectory (Rio's correction — my first probe covered only `unit/rest/`, 2,673 tests, which cannot speak for a tier-wide claim): a thread probe at `pytest_sessionfinish` across all of `src/cosa/tests/` — **8,671 passed** — reports `WATCHER_PRESENT: False` — **and Rio's independent run at the same sha reports the same**, so the absence is not one seat's artifact. ⚠️ **The absence is SPECIFIC to the watcher, not a claim that the tier starts no threads**: the same probe reports `['GhostJobSweeper', 'GhostJobSweeper', 'MainThread', 'io-embed_0', 'io-embed_1']`. Cosa runs daemon threads; none of them is the one that writes session events to stdout. (Every textual `cosa_voice_mcp` hit in `src/cosa/` is a path string, a path-suffix assertion, or a comment — no import.) **Corroboration, NOT the proof**: Rio's census finds 379 stdout-capturing test functions across 89 files with **zero** parsing the capture as JSON. That number is a census of today's tree and one new test moves it (Rio's correction); the missing importer is what holds. The unit tier is the exposed one — 15 files parse stdout as JSON there; see `src/rnd/v0.2.0/2026.08.24-import-time-watcher-thread-poisons-stdout-tests.md`.

The **serial bridge guard** step is the tier-2 whole-directory contact check (row e2ae4102) that the concurrent unit run deselects (`-m "not serial_bridge_guard"`) because a live peer's bridge write would false-accuse it. If it reports contact, a hook may be resolving its directory from a hardcoded real path instead of the seam. Dropping this line silently removes the guard — the concurrent scoped canary does not see a merge into a live seat.

> 🔴 **DO NOT WAIT FOR A "QUIESCENT BOX" — THERE IS NO SUCH STATE** (row `5a68c92c`). This line used to say "on a quiescent box", and the row-level guidance said "run it when you are the only session writing bridges." **That condition cannot be satisfied and asking peers to pause will not create it.** Measured 2026-08-24 with no suite running anywhere: **13 entries under `~/.claude/sessions` changed in 60 seconds**, and four live seats wrote bridges inside ten minutes — **including the seat running the guard**, which writes its own bridge and its own listener files while the guard executes. The precondition named a state that never exists, so a red told the reader nothing and the sanctioned response ("re-run") was indistinguishable from weakening a gate.
>
> **How to read a red instead — real contact is DETERMINISTIC, peer noise is NOT:**
> 1. **Re-run and compare the NAMED file.** The same filename every run = contact. A different file each run, or none, = peer noise. ⚠️ **This cuts both ways: one GREEN is also one sample.** The discriminator is determinism, not the colour of the result — on a check whose failure mode is nondeterministic, a single pass is as weak as a single fail. Run it more than once before reporting either.
> 2. **Identify the writer.** Read the named file's `session_id` / `cc_pid` and check whether it belongs to a live seat that is not the test: `ls /proc/<cc_pid>` — if that seat is alive and is not you, it is noise, not contact.
>
> ⚠️ **Scope note, pending a decision (do NOT "fix" this by narrowing the glob).** `fingerprint_dir` globs `*` rather than `cc-*.json` **deliberately** — row `877794ed` widened it because the narrow form MISSED real `cc-listener-*.stderr` and `.spawn-lock` writes. The cost of that correct decision, measured: the guard sha256s **6,498 entries / 154 MB twice per test**, of which **5 are Lupin bridges**; the exclusion list carries **2 names against ~4,676 `.log`/`.stderr` files**. Narrowing the glob re-opens the hazard `877794ed` found, so the scoping question is Rick's, not a drive-by. Analysis: `src/rnd/v0.2.0/2026.08.24-serial-bridge-guard-unsatisfiable-precondition.md`.

Integration is the final gate because it exercises complete user workflows across API + DB + auth on a real server — catching regressions unit tests miss.

**On failure**: do NOT merge. Fix the failing tests first, then re-run the full suite. A genuinely-flaky-not-your-code failure gets documented + a separate fix — never a merge bypass.

**Testing anti-patterns** (NEVER):
- `curl` for pipeline/integration testing, or manual `/api/push` + poll `/api/get-queue/done` — use the automated scripts (`LivePipelineTestBase`), never bespoke curl.
- Running :8000-bucket suites (integration, E2E UI, proxy-integration, presentation regression) against :7999 — they depend on server monopoly; the dev server is not a stand-in.
- Side-door injecting :8000 tests via curl / direct `/api/push` / in-process instantiation / anything but `POST /api/test-suite/submit` — collides with in-flight runs and poisons both. (Submission itself is self-authorized on a verified-idle server; the prohibition is on the side-door, not on submitting.)
- Curl is acceptable ONLY for: API-reference docs, deployment health checks, one-off debugging (never committed).
- New agent? Add an automated smoke test (see `.claude/skills/agentic-voice-workflow/SKILL.md`).

### 🔴 A MUTATION HARNESS CAN LIE IN BOTH DIRECTIONS — READ A SURVIVOR THREE WAYS

Measured 2026-08-29 on the coverage ramp (rows `ba6df71e`, `3b78bc8a`). Two instrument defects in
one evening, both the same failure: **the harness reporting on an execution that never happened.**

**OVER-REPORT — a non-zero exit is not a red test.** pytest's rc 4/5 mean it could not RUN the node
(usage error / nothing collected). A harness counting any non-zero rc as a kill scores its own
misses as hits. Receipt: an rc=4 was recorded as a caught mutation; the test had been appended into
the wrong class and never ran. ⇒ **Accept only `rc == 1`.**

🔴 **AND `rc == 1` ITSELF FAILS ON A BRANCH THAT CARRIES A DELIBERATE RED — measured
2026-08-30.** The rule above assumes a GREEN baseline. `src/tests/unit/test_secret_scan.py`
holds two intentional reds (the rotation hold), so **the suite exits 1 before a single
mutation is applied**: under `rc == 1` every mutant scores as KILLED and the pass reports a
perfect result while measuring nothing at all. A 14-arm pass run that way would have read
14/14; judged properly it was **9/14**.

⇒ **The kill signal is the FAILING SET, not the exit code: killed iff a NAMED test that was
PASSING at baseline now fails.** `rc` 4/5 still means could-not-run and is never a kill.
This is not a departure from the rule — the exit code was only ever a *proxy* for "a test
that passed now fails", and the proxy breaks the moment anything is red on purpose.

⇒ **TAKE THE BASELINE FIRST, ALWAYS, AND RECORD THE NAMES.** It costs one run, it is the
only way to tell a mutant's red from a red that was already there, and a harness that
skips it cannot distinguish a perfect score from a broken instrument. Two of tonight's
five survivors were **deliberate design decisions with their reasons in the file** —
readable only because the baseline said which reds were expected.

**STALE BYTECODE — a mutant can run as some OTHER revision of itself, and this one lies BOTH ways.**
CPython validates a cached `.pyc` on the source's whole-second mtime and size. A mutation changing
NEITHER — single-character and digit swaps, `return 3` → `return 0`, `<` → `>` — landing in the same
second as the cached compile is judged unchanged, so the cached bytecode runs instead.

- **False SURVIVOR**: the ORIGINAL bytecode runs, the test passes because the original is correct,
  and the mutation reports SURVIVED. Receipt: the same mutated sha `ab030e258b72` gave rc=0 through
  a harness and rc=1 run by hand seconds later, the only variable being bytecode caching.
- **False KILL**: in a SEQUENTIAL harness over one file, run N+1 can load run N's bytecode. The
  suite then fails on the PREVIOUS mutant and the harness records a kill the CURRENT mutant never
  earned. Mechanism and retraction on row `cfe0b15d` — the narrower "only fakes survivors, so an
  all-killed pass is safe" was believed briefly and is WRONG for the loop shape every ramp harness
  uses. ⇒ **Purge on EVERY pass, not only one that reports a survivor.** An all-green pass is
  exactly the one that looks like it needs no checking.

🔴 **`python -B` / `PYTHONDONTWRITEBYTECODE=1` DOES NOT FIX THIS.** It suppresses *writing* a
`.pyc`, never *trusting* one — and any repo that has ever run its tests already has the cache on
disk. **The structural remedy is checked-hash invalidation** (`py_compile.PycInvalidationMode.CHECKED_HASH`
/ `compileall --invalidation-mode checked-hash`), which hashes the source instead of comparing
whole-second mtime and size, and is therefore immune to a same-size same-second edit by
construction.

🔨 **RICK RULED YES — 2026-08-30, decision `866f43ce`. Checked-hash goes repo-wide.** Convert your
tree with `src/scripts/migrate-pyc-to-checked-hash.sh`; `--verify` reports without changing anything.

🔴 **"EXITS NON-ZERO" WAS WRONG — READ THE CODE, THERE ARE THREE** (Rachel 🕊️ and Tiberius 👑,
2026-08-30). This line used to say `--verify` "exits non-zero if any pyc is still timestamp-based",
which welds a real answer to a failure-to-answer:

| exit | meaning |
|---|---|
| **0** | every pyc this interpreter reads is checked-hash |
| **1** | ⚠️ **the real finding** — timestamp pycs are present |
| **2** | **it never ran** — **three** conditions share this code: unknown option · root is not a directory · no interpreter at `$PYTHON`. Each prints a distinct message to **stderr**, so the message is the only discriminator — capture stderr, or you cannot tell them apart |

**Exit 2 is common, not exotic**: `PYTHON` defaults to `$LUPIN_ROOT/.venv/bin/python`, and **roughly
two in five worktrees have no `.venv`** — so a reader treating any non-zero as "vulnerable tree"
mis-reads a script that never started. **Re-derive the ratio rather than quoting one; see below.**

```bash
# in a worktree without its own .venv — name the interpreter
PYTHON=/path/to/a/real/python src/scripts/migrate-pyc-to-checked-hash.sh --verify
```

⚠️ **And a `1` from that form is the CORRECT answer, not a failure** — it means the tree genuinely
holds timestamp pycs, which is the question you asked.

⇒ **Same defect as `purge-pycache.sh`'s exit 2** (Krishna 🦚, same evening, other script): *two
failure modes sharing one exit code, wanting opposite remedies* — fix your command line versus build
a venv. Where a script can distinguish them, **distinct exit codes beat distinct messages**: a code
is a contract, a message drifts.

🔴 **THE `-f` IS THE WHOLE MIGRATION, AND WITHOUT IT THE COMMAND CONVERTS NOTHING WHILE REPORTING
SUCCESS.** Measured 2026-08-30 — do not retype the command from memory without it:

```
python -m compileall    --invalidation-mode checked-hash .   ->  pyc stays TIMESTAMP
python -m compileall -f --invalidation-mode checked-hash .   ->  pyc becomes checked-hash
```

compileall treats an existing up-to-date `.pyc` as needing no work. **Any tree that has ever run its
tests is already full of timestamp pycs**, so the un-forced command leaves every one of them exactly
as it found it — the setting "changed" and the tree is still vulnerable. The script passes `-f`.

⚠️ **NOT CONVERT-ONCE-AND-FORGET, and the two halves pull opposite ways** (both measured):
an **existing** checked-hash pyc **stays** checked-hash — edit the source, re-import, and CPython
regenerates it in the same mode, so no build step is needed on every run. But **a pyc written when
no prior pyc exists is TIMESTAMP-based**, because there is nothing to inherit a mode from.

🔴 **WHICH MEANS THE OLD PURGE HABIT NOW RE-OPENS THE HOLE IT USED TO PLUG.** A raw
`find src -name __pycache__ -exec rm -rf {} +` deletes the checked-hash caches, and the next import
silently rebuilds them as **timestamp**. The tree is then back to the original defect with nothing in
any output saying so. This is the most likely way a converted tree regresses — the instruction people
already have in their fingers is now the thing that breaks it.

⇒ **THE FIX IS A SCRIPT, NOT A RULE: use `src/scripts/purge-pycache.sh`.** It purges *and*
reconverts in one command (~3.5s), so the halves cannot come apart. "Remember to reconvert after
purging" would be a habit, and this fleet's own doctrine is that a habit is not a control — the raw
command has been replaced everywhere it was documented (CLAUDE.md, `src/tests/README.md`, the three
`pyc_freshness` failure messages, and the mobile-parity test's remedy line) so the thing people copy
is safe by construction. Measured, both ways: after a raw purge plus one import the verifier reports
`timestamp=3`; after the script it reports every pyc checked-hash.

### 🔴 THE CHECKED-HASH VERIFIER SCANS `$LUPIN_ROOT/src`, NOT WHERE YOU ARE STANDING

Found by Tiberius 👑 while reviewing a peer's mutation pass, 2026-08-30; cleared by Rachel 🕊️.
`migrate-pyc-to-checked-hash.sh` takes its target from **`$LUPIN_ROOT/src`** (`TARGETS=(
"$LUPIN_ROOT/src" )`), never `$PWD`. Run it from a worktree with `LUPIN_ROOT` still naming the main
repo — **the default, since the variable is inherited from your shell** — and it blesses the MAIN
REPO, then prints its checkmark about a tree you are not testing:

```
$ cd <a worktree> && ./src/scripts/migrate-pyc-to-checked-hash.sh --verify
  scanned roots:
      /mnt/DATA01/include/www.deepily.ai/projects/lupin/src      <-- THE MAIN REPO
  every pyc THIS interpreter reads is checked-hash
```

A "checked-hash verified in the worktree" certification was made against the wrong tree this way.

⚠️ **AND `LUPIN_ROOT="$PWD"` ALONE DOES NOT RELIABLY FIX IT — WHAT YOU GET DEPENDS ON THE WORKTREE**
(Rachel 🕊️ caught this contradiction; measured both ways at `3019fed9`):

| worktree | `LUPIN_ROOT="$PWD"` alone |
|---|---|
| **has** its own `.venv` | **exit 1** — the real answer: this tree has timestamp pycs |
| **no** `.venv` (29 of 75) | **exit 2** — `ERROR: no interpreter at …/.venv/bin/python`; nothing was checked |

An earlier cut of this section claimed a flat "exits 1", which **contradicted its own next paragraph**
— the one explaining that `PYTHON` is derived from `LUPIN_ROOT`, so pinning only the root repoints
the interpreter at a venv the worktree does not have. ⇒ **Pin both, as below.**

⇒ **This is worse than an unconverted tree, because it is an unconverted tree wearing a checkmark.**
The script's own output names its scanned roots — **read that line, not the verdict.**

**To diagnose a tree you have already used, pin BOTH the root and the interpreter.** `LUPIN_ROOT`
alone is not enough: `PYTHON` is *derived* from it, so pinning only the root repoints the interpreter
at a venv the worktree does not have.

```bash
LUPIN_ROOT="$PWD" \
PYTHON="$( dirname "$( git rev-parse --path-format=absolute --git-common-dir )" )/.venv/bin/python" \
  ./src/scripts/migrate-pyc-to-checked-hash.sh --verify
```

`git-common-dir` resolves to the MAIN checkout from inside any worktree, so this needs no hardcoded
path and works from every tree.

🔴 **DO NOT QUOTE THE VENV-LESS COUNT — RE-DERIVE IT.** Three figures appeared in one evening
(29/74, 29/75, 30/76) and **all three were correct when taken**; the population changes as seats come
and go, so a quoted ratio is a rumour with a timestamp. Same rule as *a coordinate is not a
reference* — **ship the command, not the number**:

```bash
git worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r w; do
    [ -x "$w/.venv/bin/python" ] || echo "$w"
done | wc -l
```

Snapshot for scale only, **not to be quoted**: **30 of 76** at 2026-08-30 22:44 EDT, excluding the
six `.claude/worktrees/tfe-*` harness trees (82 and 36 including them — say which you mean). The
ratio has stayed near two in five across every measurement, which is why the `PYTHON` pin is not
optional.

⚠️ **Exit 2 at least fails LOUDLY** — it never prints a verdict, so unlike the unpinned run it cannot
certify the wrong tree. The three-way exit-code table is above.

🔴 **AND `purge-pycache.sh` ACCEPTS NO `--verify` — IT IS A DESTRUCTIVE COMMAND WEARING A READ-ONLY
NAME.** It tests only `$1 == "--dry-run"`; anything else is silently ignored and it **purges**. It
also runs under `set -uo pipefail` **without `-e`** and never checks its `rm`, so it can print
`Permission denied` and still **exit 0** — a caller reading `$?` sees success. **The read-only
verifier is `migrate-pyc-to-checked-hash.sh --verify`.** (Fix in review, row `3ac368b4`.)

⚠️ **Never run a mutation harness inside a peer's LIVE worktree** — it writes to their source. Check
the sha out into a detached worktree of your own. Learned in this same review: the peer lost nothing,
but the restore control read a dirty tree.


⇒ Three ways a tree drifts back, all one mechanism: a **new** `.py` file, a **purged**
`__pycache__`, or a module **imported for the first time** since the last conversion. Measured live
2026-08-30 — a verify run minutes after a clean conversion found exactly one offender,
`src/cosa/utils/coverage_contention.py`, which had reached this working tree on a peer's commit and
was imported before the next conversion. The gap is not theoretical; it fired inside the hour.

⇒ **Re-run the script after adding Python files or purging a cache; `--verify` when you want to know
rather than assume.** It exits non-zero if this interpreter would read a timestamp pyc.

🔴 **REVERSED 2026-08-30 — ISOLATE EVERY ARM. A CONVERTED TREE DOES NOT PROTECT A MUTATION LOOP.**
This paragraph used to read *"the per-harness purge is now the FALLBACK, not the instruction"*, on
the reasoning that a checked-hash tree can be trusted. **Four seats disproved it independently in
one evening**, on two different branches, and the reasoning was wrong for a mechanism this page
already documents two paragraphs above.

**CONFIRMED AT THE BYTE LEVEL** (Tiberius 👑). In a fresh worktree the pyc header reads **`flags=0`,
timestamp-based** — a worktree starts with no `__pycache__`, and a pyc written where none existed
has no mode to inherit. Timestamp validation compares whole-second mtime **and size**; swapping two
names inside an f-string changes neither — **6,533 bytes before and after** — so the interpreter
serves the PREVIOUS arm's bytecode against the RESTORED source.

| seat | receipt |
|---|---|
| Tiberius 👑 | byte-identical source: **7 failed** with the stale pyc, **18 passed** after removing one file. One arm read **KILLED** without a per-arm purge and **SURVIVED** with it — and he **retracted an approval** over it |
| Rachel 🕊️ | a test failed **deterministically four times** — under coverage, without it, in isolation — then passed permanently after a purge, **unreproducible** |
| Rio ⚡ | `purge-pycache.sh`'s reconvert needs `$LUPIN_ROOT/.venv/bin/python`; **35 of the repo's 80 worktrees lack it**, so there a purge leaves the tree on timestamp invalidation |
| Krishna 🦚 | corrected the first cut of this rule: **a harness that rebuilds its sandbox per arm is already isolated** and needs no purge |

🔴 **CORRECTED 2026-08-30, THE SAME EVENING IT WAS WRITTEN. "ONE PYTEST RUN UNDOES THE CONVERSION"
IS FALSE — THE REAL HAZARD IS A TREE THAT WAS NEVER CONVERTED.** Four seats measured this from four
directions and the reconciliation is the useful part: **a conversion STICKS; what does not exist
cannot stick.**

**Maya 🌻 disproved the original claim** with a probe module and a two-directional negative control —
a real source module, imported by a real pytest run, then mutated same-size with mtime restored so
neither size nor whole-second mtime moves:

| | |
|---|---|
| source pyc after convert | checked-hash |
| source pyc **after an ordinary pytest run** | **checked-hash — UNCHANGED** |
| convert → pytest → mutate → fresh import | **returns the mutated value — protection HOLDS** |
| negative control on a timestamp pyc | serves **stale** bytecode — so the probe *can* see the failure |

**Pytest's rewriting is a DISJOINT set**, which is what made two honest counts look contradictory:
it writes `…cpython-313-pytest-8.4.2.pyc`, which never replaces `…cpython-313.pyc` and is not read on
a normal import. One seat counted the population that matters for mutation and found it unchanged;
another counted a set that starts empty and grows. **Both were right.**

**And yet Clayton 😎 and Tiberius 👑 really did see a fresh worktree go `--verify` 0 → 1 after one
ordinary run**, with `src/scripts/__pycache__/bounce_dev_warn.cpython-313.pyc` heading the offender
list. Not a contradiction — **their trees had never been converted.** Measured across three real
trees the same night, `src/` only, `cpython-313` normal-import pycs, vendored trees excluded:

| tree | checked-hash | TIMESTAMP |
|---|---|---|
| **main checkout** (converted with `-f`) | **2452** | **0** |
| a converted worktree | 2434 | 1 |
| **an unconverted worktree** | **0** | **724** |

⇒ **THERE ARE THREE STATES, NOT TWO** (Pocholo 📣 — a two-state headline hides the middle one,
which is where people are actually standing):

| tree | `--verify` | what it MEANS |
|---|---|---|
| **fresh, never used** | **0** | 🔴 **VACUOUS — nothing there to judge.** Not a conversion |
| **fresh, then one ordinary run** | **1** | timestamp pycs, written where none existed — no mode to inherit |
| **converted AND populated** | **0** | ✅ genuine — an ordinary run does **not** undo it |

**The first and third both print `0` and mean opposite things.** That is why *"I verified, then
mutated"* protected nobody: the reader saw state 1, believed state 3, and mutated in state 2.

⚠️ **A live residual survives in state 3** (Clayton 😎): a module **imported for the first time since
the last conversion** arrives timestamp-based even in a converted tree, because it too has no prior
pyc to inherit from. Conversion is not a permanent property of a tree; it is a property of the pycs
that existed when you ran it.

⇒ **CONVERT A NEW WORKTREE BEFORE YOU TRUST IT.** Use it once, then purge-and-reconvert, *then*
verify. A verify on an unused tree is not evidence.

🔴🔴 **BUT PIN `LUPIN_ROOT` FIRST — `purge-pycache.sh` MUTATES THE MAIN REPO FROM INSIDE A WORKTREE.**
**Found and documented by Pocholo 📣 at ~17:52 EDT** (`TODO.md` § *purges the wrong tree … and prints
its success banner anyway*); independently re-derived by Rachel 🕊️ five hours later, who then
**declined the credit and pointed at his entry**. `purge-pycache.sh:32` reads
`LUPIN_ROOT="${LUPIN_ROOT:-<derived from BASH_SOURCE>}"` — the fallback is right, but **a set variable
wins**, and every seat's shell has `LUPIN_ROOT` pointing at the MAIN checkout. Line 40 then does
`find "$LUPIN_ROOT/src"`, and the reconvert it chains to inherits the same resolution.

⇒ Run it from a worktree and it purges and reconverts `/…/lupin`, **prints its success banner**, and
leaves your worktree exactly as poisoned as it found it.

⚠️ **THE SUCCESS BANNER IS THE WHOLE PROBLEM** — this is the wrong-tree family's signature: not a
crash, a **confident verdict about a tree you were not asking about.**

🔴 **PIN BOTH VARIABLES, OR THE STOPGAP ITSELF LEAVES A HALF-DONE TREE.** An earlier cut of this
paragraph gave only `LUPIN_ROOT="$PWD"`. **Measured — that command purges and then fails to
reconvert** in a worktree with no `.venv` (30 of 76), because `PYTHON` derives from `LUPIN_ROOT` and
the worktree has no interpreter at that path:

```
Purging 1 __pycache__ directories under src/ …
Reconverting to checked-hash — WITHOUT THIS STEP THE PURGE SILENTLY REVERTS THE TREE …
ERROR: no interpreter at …/headwt/.venv/bin/python
EXIT=2
```

The caches are **gone and unreconverted** — precisely the half-done state the script exists to
prevent, reached by following the documented remedy. Found by Rachel 🕊️.

```bash
# from a worktree — pin BOTH. Verified exit 0 with the caches reconverted.
LUPIN_ROOT="$PWD" \
PYTHON="$( dirname "$( git rev-parse --path-format=absolute --git-common-dir )" )/.venv/bin/python" \
  src/scripts/purge-pycache.sh
```

⚠️ **`LUPIN_ROOT` and `PYTHON` answer different questions** — *which tree do I clean* versus *what do
I run `compileall` with*. Pinning only the first repoints the second at a venv that does not exist.
⇒ **A fix is in review** (rows `f26f7308` / `3ac368b4`) that derives the tree from `BASH_SOURCE`
unconditionally; **when it lands, the `LUPIN_ROOT` half of this becomes a no-op** and this paragraph
must be re-cut rather than left standing.

⇒ **Two harms, and the second is the quiet one.** It reaches into a shared tree other seats are
working in; and it leaves you **believing you isolated a mutation arm that you did not**. A seat
reported exactly that tonight — repeated per-arm purges from inside worktrees, every one of them
landing on the main repo.

⇒ **The wrong-tree family now has three members** (verifier, purge script, and the tier itself, see
§ TESTING VENUES). Anything that resolves `$LUPIN_ROOT` is asking about *your shell*, not *your
location*.

**The proper fix is Pocholo's and it is one sentence**: these scripts should derive their root from
`BASH_SOURCE` **unconditionally**, because *a script shipped INSIDE the tree it cleans can only be
disagreed with by the environment, never informed by it.* Row `3ac368b4`.

🔴 **AND NOTE HOW LONG IT SAT.** It was written down, correctly and in detail, at 17:52 — and the
whole crew walked into it anyway for five hours, including a reviewer whose per-arm isolations all
went to the wrong tree. **A defect recorded in `TODO.md` is not a control**; only the code is. That
is the same conclusion three separate rows reached tonight from three directions.

⇒ **A clean verify in the MAIN repo says nothing about your worktree** — the verifier scans
`$LUPIN_ROOT/src`, not where you stand. See the wrong-tree section below.

⚠️ **STILL EXPOSED, unchanged**: editing a **TEST** file inside a test. Use
`tests.helpers.pyc_freshness` there.

⚠️ **Do not count `.pyc` files to check this** — Tiberius tried and corrected himself: the count
moves for ordinary reasons and tells you nothing about invalidation mode. **The verify status flip
is the measurement**; the file count is not.

⇒ **Isolate every arm.** The requirement is that **nothing carries between arms** — not that you run
a particular command:

| form | strength |
|---|---|
| **rebuild the sandbox per arm** — tree, scripts and caches together | ✅ strongest: nothing survives *by construction*, so there is no cache to forget |
| `src/scripts/purge-pycache.sh` between arms | good, and the practical choice in a working tree |
| a raw `find … __pycache__ -delete` between arms | 🔴 **RE-OPENS THE DEFECT** — see below |

🔴 **A RAW PURGE INSIDE A MUTATION HARNESS MANUFACTURES THE BUG IT IS THERE TO PREVENT** — measured
by Pocholo 📣, 2026-08-30, as a **false survivor**. His harness isolated arms with
`find … __pycache__ -delete`, which deletes the *checked-hash* caches; the next import rebuilds them
**timestamp-based**, because a pyc written where none exists has no mode to inherit. **The isolation
step put the tree back into exactly the state the isolation existed to prevent**, and nothing in the
output said so. ⇒ **Use the script — it purges AND reconverts, so the halves cannot come apart.**

⚠️ **Do not read this as requiring a purge you do not need.** Krishna's arms rebuild from scratch
each time and are already isolated; demanding a purge there would be cargo cult.

🔴 **AND IT IS A REVIEWER'S OBLIGATION, NOT ONLY AN AUTHOR'S** (Rachel 🕊️). An author can isolate
every arm perfectly and a reviewer re-running the suite in a shared tree still gets served stale
bytecode — which is exactly how both of tonight's sightings reached a reviewer rather than an
author. ⇒ **Before you approve on a green you watched turn, or red you cannot explain, isolate and
re-run.** A deterministic failure that vanishes after a purge is not flaky and is not fixed; it is
the instrument, and saying so is a finding rather than a shrug.

⇒ **`--verify` before a pass is necessary and NOT sufficient** — it describes the tree you started
with, not the one you are measuring in.
⇒ **`-B` / `PYTHONDONTWRITEBYTECODE` still buys the appearance of safety, not safety** — it
suppresses *writing*, never *trusting*, and a repo that has run its tests already has the cache.
⇒ ⚠️ **Rio's finding makes the purge remedy conditional**: in a worktree with no `.venv` the purge
half succeeds and the reconvert half does not. **Check the purge's exit code** rather than assuming
it did both.

**What the retraction cost and what it bought.** Two mutation passes reported earlier that evening —
a 7-for-7 and a 10-for-10 — became **UNREADABLE, which is not the same as WRONG** (Tiberius's
distinction, and it is the one to defend): a number taken in a tree whose bytecode can serve the
previous arm establishes nothing **in either direction**. It is not evidence the tests are weak, and
it is not evidence they are strong.

⇒ **Re-run such a pass WITH EVERY ARM ISOLATED — never simply re-run it.** The failure was not bad
luck that a second attempt averages out; re-running in the same tree reproduces the same instrument.
**That is why the remedy is isolation and not repetition**, and it is the whole reason this rule
names a property rather than a command.

See row `d18ce9ef` and Pocholo's write-up
`src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md` for the six priced remedies.
⚠️ **That write-up's "+3.3% import cost" is an ANALYTIC figure and did not survive measurement on the
real tier** — see `866f43ce` for the observed numbers. Quote the row, not the 3.3%.

⚠️ **THE HAZARD IS NOT LIMITED TO MUTATION HARNESSES, AND IT IS CROSS-PROCESS.** A *fresh* pytest
reads the stale pyc off disk, so any edit-then-run loop is exposed — including one an agent types by
hand. Mutation testing is merely where it lands hardest, because mutate-and-restore are both
same-size edits inside one second and **the failure points the wrong way**: you restore the file,
read it back to confirm, and the interpreter keeps running the mutant.

**Provenance, because three seats measured this independently and the numbers must be comparable**:
found by Pocholo 📣 while mutation-proving AC-G4, filed and reproduced by Tiffany 💍 on row
`d18ce9ef`, and reproduced a third time from the ramp (rows above). ⚠️ **The two published
reproductions run OPPOSITE POLARITY** — one edits `"todo"` → `"dead"`, the other `"dead"` → `"todo"`
— so the "wrong" answer is a different word in each. They agree completely: in both, the flag serves
the pre-edit value. Do not read the mirrored tables as a conflict.

⚠️ **THE BYTECODE FAILURE IS SELECTIVE, WHICH IS WHAT MAKES IT DANGEROUS.** A length-changing swap
invalidates the cache on its own, so most mutations in a pass are unaffected — 11 of 12 in the
measured case. **A harness looks healthy while lying about exactly the mutations that leave mtime
and size unchanged.** Re-verification is cheap and worth doing on any pass that predates this rule:
re-running an unpurged 10/10 with the purge in place reproduced 10/10 with identical mutated shas,
so that pass held — but it was not KNOWN to hold until it was re-run.

⇒ **A SURVIVING MUTANT HAS THREE EXPLANATIONS, NOT ONE.** Separate them before writing a line of
test code:

| Explanation | How to tell | Cost of getting it wrong |
|---|---|---|
| **A weak test** | the other two are ruled out | the only one that earns a new test |
| **A broken harness** | re-run that ONE mutant by hand — if it reddens, the harness lied | you accept a lower kill count as the file's ceiling |
| **An equivalent mutant** | read the edit: did it repair its own damage? | you write a test to kill something that was never a defect |
| **A fixture that cannot discriminate** | read the DATA, not the assertions | you audit correct assertions, find nothing, and conclude the code is fine |

Measured example of the third: an edit that dropped an `if row.get( "id" )` guard **and** swapped
`row[ "id" ]` for `row.get( "id" )` in the same change turned a `KeyError` into a harmless `None`
key. The mutation was wrong, not the test. **Reaching for "weak test" first is how a seat rewrites
tests that were already fine.**

🔴 **THE FOURTH IS THE ONE YOU CANNOT REACH BY READING THE TEST** (Krishna, row `9ad838d6`). The
assertions can be present, correct, and named for exactly the thing that broke, while the FIXTURE
cannot tell the difference: **values that are interchangeable in the data cannot reveal a swap
between them.** Measured — `migrated=1` and `skipped=1` made a counter swap invisible, because
swapping two equal numbers changes nothing; `2 / 1 / 1` kills it. The generalisation is worth more
than the case: **if two quantities can be exchanged without changing the expected output, the test
asserts their SUM, not their identity — whatever its name says.** The remedy is the fixture, never
the assertions, and an assertion audit passes it clean every time.

**TWO MORE WORKED EXAMPLES from the same evening**, both found by mutations surviving a suite whose
assertions read correctly, and both fixed in the FIXTURE rather than the assertions. They are
written out in full because the abstraction above is the part a reader skips; the shape is what
gets recognised.

**(a) The fixture agrees with the environment.** Testing that an empty `LUPIN_ROOT` falls through
to the file-relative fallback rather than becoming `Path( "" )`:

```python
# SURVIVED a mutation that returned Path( "" ) instead of the real root
assert ( root / "src" / "scripts" / "watch-hook-events.py" ).exists()

# KILLS it — Path( "" ) is RELATIVE, and only resolves right from the repo root
assert root.is_absolute()
assert root == Path( whe.__file__ ).resolve().parents[ 2 ]
```

`Path( "" ) / "src" / …` is a relative path, and pytest runs from the repo root, so **the wrong
answer and the right answer named the same file.** The assertion was measuring the CWD.

**(b) The fixture already sits at the boundary it is testing.** Testing that a one-digit seconds
field is zero-padded:

```python
# SURVIVED a mutation removing .zfill( 2 ) — "abc" has no digits, so ss is already "00",
# two characters, and the padding is a no-op either way
assert whe._hhmmss( "2026.06.06 @ 01:45 abc" ) == "01:45:00"

# KILLS it — only a ONE-digit value separates 01:45:07 from 01:45:7
assert whe._hhmmss( "2026.06.06 @ 01:45 7ms" ) == "01:45:07"
```

Both tests were named for the thing that broke. Neither could see it.

⇒ **When a mutant survives, look at the DATA before the assertions.** Three of the four readings
are invisible to a careful re-read of the test body.

**Still the floor, unchanged**: every mutation asserts it APPLIED before its result is trusted — the
anchor matched EXACTLY once, and the on-disk sha CHANGED — plus a restore control at the end that is
actually READ, since `git checkout` cannot restore an untracked file (row `c0a829a3`).

### 🔴 "I REPAIRED A FIXTURE" IS NOT "I PROVED THE REPAIR DISCRIMINATES" — TWO ARMS, ONE SHA

Ratified fleet-wide by Mr. Radio 🦉, 2026-08-30, after three seats produced it independently in
one evening. **A repaired fixture whose suite goes green has established NOTHING** — the suite was
green before, for a different reason. What establishes the repair is **two arms driven from ONE
mutated sha**:

| arm | required result | what it proves |
|---|---|---|
| the **OLD** fixture + the mutation | **SURVIVES** | the test genuinely could not see the behaviour it was named for |
| the **NEW** fixture + the *same* mutation | **KILLED**, by the named test | the repair is what closed it |

**One sha across both arms**, so the only variable is the fixture. **Neither arm alone counts**: a
lone red proves only that a test can fail, and a lone green proves nothing at all.

**Three clean instances, same evening**: Krishna 🦚 `88631dc1` (sha `7c8faf911d84`, SURVIVED before
the fixture reorder, KILLED after) · Chloé 🗼 `e23ef98c` (sha `914b6d4c0411`, 20 passed both ways on
the old fixture, killed by `test_a_vendored_path_under_src_is_still_rejected` on the new) · the
password-length repair on `migrate_mock_users.py` (sha `f83f1b901ade`).

### 🔴 AND `rc == 1` IS A KILL **ONLY ON A SUITE THAT IS GREEN AT BASELINE**

The rule above this one says to accept only `rc == 1`. **That is necessary and not sufficient**, and
the gap produced a false kill the same evening. A mutation returned `rc=1`, reddening
`test_the_flash_lite_arm_really_reaches_vertex` and `test_a_crossed_pair_is_refused` — it was nearly
recorded as KILLED. Run **unmutated**, the same two failed: they are two of the ten known worktree
artifacts from the gitignored `cloud-run.env`. **The failing SETS were byte-identical with and
without the mutation. It had SURVIVED, and the exit code said the opposite.**

⇒ **Assert the baseline is green BEFORE the mutation.** Comparing the failing SETS is the
FALLBACK for when you cannot get a green baseline, not an equal alternative to one — see the
next subsection for why a set comparison alone is not enough. 🔴 **A RESTORE CONTROL AT THE END IS NOT A BASELINE** (Rio ⚡, 2026-08-30, correcting
the first cut of this section). The floor rule above asks for a trailing unmutated run, and it is
easy to read that as discharging this one — it does not. A control that proves greenness only
*afterwards* cannot separate a false kill from a real one *during* the pass: every verdict was
already recorded by the time it runs. The baseline has to be taken **first**, or per-mutant. This is §TESTING VENUES' *"same SET beats same COUNT"* arriving in the mutation lane,
and it bites hardest **in a worktree** — which is where this fleet does all of its mutation work,
and where ten failures are present before anybody edits anything. ⚠️ It is not only a worktree
hazard: this branch's own unit tier was **RED for roughly four hours** on 2026-08-30 while several
seats mutated against it.

### 🔴 AND A FAILING SET COMPARES TEST IDS — COMPARE THE ASSERTION THAT FIRED

Raised by Rachel 🕊️ and Mr Radio 🦉 independently, 2026-08-30, against the first cut of the
subsection above. That cut offered *"compare the failing SETS"* as an equal alternative to a green
baseline. **It is not one, because a failing set is a set of test IDs and a test id says nothing
about WHY the test went red.** The two errors point opposite ways and both are live:

| what you see | what you conclude | what may actually be true |
|---|---|---|
| mutated set = baseline set | **SURVIVED** | the mutation really did break a test that was ALREADY red for an unrelated reason — a false survivor |
| mutated set = baseline set + one | **KILLED** | the extra red is a flake or a second artifact — a false kill |

⇒ **Compare the assertion that fired, not only the test that failed** — the message, the line, the
short-summary line, anything that distinguishes one red from another red in the same test.

🔴 **AND THE SAME MECHANIC DECIDES WHETHER A NEW GUARD RUNS AT ALL.** A test's assertions execute in
sequence, so an assertion added BEHIND one that is currently failing is **present in the file and
absent from the run** — and the test id in the failing set is byte-identical whether the new guard
passed, failed, or never executed. **A guard placed behind a red is carried, not exercised.**
**Worked instance, this reviewer's own, with the fix and both measurements.** The counts guard added
to `test_a_detector_change_forces_a_full_rescan` at `503000fe` sat after that test's fingerprint
assertion, and the fingerprint is red in this tree (row `8202d795`). The commit reported the file as
*"1 failed, 60 passed — byte-identical failing SET to the baseline"*, which was true and told nobody
the new assertion had not run. The counts were stale the whole time — recorded 239/116 against a
scan measuring 240/117 — so the guard would have fired on its first execution and never got one.

| placement, same record, same scan | result | what the failing set says |
|---|---|---|
| guard INLINE, behind the fingerprint assert | 1 failed, 60 passed | one id — the stale counts are invisible |
| guard in its OWN test | **2 failed, 60 passed** | two ids — the second NAMES the counts |

⇒ **Before claiming a new assertion guards anything, prove it is REACHED** — force the assertions
ahead of it green, or **move it into a test of its own**, which is the durable form: a separate test
is what lets a failing SET carry information instead of collapsing several reasons into one id.

### ⚠️ AND A CLEAN PASS IS A SAMPLE OF THE MUTATION SPACE, NOT A VERDICT ON IT

Six mutations against four files were run and reported as a pass. Clayton 😎's independent harness
then posed **40** against the same files and found **four survivors nobody had posed** — including
the one that mattered, a `site-packages` clause whose deletion left every test green. **The reviewer
had mutated that exact line and picked a different clause of it.**

⇒ A mutation pass reports on the mutations you thought of. **Two harnesses aimed at one file find
different things**, and that — not a matching sha — is the real argument for a second harness. A
cross-harness sha match establishes only **edit identity**: the same anchor and replacement against
the same source bytes is deterministic, so two correct harnesses *must* agree, and the match says
nothing about either verdict (Krishna 🦚, correcting this reviewer). **Exchange shas to catch a
DISAGREEMENT, never to manufacture a confirmation.**

Full derivation, with what each claim does NOT establish:
`src/rnd/v0.2.1/2026.08.30-two-harnesses-one-file-cross-reproduced-shas.md`.

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

## 🔴 A MEMENTO HAS TWO SLOTS, AND THE TWO DOORS READ DIFFERENT ONES

**This is not a defect and it is not a fallback.** `self_respin` reads the **root** slot;
`dismiss_sessions` (the reap) reads **io**. Written down here because it was filed as a bug on
2026-08-30 (row `f74d226a`, dropped as invalid) by a seat that had the measurement right and the
diagnosis wrong — a memento written to `io/` was refused by `self_respin`, which is the code doing
exactly what it says.

| Door | Slot | Pointer | Record |
|---|---|---|---|
| `dismiss_sessions` — a manager reaps a seat it **SPAWNED** | `io` | `io/mementos/<persona>.md` | `io/mementos/<persona>-<sid8>.md` |
| `self_respin` — a manager clears its **OWN** pane | `root` | `.claude-memento.md` (**persona-less**) | `.claude-memento-<persona>-<sid8>.md` |

**Write with the slot named** — the writer lands record, mirror and pointer in one operation, and
picking the slot is the whole decision:

```bash
memento_io.py write --slot root   # you are about to self_respin
memento_io.py write --slot io     # a manager is about to reap you
```

**Source of truth, cited rather than restated** — `SELF_RESPIN_SLOT = SLOT_ROOT` at
`src/lupin_mcp/memento_slot.py:83`, whose comment calls the split *"a DELIBERATE disjointness, not
a coincidence"*; `reap_memento`'s module docstring is the authority on which door owns which slot.
The check is wired, not decorative: `src/lupin_mcp/self_respin_core.py:572` defaults the
`verify_slot_fn` seam to `_default_verify_slot` and line 597 calls it on the live path.

⚠️ **THE ROOT POINTER IS PERSONA-LESS AND EVERY PERSONA IN THE REPO SHARES IT.** `.claude-memento.md`
is one file; measured 2026-08-30, Pocholo wrote `--slot root` at 14:41 and took the pointer, Mr.
Radio wrote at 15:20 and took it back. So your record can sit correctly at its own derived path
while the pointer a naive reader follows names **somebody else**. That is why the verifier's second
leg re-reads the pointer's own header `session_id` instead of trusting placement.

**A refusal here is legible — read it before theorising.** Given the wrong slot it names both
acceptable targets and the exact remedy command, and it recognises the one plausible wrong
destination (`~/.claude/mementos` at its bare top, which is neither slot nor a well-formed mirror —
a mirror lives at `<mirror_home>/<repo>/<record-path>`). If you are guessing which slot the verb
wanted, you did not read what it told you.

⇒ **Two records for one session is the NORMAL steady state**, not drift: a seat that may be either
reaped or self-respun legitimately has one in each slot. They are written by separate calls, so
they agree only where the writer put the same bytes in both — expect the self-respin nonce to
differ, and do not read that difference as corruption.

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
