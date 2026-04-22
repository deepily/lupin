# cosa-voice Onboarding Guide

How to set up cosa-voice MCP tools (notify, ask_yes_no, converse, etc.) for Claude Code sessions.

## Prerequisites

| Requirement | How to verify |
|-------------|---------------|
| `LUPIN_ROOT` env var | `echo $LUPIN_ROOT` should print the Lupin project path |
| Python venv | `$LUPIN_ROOT/src/cosa/.venv/bin/python --version` |
| `~/.lupin/config` | Must have `[environments]`, `[local]` sections |
| Lupin FastAPI server | Running on port 7999 (`src/scripts/run-fastapi-lupin.sh`) |
| Claude CLI | `claude --version` |

## Quick Start

```bash
$LUPIN_ROOT/src/scripts/install-cosa-voice.sh
```

This registers cosa-voice at **user scope** (global) — one registration works in every repo.

### Script Modes

```bash
install-cosa-voice.sh               # Install/update + verify
install-cosa-voice.sh --check-only  # Report without writing
install-cosa-voice.sh --uninstall   # Remove cosa-voice
```

## How It Works

### Project Auto-Detection

The MCP server detects which project you're in from your working directory:

| CWD contains | Detected project | Source |
|--------------|------------------|--------|
| `/lupin` | lupin | known |
| `/planning-is-prompting` | plan | known |
| `/cosa` (not nested in lupin) | cosa | known |
| anything else | CWD basename | basename |

No `MCP_PROJECT` env var needed — auto-detection handles it.

### Two-Part Status Display

Every Claude Code session shows cosa-voice status in two stages:

1. **SessionStart hook (immediate, ~1-2s)** — displayed in `additionalContext`:
   - MCP registration status (user/local scope)
   - Project detection result
   - Hook count (N/8)
   - Server reachability
   - Config file presence

2. **MCP server stderr (~2-5s later)** — displayed in MCP logs:
   - Project + detection source
   - Session ID + sender ID
   - Server URL
   - Account validation result

## Adding a New Project

### 1. Add to Known Projects Registry

Edit `src/cosa/agents/utils/sender_id.py` — add a path pattern in `detect_project()`:

```python
if "/your-project" in cwd:
    return "your-project"
```

And add to `KNOWN_PROJECTS` in `src/cosa/utils/notification_utils.py`.

### 2. Create Service Account

1. Open Lupin Admin UI: `http://localhost:7999/app/admin/users`
2. Create user: `claude.code@your-project.deepily.ai`
3. Add credentials to `~/.lupin/config`:

```ini
[your-project]
email = claude.code@your-project.deepily.ai
password = <the password from step 2>
```

### 3. Verify

Start Claude Code in the project directory. The SessionStart hook status block should show the project as "known".

## Troubleshooting

### cosa-voice tools not available

1. Run `install-cosa-voice.sh --check-only` to see what's missing
2. Check if a local `.mcp.json` is shadowing the global registration (local scope takes precedence)
3. Delete any stale `.mcp.json` in the project root

### Notifications not delivered

1. Verify Lupin server is running: `curl -s http://localhost:7999/docs | head -1`
2. Check `~/.lupin/config` has correct `global_notification_recipient`
3. Check MCP server logs (stderr) for account validation errors

### Project detected as wrong name

The MCP server checks CWD path patterns. If you're in a subdirectory that matches another project pattern (e.g., a directory named "lupin" inside another project), it may misdetect. Set `MCP_PROJECT` env var as an override in a local `.mcp.json` if needed.

## Migration from Per-Project `.mcp.json`

If you previously had per-project `.mcp.json` files:

1. Run `install-cosa-voice.sh` to register globally
2. Delete the local `.mcp.json` (or add it to `.gitignore`)
3. The global registration takes over automatically

The installer detects and removes stale local-scope registrations during installation.
