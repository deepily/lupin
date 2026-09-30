#!/usr/bin/env bash
# POSITIVE CONTROL ON ARM B — separates "pair is green-on-green (dead)" from
# "B never collected the new files (my instrument failed)". They print identically otherwise.
#
# FIXED per maria 18:44 — keys on COLLECTED, never on `passed`. B_passed - A_passed
# is < 21 whenever any NEW test FAILS, which is precisely the case where the pair HAS
# range. The old form would have blocked the most interesting outcome as an instrument
# failure. Collected is insensitive to the pass/fail split, which is the whole point.
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe

# collected = sum of EVERY outcome bucket on pytest's final summary line
collected () {
  tail -5 "$1" | grep -oE '[0-9]+ (passed|failed|skipped|error|errors|xfailed|xpassed|deselected|warnings?)' \
    | grep -vE 'warning' | grep -oE '^[0-9]+' | paste -sd+ | bc
}
ca=$( collected "$S/A.log" ); cb=$( collected "$S/B.log" )
pa=$( tail -5 "$S/A.log" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' )
pb=$( tail -5 "$S/B.log" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' )
echo "A: collected=$ca passed=$pa      | summary: $( tail -2 "$S/A.log" | tr -s ' \n' ' ' )"
echo "B: collected=$cb passed=$pb      | summary: $( tail -2 "$S/B.log" | tr -s ' \n' ' ' )"
echo "COLLECTED delta = $(( cb - ca ))   (predicted +21 from def test_ counts 6/6/3/6)"
echo "PASSED    delta = $(( pb - pa ))   (informational ONLY — never the gate)"
echo "--- tree identity: a checkout that silently did not take gives the same delta as a green stack ---"
grep -E 'start_sha|tree_at_end|pytest_rc' "$S/B.meta"
echo
if [ "$(( cb - ca ))" -eq 21 ]; then
  echo "CONTROL PASSED — B collected exactly the 21 tests the move adds."
  echo "  ⇒ an S_A == S_B here is a REAL dead pair, and reportable as one."
elif [ "$(( cb - ca ))" -gt 0 ]; then
  echo "CONTROL PARTIAL — B collected MORE than A but not +21 (delta=$(( cb - ca )))."
  echo "  ⇒ the collector DID reach the new files, so this is NOT an instrument failure."
  echo "  ⇒ my +21 prediction was mis-sized (parametrize expands past def counts). Report both numbers."
else
  echo "🔴 THE CHECK FAILED — B collected no more than A."
  echo "  ⇒ do NOT report a dead pair. B never saw the move. Read B.meta's sha pair first."
fi
