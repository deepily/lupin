"""
Worktree false-green guard (row a9f87d29, candidate 5 — Rachel-ratified 2026-08-16).

THE TRAP. `conftest.py` inserts `$LUPIN_ROOT/src` at `sys.path[0]`, so every test
imports `cosa` from the tree LUPIN_ROOT names. Run a test file that lives in a git
WORKTREE while LUPIN_ROOT still points at the MAIN tree and the import silently comes
from the OTHER tree: a revert-to-verify / RED check reports GREEN because it exercised
the wrong tree's code. Proven 2026-08-16 — a worktree RED check ran 44-green until
LUPIN_ROOT was set to the worktree, then flipped to 8 RED / 36 green (the truth).

THE GUARD. At collection, compare the git-tree-root of each collected test FILE against
the git-tree-root of LUPIN_ROOT. They disagree => the file is imported from a different
tree than it lives in => false-green risk => fail loud. The three cases (candidate 5):

  - worktree file + LUPIN_ROOT = same worktree (correct setup)      -> SILENT
  - main-tree file + LUPIN_ROOT = main tree (the common live case)  -> SILENT
  - worktree file + LUPIN_ROOT = a DIFFERENT tree (the trap)        -> FIRES

FAIL-SAFE. Fire ONLY when BOTH tree roots resolve AND differ. Any uncertainty — a path
whose tree root cannot be found, LUPIN_ROOT unset — returns None (SILENT). A guard that
runs for every session's every test run must never misfire on a correct setup; the cost
of a missed trap is a re-derivation, the cost of a false fire is the whole fleet's runs.

This module is import-clean and pure so it is unit-testable in BOTH directions without a
container or a real worktree (mirrors tests/venue_routing.py); conftest is the thin wiring.
"""

import fnmatch
import os


def git_tree_root( start_path ):
    """
    The git tree root that owns `start_path`: the nearest ancestor holding a `.git`
    entry (a DIRECTORY in a normal checkout, a FILE in a linked worktree).

    Requires:
        - start_path is a filesystem path string (need not exist; walked as text +
          realpath)

    Ensures:
        - Returns the realpath of the owning tree root, or None when no ancestor holds
          a `.git` entry (uncertainty => None, so the caller stays silent)
    """
    current = os.path.realpath( start_path )
    if not os.path.isdir( current ):
        current = os.path.dirname( current )

    while True:
        if os.path.exists( os.path.join( current, ".git" ) ):
            return current
        parent = os.path.dirname( current )
        if parent == current:          # reached filesystem root without a .git
            return None
        current = parent


def tree_mismatch( file_path, lupin_root ):
    """
    Whether a collected test file would be imported from a different tree than it lives in.

    Requires:
        - file_path is the path of a collected test file
        - lupin_root is the LUPIN_ROOT value (may be None)

    Ensures:
        - Returns { "file_tree", "lupin_tree", "file" } when BOTH tree roots resolve
          AND differ (the trap — FIRES)
        - Returns None when lupin_root is falsy, either tree root cannot be resolved,
          or the two roots match (SILENT — fail-safe on any uncertainty)
    """
    if not lupin_root:
        return None

    file_tree  = git_tree_root( file_path )
    lupin_tree = git_tree_root( lupin_root )
    if file_tree is None or lupin_tree is None:
        return None
    if file_tree == lupin_tree:
        return None

    return { "file_tree": file_tree, "lupin_tree": lupin_tree, "file": os.path.realpath( file_path ) }


def check_paths( file_paths, lupin_root ):
    """
    Scan collected test file paths for a tree mismatch and build the fail-loud message.

    Requires:
        - file_paths is an iterable of test file path strings
        - lupin_root is the LUPIN_ROOT value (may be None)

    Ensures:
        - Returns None when no path mismatches (SILENT)
        - Otherwise returns a multi-line diagnostic naming the first offending file,
          its tree, and the LUPIN_ROOT tree — the message a reviewer needs to see that
          their worktree RED check tested the WRONG tree
        - Resolves each unique parent directory at most once (a collection is thousands
          of items sharing few directories)
    """
    seen_dir = {}
    for file_path in file_paths:
        parent = os.path.dirname( os.path.realpath( file_path ) )
        if parent not in seen_dir:
            seen_dir[ parent ] = tree_mismatch( file_path, lupin_root )
        hit = seen_dir[ parent ]
        if hit is not None:
            return (
                "WORKTREE FALSE-GREEN GUARD (row a9f87d29): the test file being collected "
                "lives in a DIFFERENT git tree than LUPIN_ROOT, so it is imported from the "
                "WRONG tree and any pass/fail is a lie.\n"
                f"  test file  : {hit[ 'file' ]}\n"
                f"  its tree   : {hit[ 'file_tree' ]}\n"
                f"  LUPIN_ROOT : {hit[ 'lupin_tree' ]}\n"
                "Fix: set LUPIN_ROOT to the tree the test files live in "
                "(export LUPIN_ROOT=<that worktree>) before running these tests."
            )
    return None


def is_test_file( file_path, patterns ):
    """
    Whether pytest would treat `file_path` as a test module, by the SAME `python_files`
    patterns pytest itself uses.

    THE REASON THIS IS NOT A HARDCODED "test_*.py": the caller passes
    `config.getini( "python_files" )`, so the filter tracks pytest.ini rather than a
    second copy of it that can drift. A conftest.py is offered to `pytest_collect_file`
    too, and naming one as "the test file being collected" would send a reader to the
    wrong file.

    Requires:
        - file_path is a path string
        - patterns is an iterable of glob patterns (pytest's `python_files`)

    Ensures:
        - Returns True when the BASENAME matches at least one pattern, else False
    """
    name = os.path.basename( file_path )
    for pattern in patterns:
        if fnmatch.fnmatch( name, pattern ):
            return True
    return False


def paths_to_scan( item_paths, collected_file_paths ):
    """
    Which paths the mismatch check should read — closing the ZERO-ITEM BLIND SPOT (row
    08f6be8e).

    THE GAP THIS FILLS, measured 2026-08-29 in a worktree with LUPIN_ROOT pointing at the
    main tree: a module that skips at module level, or a file holding no test functions,
    produces ZERO items. The guard was handed a list built from `items`, so it had nothing
    to scan and stayed SILENT — the run exits 5, but the reader is told "1 skipped" instead
    of "LUPIN_ROOT points at another tree". The files pytest WALKED are known even when no
    item survives, so they are what to fall back to.

    ⚠️ THIS DOES NOT MAKE EMPTINESS AN ERROR, and that distinction is the whole design.
    The condition being reported is a TREE MISMATCH, which is wrong at any item count; an
    empty selection on its own stays exactly as pytest already renders it (exit 5). A `-k`
    that deliberately matches nothing in a correctly-configured tree is untouched here,
    because the mismatch predicate never fires on it. A guard that cried wolf on every
    empty run would earn an escape hatch within a week and become decoration.

    Requires:
        - item_paths is a list of paths of the items that survived collection
        - collected_file_paths is a list of test-file paths pytest walked

    Ensures:
        - Returns item_paths when it is non-empty (the live case is byte-for-byte
          unchanged — the fallback can only ADD coverage, never alter an existing verdict)
        - Returns collected_file_paths when no item survived
    """
    if item_paths:
        return item_paths
    return collected_file_paths
