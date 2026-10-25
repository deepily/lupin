#!/bin/bash
# Measures what the pytest-xdist unit lane does to the coverage gate (row c8d4b539, step 1).
#
# Usage:
#   measure-xdist-coverage-arms.sh run <out-dir> <xdist-site-dir>   # arm B (-n 4) then arm A (serial)
#   measure-xdist-coverage-arms.sh compare <data-file-a> <data-file-b>
#
# <xdist-site-dir> holds pytest-xdist and execnet, installed with
#   .venv/bin/python -m pip install --no-deps --target <dir> pytest-xdist==3.8.0 execnet
# so nothing is added to the shared venv.
#
# Each arm waits for a box with no other pytest, because the repo's contended-coverage guard refuses
# a --cov run beside another suite. While an arm runs, a sampler logs the number of other pytest
# processes to <out-dir>/contention.log every 5 seconds. Read that log before quoting an arm's numbers.
#
# Each arm runs the unit tier, then the cosa tier, into one isolated COVERAGE_FILE, then the coverage
# gate in pyramid mode (it renders and checks, it runs no tier). Exit codes land in <out-dir>/arms.log.
set -u
TREE="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"

# The interpreter comes from the shared resolver, which refuses rather than fall back to a bare python3 (rows c98bce3f, fc74c1d4, 72a28255).
PROJECT_ROOT="$TREE"
source "$TREE/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_python || exit $?

if [ "${1:-}" = "compare" ]; then
    cd "$TREE" && "$VENV_PYTHON" - "$2" "$3" <<'PY'
import sys, coverage
def load( path ):
    cov = coverage.Coverage( data_file=path, config_file="pyproject.toml" )
    cov.load()
    data = cov.get_data()
    return { f : ( frozenset( data.lines( f ) or [] ), frozenset( data.arcs( f ) or [] ) ) for f in data.measured_files() }
a, b = load( sys.argv[ 1 ] ), load( sys.argv[ 2 ] )
print( "files: A", len( a ), "B", len( b ), "only A", len( set( a ) - set( b ) ), "only B", len( set( b ) - set( a ) ) )
lines = [ f for f in a if f in b and a[ f ][ 0 ] != b[ f ][ 0 ] ]
arcs  = [ f for f in a if f in b and a[ f ][ 1 ] != b[ f ][ 1 ] ]
print( "files whose executed-line set differs:", len( lines ), " arc set differs:", len( arcs ) )
for f in lines: print( "  ", f, "A-only", len( a[ f ][ 0 ] - b[ f ][ 0 ] ), "B-only", len( b[ f ][ 0 ] - a[ f ][ 0 ] ) )
PY
    exit $?
fi

[ "${1:-}" = "run" ] && [ -n "${2:-}" ] && [ -n "${3:-}" ] || { echo "usage: see the header of $0" >&2; exit 2; }
OUT="$2"; SITE="$3"; mkdir -p "$OUT"
cd "$TREE"
export LUPIN_ROOT="$TREE" PYTHONPATH="$TREE/src:$SITE" LUPIN_COVERAGE=1
stamp() { date '+%F %T'; }

others() {  # pytest processes whose cwd is not this tree
    local n=0 pid
    for pid in $( ps -eo pid=,comm=,args= | awk '$2 ~ /^python/ && $0 ~ / -m pytest/ {print $1}' ); do
        case "$( readlink /proc/$pid/cwd 2>/dev/null )" in "$TREE"*) ;; *) n=$(( n + 1 )) ;; esac
    done
    echo $n
}
wait_clear() { until [ "$( others )" = 0 ]; do sleep 20; done; echo "$( stamp ) box clear" >> "$OUT/arms.log"; }
sample() { while true; do echo "$( stamp ) others=$( others )" >> "$OUT/contention.log"; sleep 5; done; }

arm() {  # arm <name> <extra unit-tier args...>
    local name=$1; shift
    export COVERAGE_FILE="$OUT/$name.cov"
    rm -f "$COVERAGE_FILE"
    wait_clear
    sample & local spid=$!
    echo "$( stamp ) $name unit start sha=$( git rev-parse --short HEAD ) args=[$*]" >> "$OUT/arms.log"
    bash src/tests/run-unit-tests.sh -q -rf "$@" > "$OUT/$name-unit.log" 2>&1; local u=$?
    echo "$( stamp ) $name unit rc=$u" >> "$OUT/arms.log"
    cp "$COVERAGE_FILE" "$OUT/$name-unitonly.cov" 2>/dev/null
    bash src/tests/run-cosa-tests.sh -q -rf > "$OUT/$name-cosa.log" 2>&1; local c=$?
    echo "$( stamp ) $name cosa rc=$c" >> "$OUT/arms.log"
    bash src/tests/run-coverage-gate.sh > "$OUT/$name-gate.log" 2>&1; local g=$?
    echo "$( stamp ) $name gate rc=$g" >> "$OUT/arms.log"
    kill $spid
}
arm B-n4 -n 4
arm A-serial
echo "$( stamp ) ALL DONE" >> "$OUT/arms.log"
