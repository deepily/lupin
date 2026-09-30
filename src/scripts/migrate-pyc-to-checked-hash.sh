#!/usr/bin/env bash
#
# Convert this tree's bytecode cache to CHECKED-HASH invalidation.
#
# WHY (row 866f43ce, Rick ruled YES 2026-08-30; bug d18ce9ef).
# CPython validates a `.pyc` on the source's WHOLE-SECOND mtime plus its SIZE. A same-size
# edit restored inside the same second defeats both at once, so stale bytecode is served as
# valid — and the failure points the WRONG WAY: you restore the file, read it back to
# confirm it is clean, and the interpreter keeps running the mutant. It is cross-process, so
# a fresh pytest reads the stale pyc off disk; it lies in BOTH directions (false survivors
# AND, in a sequential harness, false kills from the previous mutant's bytecode); and it is
# SELECTIVE — a length-changing edit invalidates the cache on its own, so most mutations in
# a pass are unaffected and the harness looks healthy while lying about exactly the edits
# that leave mtime and size unchanged.
#
# Checked-hash invalidation hashes the SOURCE instead, so it is immune to a same-size
# same-second edit by construction.
#
# 🔴 THE `-f` IS LOAD-BEARING. THIS IS THE WHOLE TRAP. Measured 2026-08-30:
#
#     python -m compileall --invalidation-mode checked-hash .        -> pyc stays TIMESTAMP
#     python -m compileall -f --invalidation-mode checked-hash .     -> pyc becomes checked-hash
#
# Without `-f`, compileall considers an existing up-to-date `.pyc` as needing no work and
# leaves it exactly as it found it. Any tree that has ever run its tests already has a
# `__pycache__` full of timestamp pycs, so the command WITHOUT `-f` converts nothing while
# reporting success — the setting "changed" and the tree is still vulnerable. That is
# precisely the "reach the caches that ALREADY EXIST" condition this migration owes.
#
# ⚠️ NOT CONVERT-ONCE-AND-FORGET. Two measured facts pull in opposite directions:
#
#   · An EXISTING checked-hash pyc STAYS checked-hash. Edit the source, re-import, and
#     CPython regenerates it in the same mode — it inherits, it does not degrade. So you do
#     not need a build step on every run for files that are already converted.
#   · A pyc written when NO prior pyc exists is TIMESTAMP-based — nothing to inherit from,
#     and CPython's default is timestamp.
#
# 🔴 SO THE OLD PURGE HABIT NOW RE-OPENS THE HOLE IT USED TO PLUG. `rm -rf __pycache__`
#    deletes the checked-hash caches and the next import silently rebuilds them as
#    timestamp, putting the tree back to the original defect with nothing saying so.
#    Convert after any purge, or do not purge.
#
#   ⇒ Three ways a tree drifts back, one mechanism: a NEW .py file, a PURGED __pycache__, or
#     a module imported for the FIRST TIME since the last conversion. Measured live
#     2026-08-30 — a verify minutes after a clean conversion found exactly one offender
#     (src/cosa/utils/coverage_contention.py, arrived on a peer's commit, imported before
#     the next conversion). Re-run this after adding files or purging; `--verify` tells you
#     whether you need to.
#
# Usage:
#   src/scripts/migrate-pyc-to-checked-hash.sh                  # convert, then verify
#   src/scripts/migrate-pyc-to-checked-hash.sh --verify         # report only, change nothing
#   src/scripts/migrate-pyc-to-checked-hash.sh [--verify] DIR…  # scope to DIR(s) instead of src/
#
# 🔴 THE ARGUMENT SURFACE IS PART OF THE MEASUREMENT (row a4e36bcb, 2026-08-30).
# An earlier cut of this script tested `$1` only for the literal `--verify` and assigned
# TARGETS unconditionally, so a path on the command line was neither used NOR rejected — it
# was silently discarded while the script scanned `$LUPIN_ROOT/src` and printed a verdict that
# read as if it were about the path you typed. Measured: a temp dir holding exactly ONE
# unchecked-hash pyc got `2416 (checked-hash=2416)` and `exit 0`. That was caught only because
# 2,416 was implausible for a temp dir; with a plausible count it would have produced a wrong
# bug report carrying what looked like clean evidence.
#
# This is the same failure family as the `src/cosa/.venv` mis-population recorded below — the
# scope silently differing from the scope the operator meant — arriving through the argument
# surface instead of the exclude pattern. Hence: every argument is either HONOURED or REFUSED
# (never discarded), and the census NAMES the roots it actually scanned.
set -uo pipefail

