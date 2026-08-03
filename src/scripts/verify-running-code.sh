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
# ⚠️ AND THIS SCRIPT SHIPPED WITH THE SAME DEFECT IT EXISTS TO KILL. Measured
# 2026-07-27 by Rio ⚡ while auditing it: the first cut read `.State.StartedAt` and
# never read `.State.Running`. `docker inspect` returns the LAST start time for a
# STOPPED container — non-empty and a perfectly valid ISO timestamp — so the
# emptiness guard below only ever caught a container that does not EXIST.
#
#   EXITED container, StartedAt=2026-07-27T16:27:37Z Running=false
#     -> "HAS IT"  exit 0        for a container with NO RUNNING PROCESS AT ALL
#   NEVER-STARTED,   StartedAt=0001-01-01T00:00:00Z Running=false
#     -> "MISSING" exit 1        wrong verdict class; prescribes a recreate for a
#                                container that only needed starting
#
# The question asked is "does a RUNNING process have this commit". A start-clock
# alone answers "did a process ever start after this commit" — a different question
# with the same shape, which is this row's entire thesis wearing the fix's clothes.
# ⇒ Read BOTH facts. A container that is not running cannot answer, and
#   "cannot answer" is outcome 2, never outcome 0.
#
# USAGE
#   verify-running-code.sh <container> [commit-ish]     # default commit-ish: HEAD
#   verify-running-code.sh lupin-rest-test 69295c25
#
# EXIT CODES — deliberately distinct, because "no" and "cannot tell" have different
# remedies and collapsing them is the same class of defect this script exists for.
#   0  the running process HAS the commit
#   1  the running process does NOT have it  (recreate required)
#   2  cannot determine                      (container absent, DOWN, bad ref, unparseable)
set -uo pipefail

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

CONTAINER="${1:-}"
COMMITISH="${2:-HEAD}"

if [ -z "$CONTAINER" ]; then
    printf '%s\n' "usage: verify-running-code.sh <container> [commit-ish]" >&2
    exit 2
fi

# --- fact 1: is there a RUNNING PROCESS AT ALL, and when did it start? --------
# TWO facts, read in ONE inspect so they cannot describe different moments.
#
# INJECTABLE SEAM. The comparison is the whole decision, and it must be testable
# without a live container — otherwise the only suite that can exercise this script
# is one that needs :8000 up, which is the venue this script exists to be careful
# about. Same shape as the arbiter's hold_roots_fn / scan_fn injection.
#
# `..._RUNNING` defaults to "true" when only the clock is injected: an injected
# clock stands in for a live container, and every existing caller of the seam means
# exactly that. Set it to "false" to exercise the DOWN arm.
started_at="${VERIFY_RUNNING_CODE_STARTED_AT:-}"
is_running="${VERIFY_RUNNING_CODE_RUNNING:-}"
if [ -z "$started_at" ]; then
    # ONE call, both fields: asking twice could straddle a start/stop and yield a
    # pair that never coexisted.
    inspected="$( docker inspect -f '{{.State.Running}} {{.State.StartedAt}}' "$CONTAINER" 2>/dev/null )"
    # An empty result leaves BOTH empty, which the next guard reports as absent.
    is_running="${inspected%% *}"
    started_at="${inspected#* }"
else
    is_running="${is_running:-true}"
fi

if [ -z "$started_at" ]; then
    printf '%sCANNOT DETERMINE%s  container %s does not exist (or docker is unreachable)\n' \
           "$YELLOW" "$NC" "$CONTAINER" >&2
    printf '  nothing to inspect; check the name with: docker ps -a --format "{{.Names}}"\n' >&2
    exit 2
fi

# A never-started container reports the ZERO timestamp. Checked BEFORE the running
# flag because both are false for it and only this branch says the true thing:
# "never started" is not "has already exited", and a message that describes a
# process which never existed is the same substitution — a plausible narrative
# standing in for the measured fact — that this whole script exists to refuse.
case "$started_at" in
    0001-01-01T00:00:00*)
        printf '%sCANNOT DETERMINE%s  container %s has NEVER STARTED (zero start time)\n' \
               "$YELLOW" "$NC" "$CONTAINER" >&2
        printf '  it was created but never run, so there is no process to hold any commit\n' >&2
        printf '  remedy: docker start %s   # then re-run\n' "$CONTAINER" >&2
        exit 2 ;;
esac

# ⚠️ THE DEFECT THIS ROW IS ABOUT, GUARDED. A stopped container reports its LAST
# start time, so the clock alone would happily certify a commit against a process
# that is not there. There is no running code to have the commit — that is a
# CANNOT-DETERMINE, and its remedy is "start it", NOT the recreate that outcome 1
# prescribes. Two different situations, two different remedies, two exit codes.
if [ "$is_running" != "true" ]; then
    printf '%sCANNOT DETERMINE%s  container %s exists but is NOT RUNNING\n' \
           "$YELLOW" "$NC" "$CONTAINER" >&2
    printf '  a container that is down has no running code to verify — its last start\n' >&2
    printf '  time (%s) describes a process that has already exited\n' "$started_at" >&2
    printf '  remedy: docker start %s   # then re-run; if the code is still stale, THEN recreate\n' "$CONTAINER" >&2
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
