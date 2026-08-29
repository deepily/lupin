#!/bin/bash
# watch-cc-memory.sh — Name the Claude Code session that is running away with memory.
#
# Store row df5c3696. On 2026-08-22 the kernel killed two Claude Code processes at
# 229 GB and 124 GB and nobody could say which sessions they were: the listener logs
# under ~/.claude/sessions do not record the owner pid in a greppable form. This
# samples RSS on an interval and writes ONE line when a process crosses the
# threshold, carrying the pid, the RSS and — resolved from the listener's own
# command line — the session id. With that line, the session's transcript names the
# tool call that allocated.
#
# Usage:
#   ./watch-cc-memory.sh                                   # 16 GB threshold, every 15s
#   ./watch-cc-memory.sh --threshold-gb 8 --interval 5
#   ./watch-cc-memory.sh --once --report                   # one pass, list everything
#   ./watch-cc-memory.sh --log ~/.claude/sessions/cc-memory.log
#
# Reads only; it never kills, notifies, or touches a session.

set -euo pipefail

LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"

PYTHON="$LUPIN_ROOT/.venv/bin/python3"
if [[ ! -x "$PYTHON" ]]; then PYTHON="python3"; fi

exec env PYTHONPATH="$LUPIN_ROOT/src:${PYTHONPATH:-}" \
    "$PYTHON" -m cosa.utils.cc_memory_watch "$@"
