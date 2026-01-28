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

### 1. Add MCP Server to Claude Code

```bash
claude mcp add cosa-voice -- python ${LUPIN_ROOT}/src/lupin_mcp/cosa_voice_mcp.py
```

### 2. Configure Environment Variables

Create or update your MCP config file (`~/.claude/cosa_mcp.json`):

```json
{
  "mcpServers": {
    "cosa-voice": {
      "type": "stdio",
      "command": "python",
      "args": ["${LUPIN_ROOT}/src/lupin_mcp/cosa_voice_mcp.py"],
      "env": {
        "MCP_PROJECT": "lupin",
        "LUPIN_APP_SERVER_URL": "http://localhost:7999"
      }
    }
  }
}
```

**Important**: `MCP_PROJECT` is set by the config file, not manually by the user.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_PROJECT` | Yes | - | Project name (set by MCP config) |
| `LUPIN_APP_SERVER_URL` | No | `http://localhost:7999` | Lupin server URL |
| `MCP_DEBUG` | No | - | Enable debug logging |
| `LUPIN_ROOT` | No | - | Project root path |

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

For example, with `MCP_PROJECT=lupin`:
```
claude.code@lupin.deepily.ai
```

This allows the Lupin UI to group notifications by project.

## Requirements

- Python 3.11+
- fastmcp >= 2.14.0
- Lupin server running (default: port 7999)
- cosa.cli module available

## Troubleshooting

### MCP_PROJECT not set

```
Error: MCP_PROJECT environment variable required
```

**Solution**: Add `"MCP_PROJECT": "your-project"` to your MCP config's env section.

### Server connection failed

```
Failed: Connection refused
```

**Solution**: Ensure Lupin server is running at the configured URL:
```bash
./src/scripts/run-fastapi-lupin.sh
```

### Debug mode

Enable debug logging:
```json
{
  "env": {
    "MCP_PROJECT": "lupin",
    "MCP_DEBUG": "1"
  }
}
```
