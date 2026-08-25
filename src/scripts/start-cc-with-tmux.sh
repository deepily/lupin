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
        # WORK-AXIS directory (row 697a85fe). The child's cwd, and therefore the
        # CLAUDE.md and git identity it picks up. DELIBERATELY SEPARATE from
        # LUPIN_ROOT below, which stays the PLATFORM axis — venv, PYTHONPATH and
        # hook binaries always come from lupin so the child can DM, set a topic and
        # be reaped. Measured: planning-is-prompting/.venv cannot import fastmcp, so
        # a child booted on the work repo's venv would be unreachable. Omit and the
        # child inherits the caller's cwd, which is the prior behaviour.
        --work-dir ) WORK_DIR="${2:-}"; shift 2 ;;
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
# ── Forward LUPIN_DEV_EMAIL (+ HOOK_TTS_ENABLED when set) — bug ef10c5b6 ───────
# The SessionStart hello-world notification is a fresh session's ONLY birth
# certificate on the operator's focus bar, and send_tts() no-ops SILENTLY when
# get_target_email() cannot resolve a target. A tmux-server restart froze a
# non-login global env with NO LUPIN_DEV_EMAIL, so every new session went
# invisible until it happened to push an MCP notification (server-side creds,
# env-independent). Forwarding the launcher's own value per-pane makes the
# launcher shell (Rick's login env, via the `cctmx` alias) the source of truth,
# so a server restart can never again silence registration — RESTART-PROOF where
# the `tmux set-environment -g` seed mitigation dies with the server.
# GUARDED (mirrors the COSA_VOICE_SPAWNED_BY forward below): export ONLY when the
# launcher actually carries the var non-empty. An unconditional export of an
# empty value would CLOBBER a good value the pane would otherwise inherit from
# the server's frozen global env (e.g. the set-environment -g seed), and would
# also override a deliberate per-session HOOK_TTS_ENABLED=false disable. When the
# launcher lacks it too, the hook's ~/.lupin/config file fallback is the final
# backstop (defense-in-depth, same bug).
if [[ -n "${LUPIN_DEV_EMAIL:-}" ]]; then
    INNER+="export LUPIN_DEV_EMAIL=$(printf '%q' "$LUPIN_DEV_EMAIL"); "
fi
if [[ -n "${HOOK_TTS_ENABLED:-}" ]]; then
    INNER+="export HOOK_TTS_ENABLED=$(printf '%q' "$HOOK_TTS_ENABLED"); "
fi
# ── Forward LUPIN_CONFIG_MGR_CLI_ARGS — third sibling of the 2026-07-14 boundary bug ──
# ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) reads this var for
# its config_path/splainer_path/config_block_id. It is exported in ~/.bashrc, but the
# pane shell is non-login (the .bashrc interactive guard returns before reaching it) and
# the tmux server carries no arbitrary parent env — so without this forward the var never
# reaches `claude`, never reaches the hooks, and never reaches the CC notification
# listener spawned by register_session._spawn_listener_locked (which does env.copy() and
# so faithfully inherits the gap).
#
# Symptom when missing: _send_gist_response()'s `Gister()` construction raises
# "[LUPIN_CONFIG_MGR_CLI_ARGS] is NOT set", the except swallows it, and the gist degrades
# to `" ".join( text.split()[:5] )` — a 5-word prefix that reads like a truncated gist,
# not like a failure. Cost: 526 consecutive fallback receipts between 2026-07-14 23:49
# and 2026-07-27, with the Phi-4 gist model (svllmc, :3001) never once contacted — which
# is why no 404s ever appeared in the vLLM log to give the game away.
#
# Same tmux-server-restart event, same frozen non-login env, same day as the LUPIN_ROOT
# and LUPIN_DEV_EMAIL forwards above. Those two were noticed because they failed loudly;
# this one was not. GUARDED for the same clobber reason documented above.
if [[ -n "${LUPIN_CONFIG_MGR_CLI_ARGS:-}" ]]; then
    INNER+="export LUPIN_CONFIG_MGR_CLI_ARGS=$(printf '%q' "$LUPIN_CONFIG_MGR_CLI_ARGS"); "
