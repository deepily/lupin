# LUPIN DEVELOPMENT GUIDE

## COMMANDS
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (Runs on port 7999)
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Docker build: `docker build -f docker/lupin/Dockerfile .`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`
- Install cosa-voice MCP (global): `src/scripts/install-cosa-voice.sh` (user scope, all repos)

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

**Job Types Handled**:
- **AgentBase** — Traditional sync agents (MathAgent, CalendarAgent, DateAndTimeAgent, etc.)
- **SolutionSnapshot** — Cached solution playback from prior runs
- **AgenticJobBase** — Long-running async jobs (DeepResearchJob, PodcastGeneratorJob, etc.)
- **ClaudeCodeJob** — Claude Agent SDK tasks in BOUNDED (fire-and-forget) or INTERACTIVE (bidirectional) mode

**Key Files**:
- `src/cosa/rest/queue_protocol.py` — QueueableJob protocol definition
- `src/cosa/agents/agentic_job_base.py` — Abstract base for long-running jobs
- `src/cosa/rest/agentic_job_factory.py` — Agentic job creation factory
- `src/cosa/rest/todo_fifo_queue.py` — Ingress queue + agent routing
- `src/cosa/rest/running_fifo_queue.py` — Execution engine
- `src/cosa/rest/queue_consumer.py` — Background consumer thread

**Packaging Guide**: `src/rnd/2026.02.12-cj-flow-bounded-job-packaging-guide.md`

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
  - **IMPORTANT**: `/src/cosa/` is a separate Git repository (git@github.com:deepily/cosa.git)
  - This directory employs the Git submodule/subtree pattern
  - CoSA has its own README.md and CLAUDE.md files
  - When working with CoSA code, be aware that changes may need to be committed to both repositories
  - **CRITICAL FOR CLAUDE**: Never attempt to manage the git state of the CoSA repository when working
    within the Lupin project. Do not offer to stage, commit, or push changes to the CoSA
    repository. Only manage git operations for the parent Lupin repository.
  - **Note**: See "GIT REPOSITORY MANAGEMENT" section for complete nested repository handling
- `/src/cosa/agents/`: Agent implementations (math, calendar, etc.)
- `/src/cosa/app/`: Core application components
- `/src/cosa/memory/`: Data persistence and memory management
- `/src/cosa/tools/`: External integrations and tools
- `/src/cosa/utils/`: Shared utility functions
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
- **R&D Planning Docs**: `src/rnd/2025.10.15-sse-notifications/` (historical)

## STARTUP PROCEDURE
- The first thing you should do when you start a session is read the global Claude configuration file and follow its instructions.
- **HISTORY FILE READING**: Read the main history file (`/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`) which contains recent 30-day context and links to archived periods
- **IMPLEMENTATION DOCUMENT**: Read the current implementation document referenced at the top of history.md
- **ARCHIVE ACCESS**: If deeper historical context needed, follow links to `history/YYYY-MM-history.md` files
- **IGNORE SUB-REPO HISTORIES**: Do NOT read these sub-repository history files as they are managed separately:
  - `src/lupin-plugin-firefox/history.md` (Firefox plugin sub-repo)
  - `src/cosa/history.md` (CoSA framework sub-repo)  
  - `src/lupin-mobile/history.md` (Mobile app sub-repo)

## PROJECT SHORT NAMES
- This repo's SHORT_PROJECT_PREFIX is [LUPIN]

## REPOSITORY RELATIONS
- There is another repo that's a part of the larger project contained in the directory `lupin-plugin-firefox`
- This repo must be managed separately and cannot be managed by Claude

## RUNNING/TESTING FASTAPI APPLICATIONS
- Please assume that there is a Fast API server instance bound to port 7999. I will start and stop it if needed. You never need to spin up another instance unless it's for a ephemeral use on port 8000.

## GIT REPOSITORY MANAGEMENT

**CRITICAL**: This project contains multiple nested Git repositories that must be managed separately.

### Repository Structure

**Parent Repository** (Manage with /plan-session-end):
- **Name**: Lupin (evolved from Genie-in-the-Box)
- **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/`
- **Prefix**: [LUPIN]
- **Git Operations**: Managed normally via `/plan-session-end` workflow

