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
# Design: src/rnd/v0.2.0/2026.08.26-every-green-states-its-tree.md §6b.

emit_tree_state() {
    # NEVER fails the caller. A runner that dies while reporting which tree it ran on has
    # destroyed the result it was describing; the module already exits 0 on its own
    # internal failure, and `|| true` covers the case where python itself is unavailable.
    local root="${LUPIN_ROOT:-$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )}"
    PYTHONPATH="$root/src:${PYTHONPATH}" python3 -m cosa.utils.tree_state 2>/dev/null || true
}
