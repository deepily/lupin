#!/usr/bin/env bash
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
# the tree is READ-ONLY while a tier runs — wait for A before touching it
while [ ! -f "$S/A.failset" ]; do sleep 10; done
echo "A  landed: $( wc -l < "$S/A.failset" ) failing"

"$S/arm.sh" B be1d58b2 >/dev/null 2>&1      # precondition: does the pair have range?
echo "B  landed: $( wc -l < "$S/B.failset" ) failing"
if cmp -s "$S/A.failset" "$S/B.failset"; then
  echo "PRECONDITION: S_A == S_B — pair has NO range for the which-tree question"
else
  echo "PRECONDITION: S_A != S_B — pair has range"
fi

"$S/arm.sh" A2 35590594 >/dev/null 2>&1     # maria's mandatory determinism control
echo "A2 landed: $( wc -l < "$S/A2.failset" ) failing"
if ! cmp -s "$S/A.failset" "$S/A2.failset"; then
  echo "🔴 DETERMINISM GATE FAILED: S_A1 != S_A2 — STOPPING BEFORE C, per maria."
  echo "   only-A : $( comm -23 "$S/A.failset" "$S/A2.failset" )"
  echo "   only-A2: $( comm -13 "$S/A.failset" "$S/A2.failset" )"
  echo "HALTED"; exit 3
fi
echo "DETERMINISM GATE PASSED: S_A1 == S_A2"

"$S/arm.sh" C 35590594 be1d58b2 120 >/dev/null 2>&1   # THE ARM — real move 120s in
echo "C  landed: $( wc -l < "$S/C.failset" ) failing"
echo "ALL ARMS DONE"
