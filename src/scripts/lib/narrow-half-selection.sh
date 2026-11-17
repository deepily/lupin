#!/usr/bin/env bash
# narrow_half_selection — let a caller's test-file argument narrow a --half run, or refuse it.
#
# Row 65366428: `--half a` set SELECTED_TESTS to every file in the half manifest and appended
# the caller's path after it. A path already in the half adds nothing to pytest's file list, so
# the whole half ran with no refusal and no notice.
#
# Reads and writes two caller arrays: SELECTED_TESTS (the half's files) and REMAINING_ARGS (the
# caller's pytest args). An arg is a test path when it names a `.py` file, with or without a
# `::node` suffix. Option values such as `-k expr` never end in `.py`, so they pass through.
#
# No path args  -> arrays unchanged, returns 0.
# Every path is a file in the half and exists on disk
#               -> SELECTED_TESTS becomes those args (node ids kept), they leave REMAINING_ARGS.
# Any other path -> prints the path and the cause, returns 2. Nothing is narrowed silently.
narrow_half_selection() {
    local root="$1" arg file listed
    local -a paths=() others=()
    for arg in "${REMAINING_ARGS[@]}"; do
        file="${arg%%::*}"
        file="${file#./}"
        case "$file" in
            *.py) paths+=( "$arg" ) ;;
            *)    others+=( "$arg" ) ;;
        esac
    done
    if [ "${#paths[@]}" -eq 0 ]; then
        return 0
    fi
    for arg in "${paths[@]}"; do
        file="${arg%%::*}"
        file="${file#./}"
        if [ ! -f "$root/$file" ]; then
            echo "[ERROR] --half: test path does not exist: $file"
            return 2
        fi
        listed=false
        for member in "${SELECTED_TESTS[@]}"; do
            if [ "$member" = "$file" ]; then listed=true; break; fi
        done
        if [ "$listed" != true ]; then
            echo "[ERROR] --half: test path is not in this half's manifest: $file"
            return 2
        fi
    done
    SELECTED_TESTS=( "${paths[@]#./}" )
    REMAINING_ARGS=( "${others[@]}" )
    return 0
}
