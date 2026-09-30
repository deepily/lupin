#!/usr/bin/env bash
#
# Give a linked worktree the UNTRACKED artifacts it needs to run a whole tier, by
# borrowing the main checkout's — the same move `link-worktree-venv.sh` makes for
# `.venv`, for the members that script does not cover.
#
# THE DEFECT THIS CLOSES (row dde8b87a). The spawn path provisions a `.venv` AND
# NOTHING ELSE, so a spawned seat passes `INTERPRETER OK` and is still unable to run
# its own tier. `INTERPRETER OK` and a TIER-CAPABLE TREE are different claims and the
# spawn path only ever made the first. Measured 2026-09-04: a freshly spawned worktree
# had `.venv` and no `node_modules`, so every `.test.ts` in it died with
# `Cannot find package 'tsx'` — which reads as a broken test, not a missing tree.
#
# ⚠️ THE SET IS COMPUTABLE, NOT DISCOVERABLE. A fresh worktree holds exactly the tracked
# files at its sha, so what git does not track is BY CONSTRUCTION what a worktree lacks:
#     git ls-files --others --ignored --exclude-standard --directory
# The enumeration is arithmetic; the FILTER below is where the judgement lives, and it
# is deliberately short. This script does not try to provision the whole ignored set.
#
# 🔴 THE DENY SIDE IS THE LOAD-BEARING HALF, AND IT IS A RULING, NOT A PREFERENCE.
# NEVER add a secret here — not `src/conf/keys/**` (Mr. Radio's ruling 2026-09-01,
# which overturned earlier advice saying to symlink one), not the repo-root `.env`
# (it carries JWT_SECRET_KEY and POSTGRES_PASSWORD), not
# `src/scripts/auth_migration/migration_results.json` (plaintext passwords). A symlink
# puts a live credential inside a throwaway tree that gets rm -rf'd, copied and shared,
# and the `.venv` precedent makes it look sanctioned. A VENV IS A BUILD ARTIFACT; A KEY
# IS A SECRET. A key-dependent test SKIPS when its key is absent — that is the remedy
# for that family, and it is not this script.
#
# 🔴 AND NEVER ADD A BUILD *OUTPUT*. `src/lupin_app/static/dist/` is untracked and
# absent from every worktree, and it is still out: a symlinked output directory means a
# build run in a throwaway tree writes into the SHARED checkout. `node_modules` is on
# the borrow side for the same reason `.venv` is — nobody runs `npm install` in a
# worktree, `package.json` and `package-lock.json` are tracked, and the failure mode of
# not having it is a test suite that cannot start.
#
# Usage:
#   src/scripts/link-worktree-artifacts.sh            # provision the tree you are in
#   src/scripts/link-worktree-artifacts.sh <path>     # provision another worktree
#   src/scripts/link-worktree-artifacts.sh --check    # report, change nothing
#
# Machine-readable output — the caller parses these keys, one per line, never the prose:
#   LINKED=<rel>          a symlink was created and verified
#   ALREADY=<rel>         something is already there and resolves — left alone, whether
#                         it is our symlink or a real file the seat put there itself
#   SOURCE_ABSENT=<rel>   the MAIN checkout does not have it either — nothing to borrow
#   REFUSED=<rel>         the link could not be created
#
# Exit codes:
#   0  every borrowable artifact is now present (or the main checkout has none to lend)
#   2  bad arguments, missing directory, or not a git repository
#   3  the target IS the main checkout — a correct no-op, it owns the real artifacts
#   5  a link could not be created (permissions, a racing writer)
#   6  a link was created but does not resolve — never report success on an unverified tree

set -euo pipefail

# ── THE BORROW LIST ───────────────────────────────────────────────────────────────
#
# Relative paths, borrowed from the main checkout by symlink. Read the DENY notes above
# before adding a line here. Each entry must be (a) untracked, (b) not a secret, (c) not
# a build output the worktree itself would write to, and (d) genuinely reached by code
# from inside a worktree — classified by READING the call sites, never by grepping for
# the name (`lupin-auth.db` has eight references and every one is a tmp_path or a mock).
BORROW=(
    # 215 entries, .gitignore:193. Without it every `.test.ts` dies naming a PACKAGE
    # (`Cannot find package 'tsx'`) rather than a tree, which is why this member went
    # unfound while the other two were documented.
    "node_modules"
    # .gitignore:79. Its own header reads "No secrets here - project id + AR repo only";
    # it is deploy CONFIG. Without it 9 unit tests go red naming the GCP project-id variable,
    # and the fleet currently subtracts those by hand every time — a habit, not a control.
    #
    # ⚠️ THAT VARIABLE IS NAMED IN PROSE HERE ON PURPOSE, NOT SPELLED. `test_no_hardcoded_gcp
    # _identifiers.py::test_every_script_touching_the_project_id_fails_loud_or_sources_the
    # _resolver` is an UNBOUNDED TEXT SCAN — `if "<the var>" not in body: continue` over the
    # whole file, comments included — and it demands that any .sh mentioning it either source
    # `cloud-run-config.sh` or use the fail-loud `:?` form. Spelling it in a comment tripped
    # that guard and reddened the unit tier, which is a 100% merge gate.
    #
    # 🔴 DO NOT SATISFY THE GUARD THE OTHER WAY. Adding `${<the var>:?...}` here would also
    # pass — by giving a provisioning script a real GCP dependency it has never had and does
    # not want. The guard offers two escapes and only one of them is honest for this file.
    # This script reads no GCP configuration; it only ever LINKS the file that carries it.
    "src/scripts/cloud-run.env"
)

