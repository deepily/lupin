#!/usr/bin/env bash
#
# pre-push-chain.sh: refuse a push whose commits hold a documentation lint finding.
#
# What it checks. Git hands a pre-push hook one line per ref on standard input:
#     <local ref> <local sha> <remote ref> <remote sha>
# For each commit being pushed, this script checks that commit, not the working tree. It checks
# the commit out into a throwaway worktree and runs that commit's own src/tests/run-doclint-gate.sh.
# A dirty working tree, or a push made from another branch, cannot change what is checked.
#
# Install it deliberately, as the pre-commit chain is installed. The hooks directory is shared by
# every worktree, so one link serves them all:
#
#     ln -sf ../../src/scripts/pre-push-chain.sh .git/hooks/pre-push
#
# What it does with each answer from the gate:
#     0        the commit is clean; the push goes on
#     1        a finding remains; the push is refused and the findings are printed
#     other    the gate could not check; the push is refused, because a check that did not
#              run is not a pass
# A commit that has no gate script predates the gate. It is allowed, with a loud line, so an
# old branch can still be pushed. A deleted ref is not checked.
#
# Escape hatch: `git push --no-verify`. The merge pyramid runs the same gate and has no hatch.

set -uo pipefail

ZERO="0000000000000000000000000000000000000000"
GATE_REL="src/tests/run-doclint-gate.sh"

common_dir="$( cd "$( git rev-parse --git-common-dir )" && pwd )"
main_root="$( dirname "$common_dir" )"
scratch=""

cleanup() {
    if [ -n "$scratch" ] && [ -d "$scratch" ]; then
        git -C "$main_root" worktree remove --force "$scratch" > /dev/null 2>&1 || rm -rf "$scratch"
    fi
}
trap cleanup EXIT

check_commit() {
    local sha="$1" rc
    if ! git cat-file -e "$sha:$GATE_REL" 2> /dev/null; then
        echo "[pre-push-chain] SKIPPED doc-lint for ${sha:0:9}: that commit has no $GATE_REL" >&2
        return 0
    fi
    scratch="$main_root/.claude/worktrees/prepush-${sha:0:9}-$$"
    if ! git -C "$main_root" worktree add --detach --quiet "$scratch" "$sha" > /dev/null 2>&1; then
        echo "[pre-push-chain] REFUSED: could not check out ${sha:0:9} to lint it. Nothing was checked." >&2
        scratch=""
        return 2
    fi
    # A fresh worktree has no interpreter of its own; borrow the main tree's.
    if [ -e "$main_root/.venv" ] && [ ! -e "$scratch/.venv" ]; then ln -s "$main_root/.venv" "$scratch/.venv"; fi
    bash "$scratch/$GATE_REL" >&2
    rc=$?
    cleanup
    scratch=""
    return "$rc"
}

seen=""
status=0
while read -r _local_ref local_sha _remote_ref _remote_sha; do
    [ -z "${local_sha:-}" ] && continue
    [ "$local_sha" = "$ZERO" ] && continue
    case " $seen " in *" $local_sha "*) continue ;; esac
    seen="$seen $local_sha"
    check_commit "$local_sha"
    rc=$?
    if [ "$rc" -eq 1 ]; then
        echo "[pre-push-chain] REFUSED the push: ${local_sha:0:9} holds documentation lint findings, listed above." >&2
        echo "[pre-push-chain] Reword them and commit, then push again." >&2
        status=1
    elif [ "$rc" -ne 0 ]; then
        echo "[pre-push-chain] REFUSED the push: the doc-lint gate could not check ${local_sha:0:9} (exit $rc)." >&2
        status=1
    fi
done

exit "$status"