**Nested Repositories** (DO NOT manage from parent context):

1. **CoSA Framework**
   - **Location**: `/src/cosa/`
   - **Remote**: git@github.com:deepily/cosa.git
   - **Pattern**: Git submodule/subtree
   - **Docs**: Has own README.md and CLAUDE.md
   - **Management**: Must commit to CoSA repo separately when working in CoSA context

2. **Firefox Plugin**
   - **Location**: `/src/lupin-plugin-firefox/`
   - **Management**: Separate repository, managed independently
   - **History**: Has own history.md (DO NOT read from Lupin context)

3. **Mobile App**
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
• /src/cosa/ (3 modified files)
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

**When working in CoSA** (`cd src/cosa/`):
- Read `/src/cosa/CLAUDE.md` for CoSA-specific guidance
- Use CoSA's own session management
- Commit to CoSA repository separately

**When working in Firefox Plugin** (`cd src/lupin-plugin-firefox/`):
- Manage as independent project
- Has own git history and workflows

**When working in Mobile App** (`cd src/lupin-mobile/`):
- Manage as independent project
- Has own git history and workflows

## TESTING

Lupin uses a three-tier testing strategy for comprehensive validation:

### Test Types

1. **Unit Tests** (`src/tests/unit/`)
   - Fast, isolated function tests (1-10ms per test)
   - Test individual functions with mocked dependencies
   - Coverage: jwt_service (14 tests), password_service, user_service, etc.
   - Run: `pytest src/tests/unit/`

2. **Smoke Tests** (inline `quick_smoke_test()` functions)
   - Quick module-level sanity checks (10-100ms per module)
   - Validate modules load and core functions work
   - Coverage: ~50 tests across all major modules
   - Run: `python -m cosa.rest.jwt_service` (per module)

3. **Integration Tests** (`src/tests/integration/`)
   - End-to-end user flow validation (100-1000ms per test)
   - Test complete workflows across API, database, and authentication
   - Coverage: 43 comprehensive tests (auth, admin user management, queue filtering)
   - Run: `./src/tests/run-integration-tests.sh -v` (automated with server management)

4. **WebSocket Tests** (`src/tests/websocket_smoke/`)
   - WebSocket functionality validation
   - Coverage: 50 tests
   - Run: `src/scripts/run-websocket-smoke-tests.sh`

5. **E2E UI Tests** (`src/tests/e2e_ui/`)
   - Playwright Chromium headless browser tests against live server
   - Coverage: 285 functional tests + 12 visual regression
   - **CRITICAL**: Always use `--bg` flag from Claude Code (suite takes ~17min, exceeds 10min Bash timeout)
   - Run: `./src/scripts/run-e2e-ui-tests.sh --bg -v`
   - Visual only: `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual`
   - Update baselines: `./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual`
   - Monitor: `tail -20 /tmp/e2e-ui-latest.log`
   - Status: `kill -0 $(cat /tmp/e2e-ui-tests.pid) 2>/dev/null && echo running || echo done`
   - Snapshots: `src/tests/e2e_ui/__snapshots__/` (version-controlled)

6. **Interactive Proxy Tests** (`src/tests/smoke/test_proxy_integration.py`)
   - Automated interactive testing with notification proxy auto-answer
   - Coverage: 12 scenarios across Calculator, CRUD, and Expediter agents
   - Tests submit-and-poll pipelines with proxy-driven notification responses
   - Run: `python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm`
   - **Guide**: `src/docs/automated-interactive-testing.md`

### Running Tests

```bash
# Integration tests (RECOMMENDED - automated)
./src/tests/run-integration-tests.sh -v              # All integration tests
./src/tests/run-integration-tests.sh -v -s           # Very verbose
./src/tests/run-integration-tests.sh test_auth*.py   # Specific pattern

# Unit tests
pytest src/tests/unit/                               # All unit tests
pytest -v src/tests/unit/                            # Verbose

# All pytest tests (unit + integration)
pytest src/tests/                                    # Requires manual server setup

# With coverage report
pytest --cov=cosa.rest --cov-report=html src/tests/
```

