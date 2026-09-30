#!/usr/bin/env bash
# Mr. Radio's accepted offer. BASELINE FIRST, sets BY NAME.
# 🔴 HIS CONDITION, WIRED SO IT CANNOT BE FORGOTTEN: the third tier at 82241ff8 is a
# DISCRIMINATING arm and runs ONLY IF tip-minus-baseline is NON-EMPTY. An empty set
# has nothing to attribute, so the arm would answer a question nobody asked.
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
while ! grep -qE 'ALL ARMS DONE|HALTED' "$S/driver.log" 2>/dev/null; do sleep 15; done
echo "probe arms finished — box free"

"$S/arm.sh" RBASE 8bfb1eac >/dev/null 2>&1
echo "RBASE 8bfb1eac landed: $( wc -l < "$S/RBASE.failset" ) failing"
"$S/arm.sh" RTIP  ac37ea90 >/dev/null 2>&1
echo "RTIP  ac37ea90 landed: $( wc -l < "$S/RTIP.failset" ) failing"

comm -13 "$S/RBASE.failset" "$S/RTIP.failset" > "$S/RNEW.failset"
n=$( wc -l < "$S/RNEW.failset" )
echo "--- NEW at the tip, absent at the baseline (BY NAME) — count=$n ---"; cat "$S/RNEW.failset"
echo "--- present at the baseline, GONE at the tip (BY NAME) ---"; comm -23 "$S/RBASE.failset" "$S/RTIP.failset"

if [ "$n" -eq 0 ]; then
  echo "TIP-MINUS-BASELINE IS EMPTY ⇒ THIRD TIER NOT RUN, per Mr. Radio."
  echo "  Nothing to attribute, so 82241ff8 would answer a question nobody asked."
else
  echo "TIP-MINUS-BASELINE IS NON-EMPTY ($n)."
  echo "--- PRE-FILTER (maria 19:08): arm B is a tier at be1d58b2, which CONTAINS ALL 85 ---"
  echo "    same worktree, same pins, same provisioning as RTIP ⇒ NO cross-tree artifact reasoning."
  comm -12 "$S/RNEW.failset" "$S/B.failset" | sed 's/^/  ALREADY-IN-ARM-B (carried side, not the three): /'
  comm -23 "$S/RNEW.failset" "$S/B.failset" > "$S/RSURV.failset"
  m=$( wc -l < "$S/RSURV.failset" )
  echo "--- SURVIVES the pre-filter ⇒ NOT attributable to the 85 — count=$m ---"; cat "$S/RSURV.failset"
  if [ "$m" -eq 0 ]; then
    echo "PRE-FILTER ABSORBED EVERYTHING ⇒ 82241ff8 ARM NOT RUN. 13 minutes of box saved."
  else
    echo "⇒ RUNNING 82241ff8 (standing authorisation, Mr. Radio) — an interaction effect is NOT ruled out by arm B."
    "$S/arm.sh" RCARRIED 82241ff8 >/dev/null 2>&1
    echo "RCARRIED 82241ff8 landed: $( wc -l < "$S/RCARRIED.failset" ) failing"
    comm -12 "$S/RSURV.failset" "$S/RCARRIED.failset" | sed 's/^/  CARRIED-SIDE: /'
    comm -23 "$S/RSURV.failset" "$S/RCARRIED.failset" | sed 's/^/  CHEECH-SIDE: /'
    echo "--- ac37ea90 arm: the RULE comment-only=>inert is unsound, but MEASURED here 0 tests read"
    echo "    routers/notifications.py as text (control: 21 files do use getsource). Arm kept as belt+braces. ---"
    "$S/arm.sh" RPRE 297d710c >/dev/null 2>&1
    echo "RPRE 297d710c landed: $( wc -l < "$S/RPRE.failset" ) failing"
    comm -13 "$S/RPRE.failset" "$S/RTIP.failset" | sed 's/^/  AC37EA90-ONLY: /'
  fi
fi
echo "RADIO TIERS DONE"
