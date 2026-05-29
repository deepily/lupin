#!/bin/bash
# start-cc-with-tmux.sh — Launch Claude Code inside a named tmux session.
#
# Creates a new tmux session (or reattaches to an existing one) and starts
# Claude Code inside it. The session name is recorded in the session bridge
# file by the SessionStart hook, enabling the CCNotificationListener to send
# tmux Enter keystrokes for voice injection when CC is idle.
#
# Usage:
#   ./start-cc-with-tmux.sh [session-name] [extra-claude-args...]
#   ./start-cc-with-tmux.sh --headless <session-name> --prompt "<initial task>" [extra-claude-args...]
#
# Modes:
#   interactive (default) — creates the session then `tmux attach`es to it.
#   --headless            — creates a DETACHED session and does NOT attach.
#                           Used by the manager-spawned-reviewers MCP tools
#                           (spawn_sessions) to launch worker sessions the
#                           user never sits in front of. Prints the session
#                           name to stdout and exits 0.
#
#   --prompt "<text>"     — initial task prompt; becomes the `claude "<text>"`
#                           first arg so the spawned session reads its brief on
#                           startup. Quote it; it is passed as a single arg.
#
#   --dry-run             — print the tmux command that WOULD run, without
#                           launching. (Headless dry-run for tests/preview.)
#
# Examples:
#   ./start-cc-with-tmux.sh lupin
#   ./start-cc-with-tmux.sh lupin --resume
#   ./start-cc-with-tmux.sh                                  # defaults to a hashed name
#   ./start-cc-with-tmux.sh --headless review-bugs-1 --prompt "You are a cascade reviewer..."
#
# venv provision: a session spawned from the cosa-voice MCP subprocess does NOT
# inherit the user's interactively-activated shell environment, so its
# SessionStart hook + cc-notification-listener (which import `cosa`) would fail
# to resolve the interpreter / PYTHONPATH. We therefore activate the cosa venv
# and export PYTHONPATH INSIDE the tmux command so the spawned `claude` — and
# every hook it fires — inherits them. Activation is idempotent and harmless
# when the venv is already active (interactive use), so it runs in both modes.

set -euo pipefail

HEADLESS=0
DRY_RUN=0
PROMPT=""
POSITIONALS=()

# ── Parse option flags from ANY position; collect positionals separately ──────
# Recognized --flags are pulled out wherever they appear; everything else
# (session name + any pass-through claude args like --resume) lands in
# POSITIONALS, preserving order. `--` ends option scanning explicitly.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --headless ) HEADLESS=1; shift ;;
        --dry-run  ) DRY_RUN=1;  shift ;;
        --prompt   ) PROMPT="${2:-}"; shift 2 ;;
        -- )         shift; while [[ $# -gt 0 ]]; do POSITIONALS+=( "$1" ); shift; done; break ;;
        * )          POSITIONALS+=( "$1" ); shift ;;
    esac
done

SESSION_NAME="${POSITIONALS[0]:-cc-tmux-session-$(date +%s | md5sum | cut -c1-8)}"
CLAUDE_ARGS=( "${POSITIONALS[@]:1}" )  # everything after the session name → claude

# ── venv + PYTHONPATH provision (see header) ──────────────────────────────────
LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"
VENV_ACTIVATE="$LUPIN_ROOT/src/cosa/.venv/bin/activate"

# Build the inner command run inside the tmux pane. Activating the venv (if
# present) and exporting PYTHONPATH are prefixed so `claude` + its hooks inherit
# the cosa environment regardless of how the spawner's own env was set up. Each
# pass-through arg + the prompt is %q-quoted so spaces/quotes survive the trip
# through the single tmux command string.
CLAUDE_CMD="claude"
for _a in "${CLAUDE_ARGS[@]}"; do
    CLAUDE_CMD+=" $(printf '%q' "$_a")"
done
if [[ -n "$PROMPT" ]]; then
    CLAUDE_CMD+=" $(printf '%q' "$PROMPT")"   # initial brief as a single arg
fi

INNER="export PYTHONPATH=$(printf '%q' "$LUPIN_ROOT/src:${PYTHONPATH:-}"); "
if [[ -f "$VENV_ACTIVATE" ]]; then
    INNER+="source $(printf '%q' "$VENV_ACTIVATE"); "
fi
INNER+="$CLAUDE_CMD"

# ── Dry-run: print what would happen and exit (no tmux side effects) ──────────
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN headless=$HEADLESS session='$SESSION_NAME'"
    echo "tmux new-session -d -s '$SESSION_NAME' <persona-env> \"$INNER\""
    exit 0
fi

# Per-project preferred personas. Forwarded into the tmux session via -e so the
# SessionStart hook (register_session.py) sees them regardless of the tmux
# server's frozen env or whether ~/.bashrc was sourced. The hook reads only the
# key matching detect_project(), so unused keys are inert.
PERSONA_ENV_FLAGS=(
    -e "COSA_VOICE_PREFERRED_PERSONA__LUPIN=Tiberius"
    -e "COSA_VOICE_PREFERRED_PERSONA__LUPIN_MOBILE=Tiffany"
    -e "COSA_VOICE_PREFERRED_PERSONA__PLAN=María"
    -e "COSA_VOICE_PREFERRED_PERSONA__LOOKML=Sam"
)

# Forward manager-spawn lineage env (set by session_spawner on the spawning
# process) INTO the tmux session via -e. tmux does not inherit arbitrary parent
# env for a new session, so without this the child's SessionStart hook never
# sees COSA_VOICE_SPAWNED_BY/HEADLESS/ROLE and can't self-tag / start
# speakerphone-off. (Caught by the live spawn E2E 2026-05-28.)
for _v in COSA_VOICE_SPAWNED_BY COSA_VOICE_HEADLESS COSA_VOICE_ROLE; do
    if [[ -n "${!_v:-}" ]]; then
        PERSONA_ENV_FLAGS+=( -e "$_v=${!_v}" )
    fi
done

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    if [[ "$HEADLESS" -eq 1 ]]; then
        echo "tmux session '$SESSION_NAME' already exists — leaving it (headless)."
        echo "$SESSION_NAME"
        exit 0
    fi
    echo "tmux session '$SESSION_NAME' already exists — attaching..."
    tmux attach -t "$SESSION_NAME"
else
    echo "Creating tmux session '$SESSION_NAME' with Claude Code..."
    tmux new-session -s "$SESSION_NAME" "${PERSONA_ENV_FLAGS[@]}" -d "$INNER"
    if [[ "$HEADLESS" -eq 1 ]]; then
        # Headless: do NOT attach. Emit the session name for the caller to capture.
        echo "$SESSION_NAME"
    else
        tmux attach -t "$SESSION_NAME"
    fi
fi
