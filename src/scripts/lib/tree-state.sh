#!/bin/bash
# Emit the canonical [tree-state] line from a runner that is not pytest.
#
# WHY THIS EXISTS: the root conftest's terminal-summary hook reaches every pytest tier
# and nothing else, so the node/c8 runners produced greens carrying no tree at all --
# the larger half of the original ask by surface area (store row 11253df9, gap 3).
#
# WHY IT SHELLS OUT INSTEAD OF RE-DERIVING: a shell function with its own git calls is a
# SECOND implementation of one contract, and two implementations drift. That is the exact
# failure row e2099400 keeps finding. This runs the same module conftest imports, so both
# paths render the same line from the same code.
#
# Design: src/rnd/v0.2.0/2026.08.26-every-green-states-its-tree.md §6b. — REMOVED by c752ab9e (2026-08-29); recover: git show c752ab9e^:src/rnd/v0.2.0/2026.08.26-every-green-states-its-tree.md

emit_tree_state() {
    # NEVER fails the caller. A runner that dies while reporting which tree it ran on has
    # destroyed the result it was describing; the module already exits 0 on its own
    # internal failure, and `|| true` covers the case where python itself is unavailable.
    #
    # 🔴 `${PYTHONPATH:-}` — THE `:-` IS LOAD-BEARING AND ITS ABSENCE COST A WHOLE TIER.
    # This line read `${PYTHONPATH}` until 2026-09-06. Callers run under `set -u`, where an
    # unset variable is fatal DURING PARAMETER EXPANSION — before the command is built — so
    # `|| true` never gets the chance to catch it and the comment three lines above was
    # false about its own function. Measured: run-typescript-tests.sh died in 0.9s on :8000
    # with "tree-state.sh: line 20: PYTHONPATH: unbound variable", executed ZERO tests, and
    # was read as "the multiplexer tier cannot see coverage at all" — c8 was never reached.
    # ⚠️ IT FAILED ONLY WHERE NOBODY WATCHES: every seat's shell exports PYTHONPATH, so it
    # is immune interactively; the :8000 container has none. A defect visible only in the
    # venue nobody runs by hand.
    local root="${LUPIN_ROOT:-$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )}"
    PYTHONPATH="$root/src:${PYTHONPATH:-}" python3 -m cosa.utils.tree_state 2>/dev/null || true
}
