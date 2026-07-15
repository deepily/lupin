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
VERTEX=0
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
        --vertex   ) VERTEX=1;   shift ;;
        --prompt   ) PROMPT="${2:-}"; shift 2 ;;
        -- )         shift; while [[ $# -gt 0 ]]; do POSITIONALS+=( "$1" ); shift; done; break ;;
        * )          POSITIONALS+=( "$1" ); shift ;;
    esac
done

SESSION_NAME="${POSITIONALS[0]:-cc-tmux-session-$(date +%s | md5sum | cut -c1-8)}"
CLAUDE_ARGS=( "${POSITIONALS[@]:1}" )  # everything after the session name → claude

# ── venv + PYTHONPATH provision (see header) ──────────────────────────────────
LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"
VENV_ACTIVATE="$LUPIN_ROOT/.venv/bin/activate"

# ── --vertex: route THIS session to GCP Vertex (metered billing), not Max ─────
#
# Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md
#
# The default `claude` path stays UNTOUCHED on Max. Only the flagged session is
# metered. Everything below exists because of three findings that each nearly
# shipped a silent-billing bug:
#
#   F-A11  THIS LAUNCHER MUST NOT BE THE PROCESS THAT BIRTHS A TAINTED TMUX SERVER.
#          `tmux new-session` freezes the caller's env into the server IFF it CREATES
#          it; a server born from a Vertex shell hands those vars to EVERY later
#          session on that socket, Max ones included, which are then billed for a
#          toggle they never asked for.
#          🔴 REBUILT 2026-07-14: the old guard scrubbed `tmux start-server`, which
#          MEASURABLY PROPAGATES NOTHING — scrubbed and unscrubbed produced IDENTICAL
#          clean panes, so the guard could not have come out otherwise. It was
#          decoration, and it ran ONLY on the --vertex path while the MAX path birthed
#          the server with no guard at all. The scrub now rides `new-session`, on BOTH
#          paths. See the measured block at the SERVER_SCRUB build.
#
#   F-A7   SCRUB, DON'T OMIT. A positive `-e` allowlist ADDS keys and SUBTRACTS
#          NOTHING; an unlisted key silently inherits the server env. Omission is
#          not subtraction. We explicitly `env -u` the whole hostile set.
#
#   §5c    CERTIFY vs ENFORCE. The only truthful region oracle is a rawPredict, and
#          it costs money — so a free launch-time region probe CANNOT exist. This
#          script does not RE-DERIVE the region; it ENFORCES a constant certified
#          once (LUPIN_VERTEX_REGION). vertex_env.py holds the guards.
VERTEX_ENV_FLAGS=()
if [[ "$VERTEX" == "1" ]]; then
    # Compose + guard in Python (bash has no branch-coverage instrument, so the
    # guards cannot be honestly proven in shell — §5e). This FAILS LOUD and
    # non-zero on any hostile var, project disagreement, or missing region.
    VERTEX_COMPOSED="$(
        PYTHONPATH="$LUPIN_ROOT/src:${PYTHONPATH:-}" python3 -c '
import sys
from cosa.utils.vertex_env import VertexEnvError, compose_vertex_env, format_dry_run
try:
    print( format_dry_run( compose_vertex_env() ) )
except VertexEnvError as error:
    sys.stderr.write( f"\n[--vertex] REFUSING TO LAUNCH: {error}\n\n" )
    sys.exit( 1 )
'
    )" || exit 1

    while IFS= read -r kv; do
        [[ -n "$kv" ]] && VERTEX_ENV_FLAGS+=( -e "$kv" )
    done <<< "$VERTEX_COMPOSED"

    # F-A11's born-clean scrub USED TO LIVE HERE, on a `tmux start-server` invocation, and
    # IT WAS INERT. It has MOVED to the `tmux new-session` below — the only invocation that
    # can actually taint a server. See the measured block above the SERVER_SCRUB build.
    #
    # It also only ever ran on the --vertex path, which is backwards: the MAX path is the
    # one that births a server from an unscrubbed shell. The scrub now runs on BOTH.
    #
    # (R2, Rio 2026-07-15: a DEAD `VERTEX_PANE_UNSET` derivation also lived here — computed,
    # never consumed; the live scrub is the path-dependent PANE_UNSET_LIST below. Removed.
    # A dead guard that looks alive is worse than none: the next reader trusts it.)

    cat >&2 <<BANNER

  ############################################################################
  ##  THIS SESSION IS ON GCP VERTEX — METERED, PAY-AS-YOU-GO REAL MONEY.    ##
  ##  It is NOT on the Max plan. Every token is billed to the GCP project.  ##
  ##  Spawned workers stay on MAX (Vertex vars are not -e forwarded).       ##
  ############################################################################

