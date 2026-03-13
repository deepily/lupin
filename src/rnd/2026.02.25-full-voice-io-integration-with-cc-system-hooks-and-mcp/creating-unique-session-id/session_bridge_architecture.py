# Claude Code → CoSA Voice MCP: Session ID Bridge Architecture
# Multi-Instance Isolation for Same-Repo Concurrent Sessions

"""
PROBLEM:
  - Multiple Claude Code instances run in the same repo
  - Each spawns its own CoSA Voice MCP server (stdio transport)
  - MCP servers need the Claude Code session_id for message routing
  - Claude Code does NOT expose session_id to MCP server env
  - MCP servers start BEFORE SessionStart hooks fire

TIMELINE:
  t=0    Claude Code launches
  t=0.1  MCP servers spawned (no session_id yet!)
  t=0.5  SessionStart hook fires (session_id available via stdin JSON)
  t=0.6  Hook writes session file → MCP server reads it
  t=∞    All subsequent tool calls use the real session_id

SOLUTION: Two-phase handshake via filesystem

  ┌──────────────────┐     SessionStart hook      ┌─────────────────────┐
  │  Claude Code #1  │ ──── stdin JSON ──────────► │ register_session.py │
  │  session: abc123  │                            │                     │
  │  PID: 12345       │                            │ Writes:             │
  └────────┬─────────┘                             │ ~/.claude/sessions/ │
           │                                       │   cc-12345.json     │
           │ spawns (stdio)                        └─────────┬───────────┘
           ▼                                                 │
  ┌──────────────────┐                                       │
  │ CoSA Voice MCP   │ ◄── polls/reads ─────────────────────┘
  │ session_bridge.py│
  │                  │     Resolves session_id:
  │ PPID = 12345     │     1. $CLAUDE_SESSION_ID (future)
  │                  │     2. cc-{PPID}.json file
  │ SESSION_ID =     │     3. Fallback UUID
  │   "abc123" ✓     │
  └──────────────────┘

  ┌──────────────────┐     SessionStart hook      ┌─────────────────────┐
  │  Claude Code #2  │ ──── stdin JSON ──────────► │ register_session.py │
  │  session: def456  │                            │                     │
  │  PID: 12399       │                            │ Writes:             │
  └────────┬─────────┘                             │ ~/.claude/sessions/ │
           │                                       │   cc-12399.json     │
           │ spawns (stdio)                        └─────────┬───────────┘
           ▼                                                 │
  ┌──────────────────┐                                       │
  │ CoSA Voice MCP   │ ◄── polls/reads ─────────────────────┘
  │ session_bridge.py│
  │                  │
  │ PPID = 12399     │
  │                  │
  │ SESSION_ID =     │
  │   "def456" ✓     │
  └──────────────────┘

ISOLATION KEY: PPID (parent process ID)
  - Each Claude Code instance has a unique PID
  - Each MCP server knows its PPID (= Claude Code's PID)
  - Session file keyed by PPID: cc-{pid}.json
  - No cross-talk between instances

FILES:
  ~/.claude/hooks/register_session.py   — SessionStart hook (writes session file)
  session_bridge.py                      — MCP-side reader (resolves session_id)
  ~/.claude/sessions/cc-{PID}.json      — Per-instance session metadata

  ~/.claude/settings.json must include:
  {
    "hooks": {
      "SessionStart": [{
        "hooks": [{
          "type": "command",
          "command": "python3 ~/.claude/hooks/register_session.py"
        }]
      }]
    }
  }

CLEANUP:
  Session files are small (<200 bytes) and keyed by PID.
  Stale files from dead processes are harmless but can be cleaned:
    find ~/.claude/sessions -name 'cc-*.json' -mmin +60 -delete

FUTURE-PROOF:
  When Anthropic implements GitHub #17188 (CLAUDE_SESSION_ID env var),
  session_bridge.py will use it automatically (Tier 1 resolution)
  with zero code changes needed.
"""
