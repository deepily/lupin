#!/usr/bin/env bash
# arm.sh <ARM> <START_SHA> [MOVE_TO_SHA] [MOVE_AT_SECONDS]
# Runs the unit tier in the probe worktree. If MOVE_TO_SHA is given, performs a
# REAL branch move in the tree MOVE_AT_SECONDS into the run.
set -uo pipefail
WT=/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-tiberius-moveprobe
OUT=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
ARM=$1; START=$2; MOVETO=${3:-}; MOVEAT=${4:-0}

cd "$WT" || exit 9
git checkout --quiet --detach "$START" || exit 9
# every arm starts from the SAME pyc state: converted, no carry-over from the last arm
./src/scripts/purge-pycache.sh >/dev/null 2>&1
PYTHON="$WT/.venv/bin/python" ./src/scripts/migrate-pyc-to-checked-hash.sh >/dev/null 2>&1

{
  echo "arm=$ARM start_sha=$( git rev-parse HEAD ) move_to=${MOVETO:-none} move_at=${MOVEAT}s"
  echo "started_at=$( date -Is )"
} > "$OUT/$ARM.meta"

if [ -n "$MOVETO" ]; then
  (  sleep "$MOVEAT"
     cd "$WT"
     echo "move_fired_at=$( date -Is )" >> "$OUT/$ARM.meta"
     git checkout --quiet --detach "$MOVETO" 2>>"$OUT/$ARM.meta"
     echo "move_rc=$? tree_now=$( git rev-parse HEAD )" >> "$OUT/$ARM.meta"
  ) &
fi

LUPIN_ROOT="$WT" PYTHONPATH="$WT/src" LUPIN_UNIT_NETWORK=block \
  "$WT/.venv/bin/python" -m pytest src/tests/unit/ -q -p no:randomly \
  > "$OUT/$ARM.log" 2>&1
rc=$?
wait
{
  echo "pytest_rc=$rc"
  echo "finished_at=$( date -Is )"
  echo "tree_at_end=$( cd "$WT" && git rev-parse HEAD )"
} >> "$OUT/$ARM.meta"

grep -E '^(FAILED|ERROR) ' "$OUT/$ARM.log" | sed 's/ - .*//' | sort -u > "$OUT/$ARM.failset"
tail -3 "$OUT/$ARM.log" >> "$OUT/$ARM.meta"
echo "ARM $ARM DONE rc=$rc failset=$( wc -l < "$OUT/$ARM.failset" )"