$VERTEX_COMPOSED

BANNER
fi

# ── Single-source fleet roster (Rick, 2026-06-11; user-level 2026-06-22) ──────
# COSA_VOICE_MANAGERS__<PROJECT> is defined ONCE, fleet-wide, in the repo-
# agnostic USER-level file ~/.claude/fleet-roster.env (the arbiter systemd
# drop-in reads the SAME file via EnvironmentFile=). It lives at user level so
# no product repo owns the fleet roster; the git-tracked versioned reference is
# src/conf/fleet-roster.env.template. set -a auto-exports the sourced keys so
# the forward loop below can ship them across the tmux boundary. A missing file
# degrades to an empty roster — same tolerate-missing contract as the drop-in's
# `EnvironmentFile=-` prefix.
# Design: src/rnd/v0.1.8/2026.06.11-fleet-roster-env-file-and-reserve-from-random.md
#         src/rnd/2026.06.22-fleet-roster-to-user-level-migration-spec.md (PIP, María)
FLEET_ROSTER_ENV="$HOME/.claude/fleet-roster.env"
if [[ -f "$FLEET_ROSTER_ENV" ]]; then
    set -a; source "$FLEET_ROSTER_ENV"; set +a
fi

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

INNER=""
# ── OSQ-6 / THE MAX-PATH LEAK — the scrub runs on EVERY path, not just --vertex ─────
#
# The scrub used to live inside the --vertex branch. That left the DEFAULT (Max) path
# completely unguarded, and it is the path that matters most:
#
#   CLAUDE_CODE_USE_VERTEX=1 tmux new-session       # server born TAINTED
#   → EVERY later session on that socket, INCLUDING MAX ONES, inherits it
#   → a plain `claude` silently lands on METERED BILLING, with no banner and no flag
#
# Verified live: a Max pane on a tainted server read CLAUDE_CODE_USE_VERTEX=1.
#
# This is the INVERSE of the hole we spent the day closing, and it is worse: the other
# one mis-billed a session that had already opted into billing. This one bills a session
# that never asked.
#
# 🔴 P0 — AND THIS SCRUB, WRITTEN UNCONDITIONALLY, ATE THE FEATURE IT PROTECTS.
#
# It used to unset PANE_UNSET_KEYS + VERTEX_SESSION_KEYS on BOTH paths. But the --vertex
# path forwards those same three keys via `tmux -e` (VERTEX_ENV_FLAGS, above) — and this
# line then made the pane's FIRST ACT to delete them. `--vertex` printed a METERED-BILLING
# banner and ran on MAX. The C1/OSQ-6 scrub and the toggle CANCELLED AT THE SEAM.
#
# It failed SAFE — no money burned. But THE BANNER LIED, AND THE BANNER IS WHAT A HUMAN
# TRUSTS. Neither fix was wrong alone; the defect lived in their COMPOSITION, which is
# exactly where nobody was looking, because both had already been marked done and green.
#
# The scrub set is now PATH-DEPENDENT and derived in Python (a BRANCH belongs where branch
# coverage exists — §5e):
#   MAX    -> MAX_PANE_UNSET_KEYS (hostile + the three toggle keys). Nothing opts you in.
#   VERTEX -> PANE_UNSET_KEYS     (hostile ONLY). The toggle keys are the FEATURE; they
#             arrive via -e, which sets the SESSION env and outranks the frozen server env.
#
#   SCRUB ALWAYS WHAT IS HOSTILE. NEVER SCRUB WHAT YOU JUST FORWARDED.
# R3 (Arnold F4, Rio 2026-07-15): this derivation used to run under 2>/dev/null — it
# failed CLOSED (set -e kills the script on a non-zero substitution) but SILENTLY: the
# operator saw a wordless death with the diagnosis eaten. The silencer is gone; a broken
# derivation now says what broke. And the pane no longer takes the scrub on faith either
# way — pane_guard (below) asserts the scrub's postcondition IN THE PANE.
PANE_UNSET_LIST="$(
    PYTHONPATH="$LUPIN_ROOT/src:${PYTHONPATH:-}" VERTEX_PATH="$VERTEX" python3 -c '