# 🔴 DERIVED UNCONDITIONALLY — $LUPIN_ROOT IS NOT CONSULTED. This script is shipped INSIDE the
# tree it cleans, so the environment can only DISAGREE with it, never inform it. The old line
# read "${LUPIN_ROOT:-<this same expression>}": the fallback was already right, and a SET
# variable simply won over it. Every seat's shell exports LUPIN_ROOT pointing at the MAIN
# checkout, so running this from a worktree purged /…/lupin, printed its success banner, and
# left the worktree exactly as poisoned as it found it — two harms in one command, and the
# clobbered tree belongs to somebody else. Found and remedied by Pocholo 📣, 2026-08-30 ~17:52.
LUPIN_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
PYTHON="${PYTHON:-$LUPIN_ROOT/.venv/bin/python}"
VERIFY_ONLY=0
ROOTS=()

usage() {
    cat <<'USAGE'
Usage: migrate-pyc-to-checked-hash.sh [--verify] [DIR...]

  --verify     report only; change nothing (exit 1 if any pyc THIS interpreter
               reads is not checked-hash)
  DIR...       directories to convert/verify. Default: $LUPIN_ROOT/src
  -h, --help   this message

Every argument is honoured or refused — never silently discarded. The census
names the roots it scanned, so the scope is visible in the same breath as the
verdict.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --verify )    VERIFY_ONLY=1 ;;
        -h|--help )   usage; exit 0 ;;
        -- )          shift; ROOTS+=( "$@" ); break ;;
        -* )          echo "ERROR: unknown option '$1'" >&2; usage >&2; exit 2 ;;
        * )           ROOTS+=( "$1" ) ;;
    esac
    shift
done

# A path that is not a directory is REFUSED, not coerced. The census walks
# `__pycache__/*.pyc` under each root, so a file or a typo would scan nothing and report a
# clean bill — the exact silent-wrong-scope this row exists to close.
for root in "${ROOTS[@]+"${ROOTS[@]}"}"; do
    if [[ ! -d "$root" ]]; then
        echo "ERROR: not a directory: $root" >&2
        exit 2
    fi
done