fi
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
# ── Per-session memory ceiling — OOM incident 2026-08-22 (P0) ─────────────────
# A single `node` reached ~229 GB RSS and the kernel OOM-killed it under
# CONSTRAINT_NONE/global_oom. Because ~2 dozen sessions share ONE
# tmux-server.service slice, one runaway is a whole-host event — and the kernel
# picks by oom_score, so an INNOCENT session can be the victim. A transient
# scope in its OWN slice makes the kill single-session.
#
# WHY A CGROUP AND NOT A NODE FLAG. There is no Node flag that bounds external
# memory. --max-old-space-size bounds only V8 generations (default 4G on a
# >=16G host) and blowing THAT aborts gracefully with "JavaScript heap out of
# memory" — not a 229 GB SIGKILL. The blowup lives in Buffer/ArrayBuffer, which
# nodejs/node#24225 has wanted a bound for since 2018 and still has none.
# An OS/cgroup ceiling is the only thing that actually works.
#
# WHY --scope AND NOT --unit. `systemd-run --scope` EXECs the command, so the
# pane's process is still `claude` itself: TTY untouched, and anything that
# resolves a session by pane pid (listener status, context-pressure) is
# unaffected. Verified here: pane_pid WAS the target process, no extra layer.
#
# MemorySwapMax=0 is what makes the cap REAL — MemoryMax alone lets the cgroup
# swap past it. Measured 2026-08-22: MemoryMax=64M against a 512 MB allocator
# RAN TO COMPLETION, because with memory.swap.max unset the cgroup reclaims by
# swapping rather than killing; adding MemorySwapMax=0 produced rc 137 and
# oom_kill 1 in the scope's own memory.events. The swap bound is not a
# refinement of the cap, it is the half that makes it bind.
#
# WHY 8G AND NOT 24G — Rick ruled it 2026-08-25, and the arithmetic is the
# reason. A per-session ceiling bounds one SESSION at any value; it bounds the
# MACHINE only if ceiling x concurrency stays under RAM. Against the ~24
# sessions live on the OOM day, on a 251 GiB box:
#     4G  x24 =  96 GB   safe, but only ~5x the observed peak
#     8G  x24 = 192 GB   fits, ~10x observed          <- this
#     16G x24 = 384 GB   EXCEEDS the box
#     24G x24 = 576 GB   over twice the box
# So 16G and 24G do not protect the box at all: they stop ONE runaway while
# several at once still take the machine down. Measured cost of 8G: across
# 26,797 samples over 69 sessions the worst single Claude Code process was
# 0.78 GB and the median 0.61, so 8G is ~10x anything real — while the 229 GB
# runaway that started this is ~29x ABOVE the ceiling, so it dies early with
# the transcript still readable.
#
# 🔴 NO MemoryHigh — DELIBERATE, DO NOT ADD IT BACK. A soft limit throttles and
# reclaims instead of killing, which manufactures exactly the sustained reclaim
# pressure systemd-oomd's PSI criterion selects victims on. It can therefore
# help CAUSE the kill it was meant to soften, and oomd picks by pressure rather
# than by fault — so the session it takes need not be the one at fault. The
# capped JS-test lane reached this conclusion independently and pins it in a
# test (src/tests/unit/test_jstest_lane.py, "a future edit helpfully adding
# MemoryHigh must go red"); this launcher is now consistent with it. What was
# here before: MemoryHigh=18G under MemoryMax=24G.
#
# Design: src/rnd/v0.2.0/2026.08.22-oom-incident-what-we-know-response.md
CC_MEM_LIMIT="${CC_MEM_LIMIT:-8G}"
if [[ "$CC_MEM_LIMIT" != "off" ]] \
   && command -v systemd-run >/dev/null 2>&1 \
   && [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    # '-' is systemd's slice-HIERARCHY separator, so the leaf is sanitized to
    # [A-Za-z0-9_] and every worker hangs off one implicit ccworker.slice
    # parent — which a single drop-in can later cap fleet-wide.
    _cc_slice="ccworker-$( printf '%s' "$SESSION_NAME" | tr -c 'a-zA-Z0-9' '_' ).slice"
    # Prefer a worker over tmux-server/orchestrator when the kernel must choose.
    # oom_score_adj is inherited across both execs below. Raising is
    # unprivileged; lowering is not. Scopes take no OOMScoreAdjust= property
    # (systemd execs nothing for a scope), so this is set in the pane shell.
    INNER+="echo 500 > /proc/self/oom_score_adj 2>/dev/null; "
    INNER+="systemd-run --user --scope --quiet --collect"
    INNER+=" -p MemoryAccounting=yes"
    INNER+=" -p MemoryMax=$(printf '%q' "$CC_MEM_LIMIT")"
    INNER+=" -p MemorySwapMax=0"
    INNER+=" --slice=$(printf '%q' "$_cc_slice") -- "
fi
INNER+="$CLAUDE_CMD"

# Per-project persona CHAINS — DERIVED from the fleet roster, never typed twice
# (row a1a84682, 2026-08-18). Forwarded into the tmux session via -e so the
# SessionStart hook (register_session.py) sees them regardless of the tmux
# server's frozen env or whether ~/.bashrc was sourced. The hook reads only the
# key matching detect_project(), so unused keys are inert.
# Chain syntax (2026-06-11, Rick): ordered comma-separated names; `*` means
# "then take anything free"; no `*` = strict, loud fail on exhaustion.
#
# WHY DERIVED. These four lines used to be hardcoded literals, and the roster
# they were supposed to mirror lives in ~/.claude/fleet-roster.env. Two places
# answered "who is a manager for this repo", different consumers read each
# (roster → arbiter status + escalation + reserve-from-random; chain →
# manager_figure, which gates task-store WRITES fail-closed), and nothing
# compared them. They drifted to "Mr. Radio, Tiberius" vs "Mr. Radio,Cheech,*"
# and it surfaced only when a human read a retired name off a status card.
# Now the roster is the ONE source and the chain is `<roster>,*`: a repo gains
# or loses a manager by editing ONE line in ONE file. A project with no roster
# line gets no chain (random allocation) — declare it in the roster to give it
# one. register_session's roster-drift check is the belt for the paths this
# derivation does not own (hand-exported chains, bare terminals).
PERSONA_ENV_FLAGS=()
for _v in $( compgen -A variable | grep '^COSA_VOICE_MANAGERS__' || true ); do
    if [[ -n "${!_v:-}" ]]; then
        PERSONA_ENV_FLAGS+=( -e "COSA_VOICE_PREFERRED_PERSONA__${_v#COSA_VOICE_MANAGERS__}=${!_v},*" )
    fi
done
PERSONA_ENV_FLAGS+=(
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

    # ── Brief-length probe (dry_run ONLY) — row 9c5dccd4 ─────────────────────────
    # A brief too large for tmux's command-length limit makes the REAL
    # `tmux new-session` at the bottom of this script die "command too long". The
    # live path now surfaces that verbatim (the spawner reads the failed child's
    # stderr into `reason`), but dry_run EXITS HERE, above that call — so without
    # this probe an oversized brief dry-runs clean and lies about a spawn that
    # would fail.
    #
    # Probe the box's OWN tmux at RUNTIME — never a baked constant, which would be
    # wrong on a box with a different tmux build or env size and fail in the
    # direction that looks fine. Fire the same invocation shape (the forwarded -e
    # flags + a payload of the assembled command's exact byte length) as a no-op
    # into a uniquely-named throwaway session, then kill it. The tmux that judges
    # here is the one that runs the real spawn.
    _probe_session="__lenprobe_$$_${SECONDS}_${RANDOM}"
    _inner_bytes=$( printf '%s' "$INNER" | wc -c )
    # tmux's "command too long" limit is on the WHOLE assembled command, not the
    # payload arg alone (measured on tmux 3.2a: a session name 200 bytes longer
    # lowered the max accepted payload by EXACTLY 200 bytes — row 0ab3c0cd F2).
    # The real spawn (bottom of this script) differs from this probe by three
    # things, and the session NAME is the only one that changes tmux's byte count:
    #   - SERVER_SCRUB (`env -u …`) prefixes the real spawn but is consumed by env,
    #     NOT part of tmux's argv, so it does not count toward the limit;
    #   - the `-d` flag sits in a different position but the token multiset is
    #     identical, so total bytes are unchanged;
    #   - PERSONA/VERTEX -e flags are the same arrays at the same eval point.
    # So byte-match the probe's TOTAL argv to the real spawn by folding the
    # name-length delta into the payload. ':' + (len-1) spaces = a no-op command
    # tmux parses in full.
    _name_delta=$(( ${#SESSION_NAME} - ${#_probe_session} ))
    _probe_payload_len=$(( _inner_bytes + _name_delta ))
    # Clamp: only reachable far below the limit (tiny brief + long throwaway name),
    # where the exact payload size is immaterial to the verdict.
    if (( _probe_payload_len < 1 )); then _probe_payload_len=1; fi
    _probe_payload=":$( printf '%*s' "$(( _probe_payload_len - 1 ))" '' )"
    if _probe_err=$( tmux new-session -d -s "$_probe_session" \
                        "${PERSONA_ENV_FLAGS[@]}" "${VERTEX_ENV_FLAGS[@]}" \
                        "$_probe_payload" 2>&1 ); then
        # Best-effort cleanup: the no-op payload usually self-exits and the
        # session is already gone, so a failed kill is expected — never let it
        # trip `set -e`.
        tmux kill-session -t "$_probe_session" 2>/dev/null || true
        echo "BRIEF-LENGTH-PROBE: ok — assembled command is $_inner_bytes bytes; this box's tmux accepts it."
        exit 0
    elif printf '%s' "$_probe_err" | grep -qi 'command too long'; then
        # The decisive verdict: this brief WILL blow the live spawn. Fail loud,
        # early, with the measured byte count — never a quiet dry_run pass.
        echo "BRIEF-LENGTH-PROBE: FAIL — assembled command is $_inner_bytes bytes; this box's tmux rejects it as 'command too long'. The live spawn WILL fail; trim the brief/memento." >&2
        exit 1
    else
        # Cannot probe (no tmux, or a non-length error). Per Cheech: dry_run SAYS
        # it could not verify rather than passing quietly.
        echo "BRIEF-LENGTH-PROBE: could NOT verify brief length — the probe tmux call errored for another reason: $_probe_err" >&2
        exit 1
    fi
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
    # -c sets the WORK axis (row 697a85fe): the child's cwd, hence its CLAUDE.md
    # and git identity. Empty WORK_DIR ⇒ no -c ⇒ inherit the caller's cwd, exactly
    # as before. The PLATFORM axis is untouched — $INNER still sources lupin's venv
    # and exports lupin's PYTHONPATH regardless of where the pane starts.
    TMUX_WORKDIR_FLAGS=()
    if [[ -n "${WORK_DIR:-}" ]]; then
        if [[ ! -d "$WORK_DIR" ]]; then
            echo "REFUSING TO LAUNCH: --work-dir '$WORK_DIR' is not a directory" >&2
            exit 1
        fi
        TMUX_WORKDIR_FLAGS=( -c "$WORK_DIR" )
    fi
    "${SERVER_SCRUB[@]}" tmux new-session -s "$SESSION_NAME" "${PERSONA_ENV_FLAGS[@]}" "${VERTEX_ENV_FLAGS[@]}" "${TMUX_WORKDIR_FLAGS[@]}" -d "$INNER"
    if [[ "$HEADLESS" -eq 1 ]]; then
        # Headless: do NOT attach. Emit the session name for the caller to capture.
        echo "$SESSION_NAME"
    else
        tmux attach -t "$SESSION_NAME"
    fi
fi