import os
from cosa.utils.vertex_env import pane_unset_keys
print( " ".join( pane_unset_keys( vertex_path=os.environ.get( "VERTEX_PATH" ) == "1" ) ) )
'
)"
if [[ -n "$PANE_UNSET_LIST" ]]; then
    INNER+="unset $PANE_UNSET_LIST; "
fi
# Forward LUPIN_ROOT + PLANNING_IS_PROMPTING_ROOT into the pane shell that launches
# `claude`. Without this the tmux session never inherits them (tmux does not carry
# arbitrary parent env), so every hook whose command is "$LUPIN_ROOT/.venv/bin/python3
# ..." OR "$PLANNING_IS_PROMPTING_ROOT/workflow/scripts/..." in ~/.claude/settings.json
# collapses to a root-anchored "/.venv/..." / "/workflow/..." path and dies "not found".
# Both are exported in ~/.bashrc but the `cctmx` alias enters this script with them set
# only in the OUTER env, and prior to this only PYTHONPATH was ever propagated inward.
# (Root-caused 2026-07-14.) Mirrors the PYTHONPATH forward directly below.
INNER+="export LUPIN_ROOT=$(printf '%q' "$LUPIN_ROOT"); "
INNER+="export PLANNING_IS_PROMPTING_ROOT=$(printf '%q' "${PLANNING_IS_PROMPTING_ROOT:-}"); "
INNER+="export PYTHONPATH=$(printf '%q' "$LUPIN_ROOT/src:${PYTHONPATH:-}"); "
if [[ -f "$VENV_ACTIVATE" ]]; then
    INNER+="source $(printf '%q' "$VENV_ACTIVATE"); "
fi
# ── C1 / §5c row 2 — THE GUARD IN THE RIGHT PROCESS, AT LAST ─────────────────────────
# pane_guard() runs HERE: inside the pane, post `-e` (the session env is already
# applied when this shell starts), post-unset, pre-`claude` — and dies NON-ZERO before
# the first token when the pane is not what its path promises. It asserts the scrub's
# postcondition (every unset key actually gone — the F4 class), and on --vertex that
# the toggle trio ARRIVED intact (the P0 as a runtime guard: the banner cannot lie
# quietly again). Every earlier revision ran these checks in the launcher's shell;
# `claude` does not run there (F-A10).
if [[ "$VERTEX" == "1" ]]; then PANE_GUARD_ARG="True"; else PANE_GUARD_ARG="False"; fi
INNER+="python3 -c 'from cosa.utils.vertex_env import pane_guard; pane_guard( vertex_path=$PANE_GUARD_ARG )' || exit 1; "
INNER+="$CLAUDE_CMD"