# Repo source only. Third-party code is deliberately NOT converted: nobody mutation-tests
# it, and rewriting thousands of vendored pycs buys nothing while widening the blast radius.
#
# 🔴 EXCLUDING THE NESTED VENV IS NOT AN OPTIMISATION — WITHOUT IT THIS SCRIPT MEASURES THE
# WRONG POPULATION. The root `.venv` sits outside `src/` and is excluded for free, which is
# what the first cut of this script assumed was the whole story. It is not: `src/cosa/.venv`
# is a SECOND virtualenv INSIDE the tree. Measured 2026-08-30:
#
#     .py files under src/                        31,734
#     .py files in src/cosa/.venv (3.11 vendor)   29,303   <-- 92%
#     actual Lupin source                          2,431
#
# So the un-excluded version spent minutes rewriting third-party bytecode for an interpreter
# this repo does not run, and reported a five-figure "converted" count that was ~92% vendor.
# A number that large reads like a thorough migration; it was mostly noise — the same
# wrong-population defect this row's own epic keeps finding, this time in the fix.
EXCLUDE_RE='(^|/)(\.venv|node_modules|\.git|__pypackages__|site-packages)(/|$)'
if [[ ${#ROOTS[@]} -gt 0 ]]; then TARGETS=( "${ROOTS[@]}" )
else                              TARGETS=( "$LUPIN_ROOT/src" ); fi

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: no interpreter at $PYTHON (set PYTHON=... or build the venv)" >&2
    exit 2
fi

# ── the mode reader, used by both convert and verify ──────────────────────────────────
# A pyc's flags word is bytes 4..8. Bit 0 = hash-based, bit 1 = check_source. So
# 0b11 = checked-hash, 0b01 = UNCHECKED-hash (never validated — worse than timestamp for
# our purposes, and reported separately rather than folded into a pass).
#
# 🔴 THE CENSUS SPLITS THREE POPULATIONS, because two of them are NOT compileall's to own
# and folding them into the verdict would make this gate permanently red and therefore
# useless. Both are REPORTED rather than silently dropped — "not listed" and "fine" are
# different facts. Counts below are AFTER the venv exclusion above — see it for why that
# matters more than it looks.
#
#   1. THIS interpreter's own pycs (`cpython-313.pyc`) — compileall's responsibility, and
#      the ONLY population the exit code is about.
#   2. OTHER interpreters' pycs (`cpython-310`, `cpython-311`) — debris from environments
#      this repo no longer runs. A 3.13 interpreter never reads them, so their invalidation
#      mode cannot affect anything. Inert, not a finding.
#   3. PYTEST'S ASSERTION-REWRITTEN pycs (`cpython-313-pytest-8.4.2.pyc`) — written by
#      pytest's rewriter, not by compileall, which can neither produce nor convert them.
#      ⚠️ THIS IS A REAL RESIDUAL GAP, not a technicality: TEST modules keep timestamp-based
#      caches, so a same-size same-second edit to a TEST file is still not seen. Mutating
#      library code under src/ is covered; mutating a test file is not, and
#      `tests.helpers.pyc_freshness.mutated_source` remains the tool for that case.
#
read -r -d '' CENSUS_PY <<'PYEOF' || true
import struct, sys, sysconfig
from pathlib import Path

tag       = sysconfig.get_config_var( "py_version_nodot" ) or ""
mine      = f"cpython-{tag}.pyc"
buckets   = { "mine": [], "other_interpreter": [], "pytest_rewritten": [] }
modes     = { "mine": {}, "other_interpreter": {}, "pytest_rewritten": {} }

EXCLUDED = { ".venv", "node_modules", ".git", "__pypackages__", "site-packages" }

# The scope belongs NEXT TO the verdict. Printed RESOLVED, so a relative path, a symlink or a
# worktree that is not the tree you think you are standing in is visible rather than inferred.
print( "  scanned roots:" )
for root in sys.argv[ 1: ]:
    print( f"      {Path( root ).resolve()}" )

for root in sys.argv[ 1: ]:
    for pyc in Path( root ).rglob( "__pycache__/*.pyc" ):
        # Same exclusion as the conversion. A census over a population the converter never
        # visited would report offenders nobody can fix, and bury the real ones under them.
        if EXCLUDED & set( pyc.parts ): continue
        try:
            flags = struct.unpack( "<I", pyc.read_bytes()[ 4:8 ] )[ 0 ]
        except Exception:
            mode = "unreadable"
        else:
            mode = ( "checked-hash"   if flags & 0b11 == 0b11
                     else "unchecked-hash" if flags & 0b01
                     else "timestamp" )
        if   "-pytest-" in pyc.name:    key = "pytest_rewritten"
        elif pyc.name.endswith( mine ): key = "mine"
        else:                           key = "other_interpreter"
        modes[ key ][ mode ] = modes[ key ].get( mode, 0 ) + 1
        if mode != "checked-hash": buckets[ key ].append( pyc )

labels = {
    "mine"              : f"THIS interpreter ({mine}) — the verdict",
    "other_interpreter" : "other interpreters — inert, never read here",
    "pytest_rewritten"  : "pytest assertion-rewritten — compileall cannot convert",
}
for key, label in labels.items():
    total = sum( modes[ key ].values() )
    detail = ", ".join( f"{m}={n}" for m, n in sorted( modes[ key ].items() ) ) or "none"
    print( f"  {label}\n      {total:>6}  ({detail})" )

offenders = buckets[ "mine" ]
if offenders:
    print( f"\n  {len( offenders )} pyc(s) for THIS interpreter are not checked-hash. First 10:" )
    for pyc in offenders[ :10 ]: print( f"    {pyc}" )
if buckets[ "pytest_rewritten" ]:
    print( f"\n  NOTE: {len( buckets[ 'pytest_rewritten' ] )} pytest-rewritten pycs remain "
           f"timestamp-based.\n        Expected — compileall does not own them. Editing a TEST "
           f"file inside a test\n        is therefore still exposed; use "
           f"tests.helpers.pyc_freshness.mutated_source there." )
sys.exit( 1 if offenders else 0 )
PYEOF

if [[ $VERIFY_ONLY -eq 0 ]]; then
    echo "Converting bytecode cache to checked-hash under: ${TARGETS[*]}"
    echo "(-f is required: without it, existing pycs are left untouched)"
    # -q twice = errors only. A failure to compile one file must not abort the migration:
    # the tree legitimately contains files that are not importable under this interpreter,
    # and their pycs are not what this is protecting.
    "$PYTHON" -m compileall -f --invalidation-mode checked-hash -q -q \
              -x "$EXCLUDE_RE" "${TARGETS[@]}"
    echo "compileall exited $? (non-zero = some file failed to compile; census below is the verdict)"
    echo
fi

echo "Census of $( [[ $VERIFY_ONLY -eq 1 ]] && echo "the roots below" || echo "the converted roots below" ):"
"$PYTHON" -c "$CENSUS_PY" "${TARGETS[@]}"
STATUS=$?

if [[ $STATUS -eq 0 ]]; then
    echo
    echo "✓ every pyc THIS interpreter reads is checked-hash — a same-size same-second edit"
    echo "  to library code under the scanned roots named above will be SEEN. See the note above"
    echo "  for what is excluded; the claim is scoped to the population the verdict measured."
else
    echo
    # The mode is NOT asserted here: the census one screen up already splits timestamp from
    # unchecked-hash, and this line used to claim "timestamp-based" directly beneath a census
    # reading `unchecked-hash=1`. Unchecked-hash is the more dangerous of the two — timestamp at
    # least invalidates on mtime+size, unchecked-hash is never revalidated at all — so naming
    # the wrong one understates the finding.
    echo "✗ pycs above are NOT checked-hash (see the census for which mode) and would serve"
    echo "  stale bytecode."
    [[ $VERIFY_ONLY -eq 1 ]] && echo "  Fix: run this script without --verify."
fi
exit $STATUS
