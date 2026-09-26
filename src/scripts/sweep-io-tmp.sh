#!/bin/bash
# sweep-io-tmp.sh — expire the one-off docs in io/tmp/.
#
# WHY THIS EXISTS. Rick's ruling 2026-09-26 (broadcast 355f708f, then
# ask_multiple_choice answered "Temp folder that clears itself", answered=true,
# default_used=false): a one-off report written for him to read once belongs in a
# temp directory, "because if it's in a temp directory, it's by definition not his
# problem to clean up." io/write-ups/ had ten files and no expiry. io/tmp/ is the
# self-clearing replacement, and THIS SCRIPT IS THE PART THAT MAKES "self-clearing"
# true — without it the folder is just io/write-ups/ with a shorter name.
#
# The rule it implements: planning-is-prompting workflow/rnd-directory-policy.md
# v1.2 § Where Ephemeral Work Goes Instead. A one-off report goes in the notify
# abstract; if it is too long for the card it goes to io/tmp/yyyy.mm.dd-slug.md
# and is deleted after 7 days.
#
# 🔴 SEVEN DAYS MEANS SEVEN DAYS — `-mmin`, NOT `-mtime`. `find -mtime +7`
# truncates age to whole 24h units and matches only age > 7, so it first deletes at
# EIGHT days. Rachel 🕊️ caught that on the row before anything was written, and
# María ruled it 2026-09-26 13:46: a file goes once it is more than 7x24 hours old.
# `-mmin +10080` is exact. The acceptance test is a file at 7d+1m (must go) and one
# at 7d-1m (must stay) — deliberately NOT the 8d/1d pair the row first proposed,
# which passes under both spellings and so cannot tell a correct sweep from one
# that is a day late.
#
# 🔴 DRY RUN BY DEFAULT — IT IS A GATE CONDITION, NOT A COURTESY. Nothing is
# deleted without --apply, matching sweep-hook-logs.sh. A deletion tool pointed at
# the wrong directory by a typo would otherwise act on its first cron tick with
# nothing left to review.
#
# SCOPE, CHOSEN RATHER THAN INHERITED. sweep-hook-logs.sh names its file patterns
# explicitly because it shares a directory with append-only logs it must not touch.
# io/tmp/ has no such neighbours: its entire contract is "everything here expires",
# so every regular file under it is in scope at any depth, and empty directories
# are pruned afterwards. If something in io/tmp/ ever needs to survive, the answer
# is that it does not belong in io/tmp/.
#
# Usage:
#   ./sweep-io-tmp.sh              # dry run — reports, deletes nothing
#   ./sweep-io-tmp.sh --apply      # actually delete
#   RETAIN_MINUTES=1440 ./sweep-io-tmp.sh --apply
#
# Installed via src/scripts/disk-hygiene.crontab (see that file's install line).
set -euo pipefail

LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"
TMP_DIR="$LUPIN_ROOT/io/tmp"
RETAIN_MINUTES="${RETAIN_MINUTES:-10080}"   # 7 x 24 x 60
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

# An absent directory is not an error — io/tmp/ is created on first use and a box
# that has never written a one-off doc has nothing to sweep. Say so rather than
# exiting silently: a janitor that prints nothing is indistinguishable from a
# janitor that died.
[[ -d "$TMP_DIR" ]] || { echo "io/tmp sweep — no directory at $TMP_DIR, nothing to do"; exit 0; }

before_files=$( find "$TMP_DIR" -type f 2>/dev/null | wc -l )
eligible=$(    find "$TMP_DIR" -type f -mmin "+$RETAIN_MINUTES" 2>/dev/null | wc -l )

printf 'io/tmp sweep — retain %s minutes (%s days)\n' "$RETAIN_MINUTES" \
       "$( awk -v m="$RETAIN_MINUTES" 'BEGIN{ printf "%.2f", m/1440 }' )"
printf '  dir      : %s\n' "$TMP_DIR"
printf '  before   : %s files\n' "$before_files"
printf '  eligible : %s older than %s minutes\n' "$eligible" "$RETAIN_MINUTES"

if [[ "$APPLY" -eq 0 ]]; then
    echo "  DRY RUN — nothing deleted. Re-run with --apply."
    exit 0
fi

# -delete rather than `| xargs rm`: no path list is ever materialized, so a large
# sweep cannot become the unbounded-output command the 2026-08-22 OOM analysis
# warned about.
find "$TMP_DIR" -type f -mmin "+$RETAIN_MINUTES" -delete 2>/dev/null || true

# Prune directories the sweep emptied. -mindepth 1 so io/tmp/ itself always
# survives — the doc viewer serves the folder, and a missing folder is a 404 for
# every future write, not a clean state.
find "$TMP_DIR" -mindepth 1 -type d -empty -delete 2>/dev/null || true

after_files=$( find "$TMP_DIR" -type f 2>/dev/null | wc -l )
printf '  after    : %s files\n' "$after_files"
printf '  reclaimed: %s files\n' "$(( before_files - after_files ))"