# Per-project persona CHAINS. Forwarded into the tmux session via -e so the
# SessionStart hook (register_session.py) sees them regardless of the tmux
# server's frozen env or whether ~/.bashrc was sourced. The hook reads only the
# key matching detect_project(), so unused keys are inert.
# Chain syntax (2026-06-11, Rick): ordered comma-separated names; `*` means
# "then take anything free"; no `*` = strict, loud fail on exhaustion.
PERSONA_ENV_FLAGS=(
    -e "COSA_VOICE_PREFERRED_PERSONA__LUPIN=Mr. Radio,Cheech,*"
    -e "COSA_VOICE_PREFERRED_PERSONA__LUPIN_MOBILE=Tiffany,*"
    -e "COSA_VOICE_PREFERRED_PERSONA__PLAN=María,*"
    -e "COSA_VOICE_PREFERRED_PERSONA__SKILLS_DISTILLATION=Sam,*"
    # Disable Claude Code's terminal mouse capture inside tmux panes (Rick,
    # 2026-06-26). Forwarded via -e so it crosses the tmux boundary regardless of
    # the tmux server's frozen env (a bare parent export would NOT reach `claude`).
    # Static always-on for every session this script launches (interactive +
    # headless/spawned).
    -e "CLAUDE_CODE_DISABLE_MOUSE=1"
    # This switches Claude Code back to the "classic" inline renderer, which keeps the conversation in your terminal's
    # native scrollback buffer instead of the alternate screen. That restores normal scroll-back, Cmd+F search, and
    # tmux copy-mode over the session output. The full-screen behavior you're fighting is the newer default renderer
    # (CLAUDE_CODE_NO_FLICKER=1 is the inverse toggle that force-enables it).
    -e "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1"
    # Bound EVERY MCP tool call end-to-end (wedge fix f1a21917 lever (i-a), Rick-
    # ratified 2026-07-06). Claude Code honors MCP_TOOL_TIMEOUT (milliseconds) as
    # an upper bound on MCP tool-call execution, so a stalled MCP server response
    # leg becomes a bounded, recoverable tool-error instead of an open-turn wedge
    # (incident 25c7441c: a fire-and-forget cosa-voice notify() held a turn 54m47s
    # until process death). 660_000 ms (11 min) sits ABOVE the 600s converse/ask_*
    # blocking-ask ceiling (so a legitimate wait is never severed) and an order of
    # magnitude BELOW the observed 55-min wedge. Static always-on + forwarded via
    # -e for the SAME reason as the mouse flag — it must cross the tmux boundary to
    # reach `claude`; session_spawner.py's --headless spawns run through this script
    # too, so both interactive and spawned sessions inherit the bound.
    # HONOR-CHECK VERIFIED (CC v2.1.199, 2026-07-03 ~07:04Z): a hang(120) MCP tool
    # under MCP_TOOL_TIMEOUT=15000 aborted at exactly 15s and the turn recovered.
    # Caveats: already-live sessions won't have it (coverage arrives as sessions
    # cycle — no forced respawn); bare terminals not launched via this script are
    # out of scope. Design + receipt: src/rnd/v0.1.9/2026.07.03-notify-turn-hold-fix-design.md §2(i-a)
    -e "MCP_TOOL_TIMEOUT=660000"
)

# Forward manager-spawn lineage env (set by session_spawner on the spawning
# process) INTO the tmux session via -e. tmux does not inherit arbitrary parent
# env for a new session, so without this the child's SessionStart hook never
# sees COSA_VOICE_SPAWNED_BY/HEADLESS/ROLE and can't self-tag / start
# speakerphone-off. (Caught by the live spawn E2E 2026-05-28.)
# COSA_VOICE_PERSONA_CHAIN carries a manager's spawn persona_preference;
# it must cross the tmux boundary here or the spawner's injection is lost
# (the original transport bug, one layer down — 2026-06-11).
for _v in COSA_VOICE_SPAWNED_BY COSA_VOICE_HEADLESS COSA_VOICE_ROLE COSA_VOICE_PERSONA_CHAIN; do
    if [[ -n "${!_v:-}" ]]; then
        PERSONA_ENV_FLAGS+=( -e "$_v=${!_v}" )
    fi
done

