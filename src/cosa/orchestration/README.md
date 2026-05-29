# Claude Code Orchestration

This module provides infrastructure for programmatically invoking Claude Code with voice I/O capabilities via MCP tools.

## Overview

The `ClaudeCodeDispatcher` routes tasks to Claude Code using two execution modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **BOUNDED** (Option A) | Print mode (`claude -p`) | CI/CD pipelines, scheduled jobs, bounded tasks |
| **INTERACTIVE** (Option B) | SDK client | Open-ended sessions with bidirectional control |

## Quick Start

### Option A: Bounded Tasks (Print Mode)

```python
from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType

dispatcher = ClaudeCodeDispatcher()

result = await dispatcher.dispatch( Task(
    id="task-001",
    project="lupin",
    prompt="Run tests and fix any failures",
    type=TaskType.BOUNDED
) )

if result.success:
    print( f"Completed: {result.result}" )
else:
    print( f"Failed: {result.error}" )
```

### Option B: Interactive Sessions (SDK Client)

```python
from cosa.orchestration import ClaudeCodeDispatcher, Task, TaskType

# Custom callback to handle streaming messages
def on_message( task_id: str, message ):
    print( f"[{task_id}] {type( message ).__name__}" )

dispatcher = ClaudeCodeDispatcher( on_message=on_message )

# Interactive session with bidirectional control
result = await dispatcher.dispatch( Task(
    id="session-001",
    project="lupin",
    prompt="Let's work on the authentication refactor together",
    type=TaskType.INTERACTIVE,
    max_turns=50
) )

if result.success:
    print( f"Session: {result.session_id}" )
    print( f"Cost: ${result.cost_usd:.4f}" )
```

### Bidirectional Control (Option B Only)

```python
# Inject a message into an active session
success = await dispatcher.inject( "session-001", "Actually, let's focus on the JWT module first" )

# Interrupt an active session
success = await dispatcher.interrupt( "session-001" )

# Get list of active sessions
sessions = dispatcher.get_active_sessions()
```

### CLI Usage

```bash
# Set required environment variable
export LUPIN_ROOT=/path/to/lupin

# Run a bounded task
python -m cosa.orchestration.claude_code_dispatcher \
    "List the files in the current directory" \
    --project lupin --type bounded --max-turns 5
```

## Requirements

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LUPIN_ROOT` | Yes | Path to lupin project root |
| `MCP_PROJECT` | No | Project name fallback (auto-detected from task) |
| `LUPIN_APP_SERVER_URL` | No | Server URL (default: http://localhost:7999) |

### Dependencies

- Python 3.11+
- Claude Code CLI (`@anthropic-ai/claude-code`)
- Lupin server running on port 7999
- MCP server registered with Claude Code

For interactive mode (Option B):
- `pip install claude-agent-sdk`

## MCP Voice Tools

The dispatcher configures Claude Code to use these MCP voice tools:

| Tool | Description |
|------|-------------|
| `converse()` | Ask user and wait for voice response (blocking) |
| `notify()` | Announce status update (fire-and-forget) |
| `ask_yes_no()` | Quick yes/no decision (blocking) |

## Task Configuration

```python
@dataclass
class Task:
    id: str                    # Unique task identifier
    project: str               # Project name (e.g., "lupin")
    prompt: str                # Task prompt for Claude
    type: TaskType             # BOUNDED or INTERACTIVE
    max_turns: int = 50        # Maximum conversation turns
    timeout_seconds: int = 3600  # Timeout (1 hour default)
    working_dir: str = None    # Defaults to parent of LUPIN_ROOT
```

## Result Structure

```python
@dataclass
class TaskResult:
    task_id: str
    success: bool
    session_id: Optional[str]   # Claude Code session ID
    result: Optional[str]       # Task output
    cost_usd: Optional[float]   # API cost
    duration_ms: Optional[int]  # Execution time
    error: Optional[str]        # Error message if failed
    exit_code: Optional[int]    # Process exit code
```

## Examples

### CI/CD Pipeline

```bash
#!/bin/bash
# Run in GitHub Actions or GitLab CI

export LUPIN_ROOT=/workspace/lupin

python -m cosa.orchestration.claude_code_dispatcher \
    "Review the changes in this PR and suggest improvements" \
    --project "$GITHUB_REPOSITORY" \
    --type bounded \
    --max-turns 100
```

### Cron Job

```bash
#!/bin/bash
# Nightly code analysis

python -m cosa.orchestration.claude_code_dispatcher \
    "Analyze code quality and create issues for improvements" \
    --project lupin \
    --type bounded \
    --timeout 7200
```

## Test Coverage

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_sdk_validation.py` | 11 | SDK import and options validation |
| `test_dispatcher_e2e.py` | 23 | Bounded and interactive E2E tests |
| `test_dispatcher_bidirectional.py` | 8 | inject() and interrupt() tests |

Run tests:
```bash
# All dispatcher tests
pytest src/tests/integration/test_dispatcher_*.py -v

# Quick tests (no Claude invocation)
pytest src/tests/integration/test_dispatcher_*.py -v -m "not e2e"

# Full E2E tests
pytest src/tests/integration/test_dispatcher_*.py -v -m "e2e"
```

## Related Documents

- `src/rnd/2025.12.31-mcp-implementation-plan.md` - Original MCP implementation plan
- `src/rnd/2025.12.30-claude_code_voice_mcp_guide.md` - Voice MCP design guide
- `src/rnd/2026.01.02-02-option-b-sdk-client-planning.md` - Option B planning document
- `src/lupin_mcp/README.md` - MCP server documentation
