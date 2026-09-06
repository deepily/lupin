#!/usr/bin/env bash
# orphan-sweep-tick.sh — the DELIVERING half of the orphaned-head sweep.
#
# Rick ruled OPTION B by real keypress, 2026-09-06 ~16:10 EDT. Spec:
# src/rnd/2026.09.06-scheduling-the-orphan-sweep-rick-decision.md
#
#     0,15 10-12 * * *  /mnt/.../lupin/src/scripts/orphan-sweep-tick.sh >> <log> 2>&1
#
# === WHAT IT DELIVERS, AND WHAT IT DELIBERATELY DOES NOT ===
#
# It runs planning-is-prompting's `orphaned_head_sweep.py` — the SAME script session-end
# invokes; no second implementation — and pushes CATEGORY (i) ONLY.
#
#   (i)  UNREACHABLE  no branch contains the commit. gc takes it when the worktree goes.
#                     -> DELIVERED. Zero false-positive cost, failure mode is permanent
#                        loss, and it was 0 of 98 when this shipped. An alarm that almost
#                        never fires is exactly the kind worth having.
#
#   (ii) ABANDONED    ahead of the line, no live seat behind it.
#                     -> PRINTED, NEVER PUSHED. Maria ruled this 2026-09-05 and she built
#                        the alert version first, measured it, and killed it: 23 of 31
#                        branches fired, "a wall of corpses, and a wall trains its reader
#                        to stop looking." It was 70 branches when this shipped. Pushing
#                        it would reverse a ruling made with numbers.
#
# 🔴 IF YOU ARE HERE TO "FINISH THE JOB" BY DELIVERING (ii) TOO: don't. That is the
# refused design, not an oversight. Re-read her docstring in orphaned_head_sweep.py.
#
# === WHY A TICK IN LUPIN RATHER THAN A FIX TO session-end.md ===
#
# The sweep never fires here for TWO INDEPENDENT causes, either sufficient alone:
#   1. it is tied to a ritual, not a scheduler  -> this file closes that
#   2. session-end resolves it at $repo_root/workflow/scripts/, and lupin has no
#      workflow/ directory, so the ritual takes a silent skip branch
# This closes (1) and ROUTES AROUND (2) by resolving the script explicitly. It does NOT
# fix (2) for the session-end path — that edit lives in the planning-is-prompting repo
# and is tracked separately. A seat ending its session in lupin still gets the skip.
#
# === EXIT CODES — two failure modes wanting opposite remedies never share one ===
#   0  swept, nothing in category (i)
#   1  category (i) found AND delivered
#   2  could not look: sweep unresolvable, or it reported a category it could not compute
#   3  category (i) found and DELIVERY FAILED — detection worked, the alarm did not arrive
set -uo pipefail

export LUPIN_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"
export API_BASE="${ORPHAN_TICK_API_BASE:-http://localhost:7999}"
TARGET_BRANCH="${CONTEXT_TICK_TARGET_BRANCH:-wip-v0.2.1-2026.08.29-cjflow-v2-followup}"

# Resolve the sweep. NAMED explicitly rather than derived from $repo_root — that
# derivation is cause 2 above, and inheriting it here would reproduce the silent skip.
PIP_ROOT="${PLANNING_IS_PROMPTING_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting}"
SWEEP="$PIP_ROOT/workflow/scripts/orphaned_head_sweep.py"
PY="$LUPIN_ROOT/.venv/bin/python"; [ -x "$PY" ] || PY="$( command -v python3 )"

# REFUSE rather than no-op. A tick that cannot find its sweep must not exit 0 —
# "nothing to report" and "I could not look" are different facts (lupin CLAUDE.md).
if [ ! -f "$SWEEP" ]; then
    echo "orphan-sweep-tick: REFUSING — no sweep at $SWEEP. Nothing was scanned."
    exit 2
fi
if [ ! -x "$PY" ] && [ -z "$PY" ]; then
    echo "orphan-sweep-tick: REFUSING — no interpreter. Nothing was scanned."
    exit 2
fi

echo "orphan-sweep-tick $( date '+%Y-%m-%d %H:%M:%S %Z' ) — repo=$LUPIN_ROOT target=$TARGET_BRANCH"
REPORT="$( "$PY" "$SWEEP" "$LUPIN_ROOT" "$TARGET_BRANCH" 2>&1 )"; SWEEP_RC=$?
echo "$REPORT"
echo "-- sweep exit: $SWEEP_RC --"

# Category (i) is the delivered one. The sweep prints "CLEAN — 0 of N" when it is empty;
# anything else in that block is a finding. Parsed from the report rather than re-derived,
# so this file and the sweep can never disagree about what category (i) means.
CAT_I="$( printf '%s\n' "$REPORT" | sed -n '/(i) UNREACHABLE/,/(ii)/p' )"
if printf '%s\n' "$CAT_I" | grep -q "CLEAN —"; then
    echo "category (i): clean — nothing to deliver"
    [ "$SWEEP_RC" -eq 2 ] && { echo "…but the sweep reported a category it could NOT compute"; exit 2; }
    exit 0
fi
if [ "$SWEEP_RC" -eq 2 ]; then
    echo "orphan-sweep-tick: the sweep could not compute a category — not treating this as clean"
    exit 2
fi

echo "🔴 category (i) UNREACHABLE — delivering"
DELIVERY="$( LUPIN_ROOT="$LUPIN_ROOT" API_BASE="$API_BASE" CAT_I="$CAT_I" "$PY" - <<'PY'
import os, sys, urllib.parse, urllib.request

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )
from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key

API_BASE = os.environ[ "API_BASE" ]
API_KEY  = read_api_key()
body     = os.environ[ "CAT_I" ].strip()

def target():
    """No recipient is a DELIVERY FAILURE, never a silent skip."""
    t = os.getenv( "LUPIN_DEV_EMAIL" )
    if t: return t
    try:
        from cosa.utils.config_loader import get_api_config
        return get_api_config( os.getenv( "LUPIN_ENV", "local" ) ).get( "global_notification_recipient" )
    except Exception:
        return None

who = target()
if not who:
    print( "DELIVERY FAILED — no notification recipient configured" ); sys.exit( 1 )

params = {
    "message" : "Orphaned commits found: work whose only anchor is a worktree. "
                "One ordinary cleanup command from being lost.",
    "abstract": "🔴 ORPHANED-HEAD SWEEP — category (i) UNREACHABLE\n\n"
                "These commits are reachable from NO branch. `git worktree remove` or a "
                "prune collects them, and nothing warns whoever types it.\n\n"
                f"```\n{body}\n```\n\n"
                "The report prints the `git branch` command that rescues each one. "
                "A rescue stops the LOSS; it does not deliver the work.",
    "type"    : "custom",
    "priority": "urgent",
    "target_user": who,
}
req = urllib.request.Request( f"{API_BASE}/api/notify?{urllib.parse.urlencode( params )}",
                              data=b"", headers={ "X-API-Key": API_KEY }, method="POST" )
try:
    with urllib.request.urlopen( req, timeout=30 ) as r:
        print( f"notify to {who}: HTTP {r.status}" )
        sys.exit( 0 if r.status == 200 else 1 )
except Exception as e:
    print( f"DELIVERY FAILED — notify to {who}: {e}" ); sys.exit( 1 )
PY
)"; DELIVERY_RC=$?
echo "$DELIVERY"
[ "$DELIVERY_RC" -ne 0 ] && { echo "orphan-sweep-tick: detection succeeded, DELIVERY FAILED"; exit 3; }
exit 1
