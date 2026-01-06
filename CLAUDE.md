# LUPIN DEVELOPMENT GUIDE

## COMMANDS
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (Runs on port 7999)
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Docker build: `docker build -f docker/lupin/Dockerfile .`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`

## CLAUDE CODE SLASH COMMANDS
- `/smoke-test-baseline [scope]` - Establish comprehensive baseline before changes
  - **scope**: `full` (Lupin + COSA) or `lupin` (Lupin-only), default: `full`
  - Creates timestamped logs and baseline report in `src/rnd/`
  - Pure data collection - no remediation attempts
- `/smoke-test-remediation [baseline_report] [scope]` - Verify and fix post-change issues
  - **baseline_report**: Path to baseline report (auto-detects latest if not provided)
  - **scope**: `FULL|CRITICAL_ONLY|SELECTIVE|ANALYSIS_ONLY`, default: `FULL`
  - Compares against baseline, identifies regressions, performs systematic remediation

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
   - Coverage: 50 tests (92% pass rate)
   - Run: `src/scripts/run-websocket-smoke-tests.sh`

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
- **Unit Tests**: Inline documentation in test files

### Test Coverage

- **Total Tests**: ~122 (14+ unit, ~50 smoke, 8 integration, 50 WebSocket)
- **Auth System Coverage**: 85-90%
- **Critical Paths**: Login, registration, token refresh, password change all tested

See `src/tests/README.md` for comprehensive testing documentation.

## HISTORY STRUCTURE NOTES
- **Project Span**: December 2024 - Present (Lupin evolution from Genie-in-the-Box)
- **Key Archived Periods**: 
  - 2024.12-2025.05: PEFT training, agent migrations, Flask→FastAPI transition
  - 2025.06: Lupin renaming, notification system, WebSocket foundation
  - 2025.07: Progressive TTS streaming, user routing architecture
  - 2025.08: Unit testing framework, Fresh Queue UI, audio debugging
- **Current Implementation Docs**: Referenced in history.md header
- **Archive Location**: `history/` directory with monthly organization