### Documentation

- **Testing Overview**: `src/tests/README.md` - Complete testing strategy and hierarchy
- **Integration Tests**: `src/tests/integration/README.md` - Detailed integration test guide
- **Interactive Proxy Tests**: `src/docs/automated-interactive-testing.md` - Comprehensive proxy testing guide
- **Smoke Tests**: `src/tests/smoke/README.md` - Quick-start guide for smoke tests
- **Unit Tests**: Inline documentation in test files

### Test Coverage

- **Total Tests**: ~387+ (14+ unit, ~50 smoke, 43 integration, 50 WebSocket, 265 E2E UI)
- **Auth System Coverage**: 85-90%
- **Critical Paths**: Login, registration, token refresh, password change all tested

See `src/tests/README.md` for comprehensive testing documentation.

## PR MERGE REQUIREMENTS

**CRITICAL**: The following tests MUST pass before merging any branch to main.

### Pre-Merge Test Checklist

| Test Suite | Command | Requirement |
|------------|---------|-------------|
| Unit Tests | `pytest src/tests/unit/` | 100% pass |
| WebSocket Tests | `./src/scripts/run-websocket-smoke-tests.sh` | 100% pass |
| E2E UI Tests | `./src/scripts/run-e2e-ui-tests.sh --bg -v` | 100% pass |
| Visual Regression | `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual` | 100% pass |
| Integration Tests | `./src/tests/run-integration-tests.sh -v` | 100% pass (FINAL GATE) |

### Integration Tests are the Final Gate

Integration tests are the **FINAL validation step** before any branch merge to main.

**Why integration tests are critical**:
- Test complete user workflows end-to-end
- Validate API, database, and authentication work together
- Catch regressions that unit tests miss
- Require a running server (realistic conditions)

### Pre-Merge Workflow

```bash
# Complete pre-merge validation sequence
pytest src/tests/unit/ -v && \
./src/scripts/run-websocket-smoke-tests.sh && \
./src/scripts/run-e2e-ui-tests.sh --bg -v && \
./src/tests/run-integration-tests.sh -v
```

**Note**: E2E UI tests run in background (`--bg`) — monitor via `tail -20 /tmp/e2e-ui-latest.log`.
Wait for completion before proceeding to integration tests (the final gate).

### When Tests Fail

- **DO NOT** merge with failing tests
- **Fix the failing tests first**, then re-run the full suite
- If a test is legitimately flaky (not your code), document and create a separate fix

### Testing Anti-Patterns

- **NEVER** use `curl` commands for pipeline or integration testing — use automated test scripts
- **NEVER** manually POST to `/api/push` and poll `/api/get-queue/done` — use `LivePipelineTestBase`
- **NEVER** create bespoke curl scripts as a substitute for repeatable test automation
- Manual curl is acceptable ONLY for: API reference documentation, deployment health checks, one-off debugging (never committed)
- When building new agents, create an automated smoke test — see `.claude/skills/agentic-voice-workflow/SKILL.md`

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
| `routers/*.py` endpoint decorators | `/docs` auto-updates (no action needed) |
| `websocket_manager.py` | `src/docs/websocket-architecture.md` |
| `routers/websocket.py` | `src/docs/websocket-events.md`, `websocket-architecture.md` |
| `routers/notifications.py` architecture | `src/docs/notification-api.md` |
| `lupin-app.ini` WebSocket keys | `src/docs/websocket-configuration.md` |
| `lupin-app.ini` `websocket available events` | `src/docs/websocket-events.md`, `websocket-configuration.md` |
| New router added | `src/docs/rest-api-reference.md` quick-reference table |
| Auth services (`jwt_service`, `user_service`, etc.) | `src/docs/auth/architecture-overview.md` |
| Decision proxy / trust logic | `src/docs/proxy-admin-guide.md` |
| Frontend page routes | `src/docs/rest-api-reference.md` (Pages section) |

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
