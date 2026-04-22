# CoSA Voice MCP Server

Voice I/O bridge for Claude Code - enables voice notifications and conversations through the CoSA/Lupin notification system.

## Tools

| Tool | Description | Blocking |
|------|-------------|----------|
| `converse()` | Speak to user, wait for response | Yes |
| `notify()` | Announce without waiting | No |
| `ask_yes_no()` | Quick yes/no decision | Yes |
| `ask_multiple_choice()` | Menu selection (mirrors AskUserQuestion) | Yes |
| `get_session_info()` | Get session identification | No |

### Common Parameters

All notification tools support these optional parameters:

| Parameter | Description |
|-----------|-------------|
| `priority` | `"low"`, `"medium"` (default), `"high"`, or `"urgent"` |
| `abstract` | Optional supplementary context (plan details, URLs, markdown) |

## Installation

### One-Command Setup (Recommended)

```bash
$LUPIN_ROOT/src/scripts/install-cosa-voice.sh
```

This registers cosa-voice at **user scope** (global) — one registration works in every repo. The MCP server auto-detects the project from your working directory.

See `src/docs/cosa-voice-onboarding.md` for the full onboarding guide.

### Manual Registration

```bash
claude mcp add --scope user --transport stdio \
  -e "PYTHONPATH=$LUPIN_ROOT/src" \
  -e "LUPIN_ROOT=$LUPIN_ROOT" \
  cosa-voice -- "$LUPIN_ROOT/src/cosa/.venv/bin/python" \
  "$LUPIN_ROOT/src/lupin_mcp/cosa_voice_mcp.py"
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LUPIN_ROOT` | Yes | - | Project root path (set by installer) |
| `PYTHONPATH` | Yes | - | Must include `$LUPIN_ROOT/src` (set by installer) |
| `MCP_PROJECT` | No | auto-detected | Optional override — auto-detection from CWD is preferred |
| `LUPIN_APP_SERVER_URL` | No | `http://localhost:7999` | Lupin server URL |
| `MCP_DEBUG` | No | - | Enable debug logging |

## Usage Examples

### Notify (fire-and-forget)

```python
# From Claude Code
notify( "Starting code analysis...", notification_type="progress" )
notify( "Build completed!", notification_type="task", priority="high" )

# With abstract context
notify( "Deploying to staging", abstract="**Files**: api.py, models.py\n**Branch**: feature/auth" )
```

### Converse (blocking)

```python
# Get user input
response = converse( "What naming convention should I use?" )

# Yes/no with default
response = converse(
    "Tests are failing. Should I continue?",
    response_type="yes_no",
    response_default="no"
)

# With abstract context
response = converse(
    "Which migration approach?",
    abstract="Option A: Incremental (safer)\nOption B: Full rebuild (faster)"
)
```

### Ask Yes/No (convenience wrapper)

```python
if ask_yes_no( "Delete the old backups?" ):
    # User said yes
    pass

# With abstract context
if ask_yes_no( "Proceed with migration?", abstract="This will update 47 database records" ):
    pass
```

### Ask Multiple Choice

```python
response = ask_multiple_choice( questions=[
    {
        "question": "Which database should we use?",
        "header": "Database",
        "multiSelect": False,
        "options": [
            { "label": "PostgreSQL", "description": "Relational database" },
            { "label": "MongoDB", "description": "Document database" }
        ]
    }
] )
# Returns: { "answers": { "Database": "PostgreSQL" } }
```

### Get Session Info

```python
info = get_session_info()
# Returns: { "project": "lupin", "sender_id": "claude.code@lupin.deepily.ai", ... }
```

## Session ID Format

Notifications are tagged with a sender ID:
```
claude.code@{project}.deepily.ai
```

The project name is auto-detected from your working directory. For example, running Claude Code from the Lupin project directory:
```
claude.code@lupin.deepily.ai
```

This allows the Lupin UI to group notifications by project.

## Requirements

- Python 3.11+
- fastmcp >= 2.14.0
- Lupin server running (default: port 7999)
- lupin_cli.notifications module available

## Troubleshooting

### Tools not available

Run the bootstrapper in check-only mode to diagnose:
```bash
$LUPIN_ROOT/src/scripts/install-cosa-voice.sh --check-only
```

### Server connection failed

```
Failed: Connection refused
```

**Solution**: Ensure Lupin server is running at the configured URL:
```bash
./src/scripts/run-fastapi-lupin.sh
```

### Debug mode

Set `MCP_DEBUG=1` in your shell environment before starting Claude Code, or add to the MCP registration:
```bash
claude mcp add --scope user -e "MCP_DEBUG=1" ...
```
