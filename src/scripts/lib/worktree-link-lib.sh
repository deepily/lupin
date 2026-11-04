#!/usr/bin/env bash
# Shared plumbing of the three seat-worktree scripts: link-worktree-venv.sh,
# link-worktree-artifacts.sh and provision-seat-worktree.sh.
#
# Each of them has to find the main checkout of the repository a directory belongs to, and to
# ask whether a directory is that main checkout. They carried their own copy of both, word for
# word, and a fix to one had to be made three times. This file holds the one copy.
#
# Source it from the script that uses it, then call the functions:
#   source "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/lib/worktree-link-lib.sh"
#
# It sets no shell options and never exits. The caller decides what a failure means and which
# message to print, so each script keeps its own wording and its own exit codes.
#
# lupin-mobile carries a byte-identical copy of this file, because its own three scripts have the
# same two needs. src/tests/unit/test_worktree_link_lib.py compares the two copies and skips,
# naming the file to add, while the sibling has none.

# Find the main checkout of the repository that holds a directory.
#
# Requires: $1 is an existing directory.
# Ensures:  WT_LIST holds the output of `git worktree list --porcelain`, or nothing when git failed.
#           WT_MAIN holds the path of the first worktree in it, the primary tree, or nothing.
#           Returns 0 when WT_MAIN is set and 1 when the directory is not inside a git repository.
#
# 🔴 NO PIPE HERE, DELIBERATELY (row f8f7d54b). This used to read
#     git ... worktree list --porcelain | awk '/^worktree /{print $2; exit}'
# and died with SIGPIPE on 17 of 30 runs on a box with 152 lines of worktree list: awk closes
# the pipe on its first match while git is still writing, git takes SIGPIPE, and `pipefail` plus
# `set -e` turn that into a silent exit 141 before any message of the caller's own. To a caller
# it reads exactly like "ran fine, nothing to do". The failure rate rises with the length of
# git's output, which is why its author never saw it. Reading the whole output into a variable
# first is the shape that cannot race: there is no reader to close early. Bonus:
# `${line#worktree }` keeps a path that contains spaces, which awk '{print $2}' cut at the first.
wt_resolve_main() {
    local dir="$1" line
    if ! WT_LIST="$( git -C "$dir" worktree list --porcelain 2>/dev/null )"; then
        WT_LIST=""
    fi
    WT_MAIN=""
    while IFS= read -r line; do
        if [[ "$line" == "worktree "* ]]; then
            WT_MAIN="${line#worktree }"
            break
        fi
    done <<< "$WT_LIST"
    [[ -n "$WT_MAIN" ]]
}

# Say whether two directories are the same directory, symlinks resolved.
#
# Requires: $1 and $2 are existing directories.
# Ensures:  returns 0 when both resolve to one physical path and 1 when they do not.
wt_same_dir() {
    [[ "$( cd "$1" && pwd -P )" == "$( cd "$2" && pwd -P )" ]]
}