# Forward the declared-manager roster (sourced from fleet-roster.env above)
# across the same tmux boundary. Generic glob so a future
# COSA_VOICE_MANAGERS__<OTHER_PROJECT> roster line needs zero script edits.
# The SessionStart hook reads only the key matching detect_project() and
# threads it to the allocate endpoint as `declared_managers` (reserve-from-
# random: declared names skip random + chain-`*` allocation).
for _v in $( compgen -A variable | grep '^COSA_VOICE_MANAGERS__' || true ); do
    if [[ -n "${!_v:-}" ]]; then
        PERSONA_ENV_FLAGS+=( -e "$_v=${!_v}" )
    fi
done

# Forward the subagent-governance runtime flag across the tmux boundary so the
# manager-spawn governance hook (subagent_governance.py, default-OFF behind
# LUPIN_SUBAGENT_GOVERNANCE) actually sees it. tmux does not inherit arbitrary
# parent env, so a bare `export LUPIN_SUBAGENT_GOVERNANCE=1` never reaches the
# hook without this forward (activation 0dcf3a10, 2026-06-23). Runtime-flag
# design preserved: unset/empty → hook stays default-OFF; Rick toggles it via
# his shell export.
if [[ -n "${LUPIN_SUBAGENT_GOVERNANCE:-}" ]]; then
    PERSONA_ENV_FLAGS+=( -e "LUPIN_SUBAGENT_GOVERNANCE=${LUPIN_SUBAGENT_GOVERNANCE}" )
fi

# ── Dry-run: print what would happen and exit (no tmux side effects) ──────────
# Sits AFTER the env-flag assembly (moved 2026-06-11) so the PERSONA-ENV line
# shows the REAL forwarded flags — the fleet-roster unit test asserts the
# sourced COSA_VOICE_MANAGERS__* roster survives to the tmux boundary.
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN headless=$HEADLESS vertex=$VERTEX session='$SESSION_NAME'"
    printf 'PERSONA-ENV:'; printf ' %q' "${PERSONA_ENV_FLAGS[@]}"; printf '\n'
    # AC-D1 asserts on this line. It MUST show the real forwarded flags: a --dry-run
    # that omits what would actually be exported is a test oracle that cannot fail.
    if [[ "$VERTEX" -eq 1 ]]; then
        printf 'VERTEX-ENV:'; printf ' %q' "${VERTEX_ENV_FLAGS[@]}"; printf '\n'
    fi
    echo "tmux new-session -d -s '$SESSION_NAME' <persona-env> <vertex-env> \"$INNER\""
    exit 0
fi

# ── F-A11 (REBUILT 2026-07-14) — NEVER BE THE PROCESS THAT BIRTHS A TAINTED SERVER ──────
#
# 🔴 THE OLD GUARD WAS INERT, AND IT WAS INERT IN THE ONE WAY NOTHING CATCHES: it produced
# the right answer for a reason that had nothing to do with the guard.
#
# It scrubbed `tmux start-server`. MEASURED ON tmux 3.2a, ISOLATED SOCKETS:
#
#   A  TAINT=1 tmux start-server   -> a later pane reads TAINT=<unset>   (server NOT tainted)
#   C  TAINT=1 env -u TAINT tmux start-server  -> pane reads <unset>     (server NOT tainted)
#   B  TAINT=1 tmux new-session    -> a later pane reads TAINT=1         (SERVER TAINTED)
#
#   ## A AND C ARE IDENTICAL. THE SCRUB CHANGED NOTHING — IT COULD NOT HAVE COME OUT
#   ## OTHERWISE. `start-server` NEVER PROPAGATES THE CALLER'S ENV. IT WAS DECORATION.
#
# `new-session` is the ONLY invocation that freezes the caller's env into the server, and it
# does so IFF it CREATES the server. And the launcher ran it UNSCRUBBED — so the script whose
# header says "never be the process that births the server" WAS THAT PROCESS. Worse, the old
# scrub only ran under --vertex, while the MAX path — the one launched from whatever shell
# Rick happens to be in, possibly a Vertex one — birthed the server with no guard at all.
# A MAX pane protects ITSELF via the INNER unset; it does nothing for the NEXT session on
# that socket, which inherits the frozen env and is billed for a toggle it never asked for.
#
# So the scrub now rides the invocation that can actually taint, on BOTH paths. The three
# toggle keys are scrubbed from the SERVER-BIRTH env even under --vertex — they are NOT lost,
# because `-e` sets the SESSION environment, which outranks the frozen server env. We forward
# them to the session; we refuse to freeze them into the server. Both halves of the rule:
#
#   SCRUB ALWAYS WHAT IS HOSTILE. NEVER SCRUB WHAT YOU JUST FORWARDED.
#
# DERIVE, DON'T RESTATE (FLAG D): the key list is imported, never spelled out here. A restated
# list falls silently behind its source while the suite stays green testing the source.
SERVER_SCRUB=( env )
while IFS= read -r key; do
    [[ -n "$key" ]] && SERVER_SCRUB+=( -u "$key" )