TARGET="${1:-$PWD}"
CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=1
    TARGET="${2:-$PWD}"
fi

if [[ ! -d "$TARGET" ]]; then
    echo "ERROR: not a directory: $TARGET" >&2
    exit 2
fi

# 🔴 NO PIPE HERE, DELIBERATELY — the same SIGPIPE race documented at length in
# `link-worktree-venv.sh` (row f8f7d54b): a short-circuiting reader closes the pipe
# while git is still writing a 100+ entry worktree list, git takes SIGPIPE, and
# `pipefail` + `set -e` turn that into a silent exit 141 that reads like success.
if ! WORKTREE_LIST="$( git -C "$TARGET" worktree list --porcelain 2>/dev/null )"; then
    WORKTREE_LIST=""
fi

MAIN_REPO=""
while IFS= read -r line; do
    if [[ "$line" == "worktree "* ]]; then
        MAIN_REPO="${line#worktree }"
        break
    fi
done <<< "$WORKTREE_LIST"
if [[ -z "$MAIN_REPO" ]]; then
    echo "ERROR: $TARGET is not inside a git repository" >&2
    exit 2
fi

if [[ "$( cd "$TARGET" && pwd -P )" == "$( cd "$MAIN_REPO" && pwd -P )" ]]; then
    if [[ $CHECK_ONLY -eq 1 ]]; then
        echo "MAIN: $TARGET is the main checkout - it owns the real artifacts"
        exit 0
    fi
    echo "REFUSING: $TARGET is the MAIN repo, which owns the real artifacts."
    echo "  Linking them to themselves would replace real files with loops."
    exit 3
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
    missing=0
    for rel in "${BORROW[@]}"; do
        if [[ -e "$TARGET/$rel" ]]; then
            echo "ALREADY=$rel"
        elif [[ ! -e "$MAIN_REPO/$rel" ]]; then
            echo "SOURCE_ABSENT=$rel"
        else
            echo "MISSING=$rel" >&2
            missing=$(( missing + 1 ))
        fi
    done
    if [[ $missing -gt 0 ]]; then
        echo "  $missing borrowable artifact(s) absent here and present in $MAIN_REPO." >&2
        echo "  Fix: src/scripts/link-worktree-artifacts.sh" >&2
        exit 1
    fi
    exit 0
fi

REFUSED=0
for rel in "${BORROW[@]}"; do
    source_path="$MAIN_REPO/$rel"
    link="$TARGET/$rel"

    if [[ -e "$link" || -L "$link" ]]; then
        if [[ -e "$link" ]]; then
            echo "ALREADY=$rel"
            continue
        fi
        # A dangling symlink is the one case worth clearing: it is ours and it is broken.
        echo "Replacing a dangling symlink at $link" >&2
        rm "$link"
    fi

    if [[ ! -e "$source_path" ]]; then
        # Fail-open and SAY SO. A main checkout that never ran `npm install` has nothing
        # to lend; that is not this script's failure and must not take a spawn down.
        echo "SOURCE_ABSENT=$rel"
        continue
    fi

    # The parent must exist before the link can. Only ever a directory INSIDE the
    # worktree, and only ever one git already tracks (`src/scripts`), so this creates
    # nothing surprising.
    parent="$( dirname "$link" )"
    if [[ ! -d "$parent" ]]; then
        mkdir -p "$parent"
    fi

    if ! ln -s "$source_path" "$link" 2>/dev/null; then
        echo "REFUSED=$rel"
        echo "ERROR: could not create $link" >&2
        REFUSED=$(( REFUSED + 1 ))
        continue
    fi

    # Verify rather than assume: a symlink that resolves to nothing looks identical to
    # success from the exit code of `ln`.
    if [[ ! -e "$link" ]]; then
        echo "ERROR: created $link but it resolves to nothing" >&2
        exit 6
    fi
    echo "LINKED=$rel"
done

if [[ $REFUSED -gt 0 ]]; then
    exit 5
fi
