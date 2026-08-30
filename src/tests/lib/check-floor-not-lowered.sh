#!/bin/bash
# PROPOSED FIX for run-coverage-gate.sh's false green (row from Maya's working-tree-artifact
# audit, src/rnd/v0.2.1/2026.08.30-working-tree-artifact-gate-audit.md).
#
# THE DEFECT THIS CLOSES. The gate's floor is pyproject's `fail_under`, read from the
# WORKING TREE at gate time — never from HEAD. Measured 2026-08-30 at sha 908414ad:
# lowering it 92 -> 0 turned a 0.84% measurement into "COVERAGE GATE PASSED", exit 0.
#
# WHY THE EXISTING TELL CANNOT DO THIS JOB. run-coverage-gate.sh:118 prints
# `tracked-dirty=<count>`. It printed 1 during the tamper and the gate passed anyway —
# nothing consumes it. And it CANNOT carry the check even if something did: an unrelated
# README edit prints the identical string while the gate correctly fails. A repo-wide
# count is not a statement about pyproject.
#
# ⇒ So this asks the only question that decides the verdict: is the floor we are about to
#   enforce the floor the branch actually committed?
#
# DELIBERATELY NOT CHECKED HERE, and named so nobody reads more into a pass than it carries:
#   · `source` / `omit` edits, which shrink the DENOMINATOR rather than the threshold.
#     That is the frame check's territory and belongs in its own row.
#   · a floor RAISED locally — stricter than HEAD, so it is announced, not refused.
#
# Exit: 0 floor intact (or raised) · 1 floor LOWERED · 2 CANNOT TELL.
# 1 and 2 are BOTH refusals — the codes differ only so the cause is diagnosable.
# Callers must treat any non-zero as a refusal; see run-coverage-gate.sh.

set -u
set -o pipefail

PYBIN="${1:?usage: check-floor-not-lowered.sh <python> [pyproject-path]}"
PYPROJECT="${2:-pyproject.toml}"

read_floor() {  # stdin = a pyproject.toml; prints the floor or nothing
    "$PYBIN" -c '
import sys, tomllib
try:
    d = tomllib.loads( sys.stdin.buffer.read().decode( "utf-8" ) )
except Exception:
    sys.exit( 1 )
v = d.get( "tool", { } ).get( "coverage", { } ).get( "report", { } ).get( "fail_under" )
if v is None: sys.exit( 1 )
print( v )'
}

tree_floor="$( read_floor < "$PYPROJECT" )" || tree_floor=""
head_floor="$( git show "HEAD:$PYPROJECT" 2>/dev/null | read_floor )" || head_floor=""

if [ -z "$tree_floor" ] || [ -z "$head_floor" ]; then
    echo "[floor-guard] REFUSED — CANNOT TELL whether the floor is intact." \
         "working-tree floor='${tree_floor:-<unreadable>}' HEAD floor='${head_floor:-<unreadable>}'."
    echo "  This REFUSES rather than waving through, on Mr Radio's condition 2026-08-30:"
    echo "  a guard that shrugs on a parse error is the defect wearing the cure's clothes."
    echo "  The gate is about to enforce a threshold nobody could check against the branch,"
    echo "  and an unreadable threshold must never read as a pass."
    echo "  Usual causes: no commit yet, $PYPROJECT absent from HEAD, or a malformed table."
    exit 2
fi

if "$PYBIN" -c "import sys; sys.exit( 0 if float( sys.argv[1] ) < float( sys.argv[2] ) else 1 )" \
        "$tree_floor" "$head_floor"; then
    echo "[floor-guard] REFUSED — the coverage floor is LOWERED in the working tree."
    echo "    HEAD says          fail_under = $head_floor"
    echo "    this tree says     fail_under = $tree_floor"
    echo "  The pass mark IS the mandate, so a gate run against an uncommitted lower floor"
    echo "  certifies nothing. Commit the change and let it be reviewed, or restore it:"
    echo "      git checkout -- $PYPROJECT"
    exit 1
fi

if [ "$tree_floor" != "$head_floor" ]; then
    echo "[floor-guard] floor RAISED locally ($head_floor -> $tree_floor) — stricter than HEAD, allowed."
else
    echo "[floor-guard] floor intact — fail_under = $tree_floor, same as HEAD."
fi
exit 0
