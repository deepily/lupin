#!/bin/bash
# disk-hygiene-report.sh — weekly inventory of what the fleet leaves behind.
#
# WHY THIS EXISTS. io/claude_code_hooks/logs reached 748,063 files / 6.1 GB over six
# months and nobody knew, because nothing reported it. This prints NUMBERS, not a
# verdict. A janitor that says "cleanup complete" without counts is exactly how you
# get to three quarters of a million files.
#
# Every command here has bounded output by construction — no path list is ever
# materialized. That is deliberate: the OOM analysis names unbounded sweeps as the
# leading hypothesis for the 2026-08-22 crash, and a hygiene tool must not be the
# thing that trips it.
#
# Design: src/rnd/v0.2.0/2026.08.23-plan-3-worker-detritus-containment.md — REMOVED by c752ab9e (2026-08-29); recover: git show c752ab9e^:src/rnd/v0.2.0/2026.08.23-plan-3-worker-detritus-containment.md
set -euo pipefail

# 🔴 FIXED 2026-09-05 (row d2dd3ee3). THIS SCRIPT BECAME THE THING ITS OWN HEADER
# WARNS ABOUT, and it did so silently.
#
# It exited 1 with ZERO stdout and ZERO stderr. The cause: line 29 globbed
# "$PROJECTS"/lupin-v1-*, no lupin-v1-* directory has ever existed on this box, so
# the unmatched pattern passed through literally, `du` exited 1, `pipefail`
# propagated it, and `set -e` killed the script AFTER wt_gb was assigned and BEFORE
# the report heredoc printed. The `2>/dev/null` on that same line ate the only
# error message. Isolated one variable at a time: the identical pipeline WITH the
# unmatched glob exits 1, WITHOUT it exits 0.
#
# ⇒ A janitor that says nothing at all is worse than one that says "cleanup
# complete" without counts, because silence is indistinguishable from a clean run.
# This is the one surface in the tree that computes merged-ness, and it has been
# reporting nothing to nobody.
#
# TWO CHANGES, and the second matters more than the first:
#   1. `nullglob` — an unmatched pattern expands to nothing instead of to itself,
#      so the du list is always real paths. That fixes THIS instance.
#   2. An ERR trap that NAMES the line it died on. That fixes the CLASS: the next
#      unguarded command to fail cannot take the report down in silence. A fix that
#      only closes the known instance leaves the failure mode installed.
shopt -s nullglob

_died() {
    local rc=$? line=$1
    echo "disk-hygiene-report.sh: DIED at line ${line} (exit ${rc}) — report NOT produced." >&2
    echo "  This is a failure, not an empty result. Do not read it as a clean run." >&2
    exit "$rc"
}
trap '_died $LINENO' ERR

LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"
PROJECTS="$( dirname "$LUPIN_ROOT" )"

gb() { awk '{printf "%.2f", $1/1073741824}'; }
dir_bytes() { du -sb "$1" 2>/dev/null | cut -f1 || echo 0; }

# Sum a list of directories that may legitimately be EMPTY. `du` with no operands
# reads the current directory, which would silently report the wrong number — so an
# empty list short-circuits to 0 rather than being handed to du at all.
sum_bytes() {
    if [ "$#" -eq 0 ]; then echo 0; return; fi
    du -scb "$@" 2>/dev/null | tail -1 | cut -f1
}

# `find` exits non-zero on a missing directory, and under pipefail that killed the
# whole report — the SAME class as the glob above, found by the ERR trap the moment
# it was installed (io/claude_code_hooks/logs exists in the main checkout and in no
# worktree, so this line had never been exercised anywhere it fails).
# `count_files` reports 0 for an absent directory, which is the true answer.
# ⚠️ NOT `find ... | wc -l || echo 0`. `wc` succeeds and prints 0 even when `find`
# failed, and pipefail then fires the `||` as well — so the substitution captures
# "0\n0", which the threshold test below rejects with "integer expression expected".
# Caught by running it in a worktree, where the directory genuinely is absent.
# Test the directory instead of trying to rescue a pipeline that already printed.
count_files() {
    [ -d "$1" ] || { echo 0; return; }
    find "$1" -maxdepth 1 -type f 2>/dev/null | wc -l
}

hook_logs="$LUPIN_ROOT/io/claude_code_hooks/logs"
hl_files=$( count_files "$hook_logs" )
hl_gb=$( dir_bytes "$hook_logs" | gb )

wt_count=$( git -C "$LUPIN_ROOT" worktree list 2>/dev/null | wc -l )   # wc always succeeds
wt_dirs=( "$PROJECTS"/lupin-wt-* "$PROJECTS"/lupin-v1-* )   # nullglob: unmatched -> absent
wt_gb=$( sum_bytes "${wt_dirs[@]}" | gb )
wti_gb=$( dir_bytes "$LUPIN_ROOT/.claude/worktrees" | gb )
tx_gb=$( dir_bytes "$HOME/.claude/projects" | gb )
io_gb=$( dir_bytes "$LUPIN_ROOT/io" | gb )

# A worktree whose HEAD is already an ancestor of the integration branch is dead
# weight — count them, because that number IS the reclaimable backlog.
BASE="$( git -C "$LUPIN_ROOT" rev-parse --abbrev-ref HEAD )"
merged=0
while read -r wt; do
    [ -z "$wt" ] && continue
    h=$( git -C "$wt" rev-parse HEAD 2>/dev/null ) || continue
    git -C "$LUPIN_ROOT" merge-base --is-ancestor "$h" "$BASE" 2>/dev/null && merged=$(( merged + 1 ))
done < <( git -C "$LUPIN_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2}' )

cat <<REPORT
disk hygiene — $( date '+%Y-%m-%d %H:%M' )
  hook logs      : ${hl_files} files, ${hl_gb} GB
  worktrees      : ${wt_count} total (${merged} fully merged = reclaimable)
  worktree bytes : ${wt_gb} GB external + ${wti_gb} GB in-repo
  transcripts    : ${tx_gb} GB
  io/ total      : ${io_gb} GB
REPORT

# Thresholds worth waking someone for. Numbers first, judgment second.
[ "$hl_files" -gt 50000 ] && echo "  ⚠ hook logs over 50k files — run sweep-hook-logs.sh --apply"
[ "$merged" -gt 5 ]       && echo "  ⚠ ${merged} fully-merged worktrees reclaimable — see Plan 2"
exit 0
