#!/usr/bin/env bash
#
# Install the two git hooks this checkout ships, as links.
#
#   pre-commit  ->  src/scripts/pre-commit-chain.sh
#   pre-push    ->  src/scripts/pre-push-chain.sh
#
# A hook lives in the git hooks folder, which git does not carry, so every fresh clone and
# every updated VM starts without one. `lupin-vm.sh deploy` runs this after the checkout.
#
# Usage:
#   src/scripts/install-git-hooks.sh              # make the two links; leave anything in the way
#   src/scripts/install-git-hooks.sh --replace    # move what is in the way to <name>.bak-<epoch>
#
# Exit codes:  0 both links right  ·  1 something was in the way  ·  2 could not run
#
# The two names and the two targets are fixed below. The only argument is --replace, and
# the environment is not consulted for a target, so no input can point a link somewhere else.
# The tree is the one this script sits in; $LUPIN_ROOT is deliberately not consulted.
#
set -uo pipefail

# The real path first: reached through a link, the tree is the one the script lives in, not the link's folder.
SELF="$( readlink -f "${BASH_SOURCE[0]}" )"
ROOT="$( cd "$( dirname "$SELF" )/../.." && pwd )"

REPLACE=0
case "${1:-}" in
    "")        ;;
    --replace) REPLACE=1 ;;
    *)         echo "install-git-hooks: unknown argument '$1' (the only option is --replace)" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { echo "install-git-hooks: too many arguments (the only option is --replace)" >&2; exit 2; }

HOOK_NAMES=( pre-commit pre-push )
HOOK_SCRIPTS=( pre-commit-chain.sh pre-push-chain.sh )

# 1. every chain script must exist before any link is made — no partial install.
for script in "${HOOK_SCRIPTS[@]}"; do
    if [ ! -f "$ROOT/src/scripts/$script" ]; then
        echo "install-git-hooks: REFUSED — this checkout has no src/scripts/$script, so it predates the hook. Update the checkout first. Nothing was changed." >&2
        exit 2
    fi
done

# 2. the folder git itself runs hooks from (follows core.hooksPath).
# GIT_DIR and friends would move the folder, so they are dropped for this one lookup.
hooks_path="$( env -u GIT_DIR -u GIT_COMMON_DIR -u GIT_WORK_TREE -u GIT_CEILING_DIRECTORIES \
    git -c "safe.directory=$ROOT" -C "$ROOT" rev-parse --git-path hooks 2>/dev/null )" || hooks_path=""
if [ -z "$hooks_path" ]; then
    echo "install-git-hooks: $ROOT is not a git tree, so there is no hooks folder. Nothing was changed." >&2
    exit 2
fi
case "$hooks_path" in
    /*) HOOKS_DIR="$hooks_path" ;;
    *)  HOOKS_DIR="$ROOT/$hooks_path" ;;
esac

# 2b. a linked worktree shares the main checkout's hooks folder, so a link made from here would
# point every worktree's hooks at this one tree, and dangle once this tree is removed.
git_dir="$( env -u GIT_DIR -u GIT_COMMON_DIR -u GIT_WORK_TREE -u GIT_CEILING_DIRECTORIES \
    git -c "safe.directory=$ROOT" -C "$ROOT" rev-parse --absolute-git-dir 2>/dev/null )" || git_dir=""
common_dir="$( env -u GIT_DIR -u GIT_COMMON_DIR -u GIT_WORK_TREE -u GIT_CEILING_DIRECTORIES \
    git -c "safe.directory=$ROOT" -C "$ROOT" rev-parse --git-common-dir 2>/dev/null )" || common_dir=""
case "$common_dir" in /*) ;; *) common_dir="$ROOT/$common_dir" ;; esac
if [ "$( readlink -f "$git_dir" )" != "$( readlink -f "$common_dir" )" ]; then
    echo "install-git-hooks: REFUSED — $ROOT is a linked worktree, and its hooks folder is shared with the main checkout. Run this from the main checkout. Nothing was changed." >&2
    exit 2
fi

# 2c. only now create the folder, so a refused run creates nothing.
mkdir -p "$HOOKS_DIR" || { echo "install-git-hooks: could not create $HOOKS_DIR" >&2; exit 2; }

# 3. look before touching anything: a blocked hook without --replace stops the whole run.
blocked=0
for i in "${!HOOK_NAMES[@]}"; do
    name="${HOOK_NAMES[$i]}"; want="$ROOT/src/scripts/${HOOK_SCRIPTS[$i]}"; path="$HOOKS_DIR/$name"
    if [ -e "$path" ] || [ -L "$path" ]; then
        if [ -L "$path" ] && [ "$( readlink -f "$path" )" = "$( readlink -f "$want" )" ]; then continue; fi
        if [ "$REPLACE" -eq 0 ]; then
            if [ -L "$path" ]; then
                echo "$name: IN THE WAY — a link to $( readlink "$path" ), not to src/scripts/${HOOK_SCRIPTS[$i]} (re-run with --replace to move it aside)"
            else
                if [ -d "$path" ]; then kind="a directory"; elif [ -f "$path" ]; then kind="a regular file"; else kind="something that is neither a file nor a link"; fi
                echo "$name: IN THE WAY — $kind at $path (re-run with --replace to move it aside)"
            fi
            blocked=1
        fi
    fi
done
if [ "$blocked" -eq 1 ]; then
    echo "install-git-hooks: nothing was changed — fix what is in the way, or use --replace"
    exit 1
fi

# 4. make the links.
stamp="$( date +%s )"
for i in "${!HOOK_NAMES[@]}"; do
    name="${HOOK_NAMES[$i]}"; want="$ROOT/src/scripts/${HOOK_SCRIPTS[$i]}"; path="$HOOKS_DIR/$name"
    if [ -L "$path" ] && [ "$( readlink -f "$path" )" = "$( readlink -f "$want" )" ]; then
        echo "$name: already there ($path)"
        continue
    fi
    if [ -e "$path" ] || [ -L "$path" ]; then
        mv "$path" "$path.bak-$stamp" || { echo "install-git-hooks: could not move $path aside" >&2; exit 2; }
        echo "$name: moved the old one aside to $path.bak-$stamp"
    fi
    ln -s "$want" "$path" || { echo "install-git-hooks: could not link $path" >&2; exit 2; }
    echo "$name: linked $path -> $want"
done
echo "install-git-hooks: both hooks are links to the scripts this checkout ships ($HOOKS_DIR)"
exit 0
