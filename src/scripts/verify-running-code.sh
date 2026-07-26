#!/usr/bin/env bash
# verify-running-code.sh — does the RUNNING PROCESS have this commit? (row ce89669e)
#
# THE FALSE GREEN THIS EXISTS TO KILL
# ----------------------------------
# `:8000` (lupin-rest-test) bind-mounts ./src, so editing a source file on the host
# changes the file inside the container IMMEDIATELY. But it runs `reload=False` by
# design — snapshot isolation, so a scheduled run cannot shift underneath itself.
# The module was imported at process start and stays imported.
#
#   ⇒ The file is new. The process is old. And the obvious check reads the FILE.
#
# Measured 2026-07-26 verifying commit 69295c25:
#   docker exec lupin-rest-test grep -c <symbol> /var/lupin/src/.../job.py  ->  3
#   container started 13:44 UTC · fix committed 16:29 UTC
#   Three hits. Zero of them running.
#
# ⚠️ AND `git` INSIDE THE CONTAINER LIES THE SAME WAY. Measured the same day:
#   docker exec lupin-rest-test git rev-parse --short HEAD  ->  95f357e6
#   that commit authored 17:20 EDT · container started 12:57 EDT
# The repo is bind-mounted too, so HEAD tracks the HOST's working tree, not the
# code the process loaded. Asking git in the container is the grep with extra steps.
#
# THE ONLY HONEST QUESTION is a comparison of two clocks:
#   when did this process start, vs when was that commit made?
# If the commit is newer, the running process does not have it, whatever any file
# or any `git` inside the container says.
#
# ⚠️ A RECREATE IS THE ONLY FIX. `docker restart` does not re-import a loaded module
# and does not pick up new mounts. Use `docker rm -f` + `docker compose up -d` — and
# note the destructive half succeeds before the constructive half is known to work
# (compose interpolates LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* from a shell that a
# non-interactive invocation never sourced). Export those first.
#
# USAGE
#   verify-running-code.sh <container> [commit-ish]     # default commit-ish: HEAD
#   verify-running-code.sh lupin-rest-test 69295c25
#
# EXIT CODES — deliberately distinct, because "no" and "cannot tell" have different
# remedies and collapsing them is the same class of defect this script exists for.
#   0  the running process HAS the commit
#   1  the running process does NOT have it  (recreate required)
#   2  cannot determine                      (container down, bad ref, unparseable)
set -uo pipefail

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

CONTAINER="${1:-}"
COMMITISH="${2:-HEAD}"

if [ -z "$CONTAINER" ]; then
    printf '%s\n' "usage: verify-running-code.sh <container> [commit-ish]" >&2
    exit 2
fi

# --- clock 1: when did the PROCESS start? -------------------------------------
# INJECTABLE SEAM. The comparison is the whole decision, and it must be testable
# without a live container — otherwise the only suite that can exercise this script
# is one that needs :8000 up, which is the venue this script exists to be careful
# about. Same shape as the arbiter's hold_roots_fn / scan_fn injection.
started_at="${VERIFY_RUNNING_CODE_STARTED_AT:-}"
if [ -z "$started_at" ]; then
    started_at="$( docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null )"
fi
if [ -z "$started_at" ]; then
    printf '%sCANNOT DETERMINE%s  container %s is not running (or does not exist)\n' \
           "$YELLOW" "$NC" "$CONTAINER" >&2
    printf '  a container that is down has no running code to verify; start it, then re-run\n' >&2
    exit 2
fi

# --- clock 2: when was the COMMIT made? ---------------------------------------
# Author date, not committer date: a rebase rewrites committer date and would make
# an old commit look new, failing CLOSED (reporting "not present" when it is). That
# is the safe direction, but it is noise, and author date is the honest answer.
commit_time="$( git log -1 --format=%aI "$COMMITISH" 2>/dev/null )"
if [ -z "$commit_time" ]; then
    printf '%sCANNOT DETERMINE%s  %s is not a commit this repo knows\n' \
           "$YELLOW" "$NC" "$COMMITISH" >&2
    exit 2
fi
commit_sha="$( git log -1 --format=%h "$COMMITISH" 2>/dev/null )"

# --- compare ------------------------------------------------------------------
verdict="$( python3 -c "
import sys
from datetime import datetime
try:
    started = datetime.fromisoformat( '$started_at'.replace( 'Z', '+00:00' ) )
    commit  = datetime.fromisoformat( '$commit_time' )
except ValueError:
    sys.exit( 2 )
print( 'HAS' if commit <= started else 'MISSING' )
" 2>/dev/null )"

if [ -z "$verdict" ]; then
    printf '%sCANNOT DETERMINE%s  could not parse one of the timestamps\n' "$YELLOW" "$NC" >&2
    printf '  started_at=%s  commit_time=%s\n' "$started_at" "$commit_time" >&2
    exit 2
fi

printf 'container   %s\n' "$CONTAINER"
printf 'started at  %s\n' "$started_at"
printf 'commit      %s  (%s)\n' "$commit_sha" "$commit_time"

if [ "$verdict" = "HAS" ]; then
    printf '%sHAS IT%s      the running process started after this commit\n' "$GREEN" "$NC"
    exit 0
fi

printf '%sMISSING%s     the commit is NEWER than the process — it is on disk, not in memory\n' "$RED" "$NC"
printf '  remedy: docker rm -f %s && docker compose up -d %s   # a RESTART will NOT do it\n' \
       "$CONTAINER" "$CONTAINER"
printf '  first:  eval "$(grep -E %s ~/.bashrc | tail -2)"\n' \
       "'^[[:space:]]*export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_(EMAIL|PASSWORD)='"
exit 1