done < <(
    PYTHONPATH="$LUPIN_ROOT/src:${PYTHONPATH:-}" python3 -c '
from cosa.utils.vertex_env import MAX_PANE_UNSET_KEYS
print( "\n".join( MAX_PANE_UNSET_KEYS ) )
'
)

# ── OSQ-6, THE EXISTING-SERVER HALF (C1's close) ─────────────────────────────────────
# "Assert the tmux server env is Vertex-free — and, if NO server exists, that the one
# we create is BORN CLEAN." SERVER_SCRUB below is the born-clean half. THIS is the
# other half: if a server is already alive on this socket, its FROZEN env is what every
# pane — this one and every later one — inherits, and the launcher shell's own guards
# never saw it (a guard that fires in the wrong process is not a guard, F-A10). Read
# the server's global env and REFUSE, naming every offender, if it carries the toggle
# or hostile set. BLAST RADIUS (deliberate, stated in the error too): while the server
# is tainted, EVERY launch on this socket refuses until it is cleansed surgically
# (`tmux set-environment -g -u <KEY>` — never a server kill).
#
# `show-environment -g` failing means NO REACHABLE SERVER (it cannot enumerate what
# does not exist) — that is NOT read as "clean"; it routes to the born-clean path,
# where SERVER_SCRUB guards the birth. The failure is SAID, not swallowed (R3's rule).
if TMUX_GLOBAL_ENV="$( tmux show-environment -g 2>/dev/null )"; then
    printf '%s\n' "$TMUX_GLOBAL_ENV" | PYTHONPATH="$LUPIN_ROOT/src:${PYTHONPATH:-}" python3 -c '
import sys
from cosa.utils.vertex_env import VertexEnvError, assert_server_env_is_vertex_free, parse_tmux_global_env
try:
    assert_server_env_is_vertex_free( parse_tmux_global_env( sys.stdin.read() ) )
except VertexEnvError as error:
    sys.stderr.write( f"\n[OSQ-6] REFUSING TO LAUNCH: {error}\n\n" )
    sys.exit( 1 )
' || exit 1
else
    echo "No existing tmux server on this socket — the session below births it under SERVER_SCRUB (born clean)." >&2
fi

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
    # VERTEX_ENV_FLAGS is empty unless --vertex was passed, so the default Max path
    # forwards nothing — but it is NO LONGER unscrubbed. If this invocation CREATES the
    # server, SERVER_SCRUB is what stops it freezing a Vertex-tainted shell into an env
    # that every later session on this socket would inherit (F-A11, rebuilt above).
    "${SERVER_SCRUB[@]}" tmux new-session -s "$SESSION_NAME" "${PERSONA_ENV_FLAGS[@]}" "${VERTEX_ENV_FLAGS[@]}" -d "$INNER"
    if [[ "$HEADLESS" -eq 1 ]]; then
        # Headless: do NOT attach. Emit the session name for the caller to capture.
        echo "$SESSION_NAME"
    else
        tmux attach -t "$SESSION_NAME"
    fi
fi
