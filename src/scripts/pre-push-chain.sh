#!/usr/bin/env bash
#
# pre-push-chain.sh: refuse a push whose tip holds a documentation lint finding.
#
# What it checks. Git hands a pre-push hook one line per ref on standard input:
#     <local ref> <local sha> <remote ref> <remote sha>
# This script checks the tip of each pushed ref: the tree the remote will hold after the push.
# It does not check the working tree, and it does not check the commits below a tip.
#
# Whose code does the checking. The gate code and the word list come from the tree this hook is
# installed from. The files that are linted come from the pushed tip, checked out into a
# throwaway worktree. So nothing in the pushed tree can switch the check off: not a deleted gate
# script, not an edited linter, not an emptied word list.
#
# Install it deliberately, as the pre-commit chain is installed. The hooks directory is shared by
# every worktree, so one link serves them all:
#
#     ln -sf ../../src/scripts/pre-push-chain.sh .git/hooks/pre-push
#
# What it does with each answer from the gate:
#     0        the tip is clean; the push goes on
#     1        a finding remains; the push is refused and the findings are printed
#     other    the gate could not check; the push is refused, because a check that did not
#              run is not a pass
# Which tips are held to zero. The hook tree records one commit, the epoch, in
# src/conf/doc-gate-epoch.txt. A tip that descends from the epoch is checked. A tip that does not
# descend from it predates the gate: it is pushed, with a loud line, and meets the pyramid gate
# when it merges. Ancestry cannot be faked by deleting or editing a file in the pushed tree.
#
# It fails closed. A hook tree with no gate script or no readable epoch refuses every push. A
# checked tip with no swept file is refused as unchecked. A deleted ref is not checked.
#
# Escape hatch: `git push --no-verify`. The merge pyramid runs the same gate and has no hatch.

set -uo pipefail

ZERO="0000000000000000000000000000000000000000"

# The tree this hook is installed from: the link in .git/hooks points at this file.
hook_root="$( cd "$( dirname "$( readlink -f "${BASH_SOURCE[0]}" )" )/../.." && pwd )"
gate="$hook_root/src/tests/run-doclint-gate.sh"
epoch_file="$hook_root/src/conf/doc-gate-epoch.txt"

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
    local sha="$1" rc epoch
    if [ ! -f "$gate" ]; then
        echo "[pre-push-chain] REFUSED: no gate script at $gate. Nothing was checked." >&2
        return 2
    fi
    epoch="$( grep -v '^[[:space:]]*\(#\|$\)' "$epoch_file" 2> /dev/null | head -n 1 | tr -d '[:space:]' )"
    if [ -z "$epoch" ] || ! git cat-file -e "${epoch}^{commit}" 2> /dev/null; then
        echo "[pre-push-chain] REFUSED: no usable epoch commit in $epoch_file. Nothing was checked." >&2
        return 2
    fi
    if ! git merge-base --is-ancestor "$epoch" "$sha" 2> /dev/null; then
        echo "[pre-push-chain] SKIPPED doc-lint for ${sha:0:9}: it does not descend from the gate's epoch ${epoch:0:9}, so it predates the gate" >&2
        return 0
    fi
    scratch="$main_root/.claude/worktrees/prepush-${sha:0:9}-$$"
    if ! git -C "$main_root" worktree add --detach --quiet "$scratch" "$sha" > /dev/null 2>&1; then
        echo "[pre-push-chain] REFUSED: could not check out ${sha:0:9} to lint it. Nothing was checked." >&2
        scratch=""
        return 2
    fi
    bash "$gate" --tree "$scratch" >&2
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
