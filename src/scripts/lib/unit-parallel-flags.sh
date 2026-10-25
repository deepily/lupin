#!/bin/bash
# The pytest-xdist flags for the unit tier — row c8d4b539 step 2.
#
# The unit tier runs `-n 4` by default. Measured 2026-10-25 at 7fafa7762: 3.7x faster than
# serial, with an identical coverage answer. LUPIN_UNIT_WORKERS overrides the count; 0 means
# serial.
#
# IT REFUSES RATHER THAN FALLING BACK. A box without pytest-xdist that quietly ran serial would
# take an hour instead of a quarter of one and print nothing to say why. Exit 3 matches the
# missing-venv refusal in resolve-venv-pytest.sh.
#
# NO FLAGS WHEN xdist CANNOT HELP. A collection-only run, a debugger run, or a caller who passed
# their own -n / --dist / -p no:xdist gets nothing added; the caller's choice stands.
#
# USAGE (source it; prints the flags on stdout, possibly none):
#   source "$PROJECT_ROOT/src/scripts/lib/unit-parallel-flags.sh"
#   FLAGS="$( unit_parallel_flags "$PYTEST" "$@" )" || exit $?
#
# ⚠️ IT RETURNS, IT DOES NOT EXIT — same reason as resolve-venv-pytest.sh.
#
# Created: 2026-10-25 (row c8d4b539)

UNIT_PARALLEL_DEFAULT_WORKERS=4

unit_parallel_flags() {
    # Requires: $1 is the resolved pytest path; the remaining args are the caller's pytest args.
    #           The interpreter beside $1 is the one pytest runs under.
    # Ensures:  prints "-n <N>" when the lane applies; prints nothing when it does not;
    #           returns 3 (message on stderr) when it applies but pytest-xdist is not importable.
    local pytest_path="$1"; shift
    local workers="${LUPIN_UNIT_WORKERS:-$UNIT_PARALLEL_DEFAULT_WORKERS}"

    case "$workers" in
        ''|*[!0-9]*)
            echo "LUPIN_UNIT_WORKERS must be a whole number (0 = serial); got '$workers'." >&2
            return 3 ;;
    esac
    [ "$workers" -eq 0 ] && return 0

    local a
    for a in "$@"; do
        case "$a" in
            --collect-only|--co|--pdb|-n|-n*|--numprocesses|--numprocesses=*|--dist|--dist=*|--maxprocesses|--maxprocesses=*) return 0 ;;
        esac
    done
    # `-p no:xdist` arrives as two args; the pair is the caller opting out.
    local prev=""
    for a in "$@"; do
        if [ "$prev" = "-p" ] && [ "$a" = "no:xdist" ]; then return 0; fi
        prev="$a"
    done

    if ! "$( dirname "$pytest_path" )/python" -c "import xdist" 2>/dev/null; then
        echo "" >&2
        echo "REFUSING the unit lane: pytest-xdist is not importable beside $pytest_path." >&2
        echo "  The unit tier runs -n $workers; without xdist it would run serial and take about" >&2
        echo "  four times as long, silently." >&2
        echo "  Install:  uv pip install pytest-xdist  (declared in pyproject.toml's dev group)" >&2
        echo "  Or run serial on purpose:  LUPIN_UNIT_WORKERS=0 <your command>" >&2
        echo "" >&2
        return 3
    fi
    echo "-n $workers"
}
