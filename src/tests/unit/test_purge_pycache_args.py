"""
Argument-surface tests for `src/scripts/purge-pycache.sh`.

WHY THESE EXIST. The script parsed its whole command line with one line —
`[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1` — so anything that was not exactly
`--dry-run` in position one fell through to a REAL purge. Two live spellings of
that: a typo (`--dryrun`), and a correct flag in position two
(`purge-pycache.sh foo --dry-run`).

The silent path here is the destructive one, which is what makes it worth a test.
An operator asking to PREVIEW a purge got the purge, exit 0, and output that reads
like a successful run. Its sibling `migrate-pyc-to-checked-hash.sh` already refuses
unknown options with usage and exit 2, and says so in its own help text: "Every
argument is honoured or refused — never silently discarded." This closes the same
surface on the purge script.

The discriminating assertion in each rejection case is not the exit code — it is
that the planted cache SURVIVES. An exit code says what the script decided; the
surviving directory says what it did.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path( __file__ ).resolve().parents[ 3 ] / "src" / "scripts" / "purge-pycache.sh"


@pytest.fixture
def planted_root( tmp_path ):
    """
    Requires:
        - tmp_path is an existing empty directory

    Ensures:
        - returns a directory usable as LUPIN_ROOT holding exactly one
          src/pkg/__pycache__ with a file in it
        - the real repository tree is never the target of a run
    """
    cache = tmp_path / "src" / "pkg" / "__pycache__"
    cache.mkdir( parents=True )
    ( cache / "mod.cpython-313.pyc" ).write_bytes( b"not really bytecode" )
    return tmp_path


def _run( root, *args ):
    """
    Requires:
        - root is a directory to be used as LUPIN_ROOT
        - args are the command-line arguments under test

    Ensures:
        - returns the CompletedProcess with stdout/stderr captured as text
        - LUPIN_ROOT is pinned to root, so no run can reach the real tree
    """
    env = dict( os.environ, LUPIN_ROOT=str( root ) )
    return subprocess.run( [ str( SCRIPT ), *args ], capture_output=True, text=True, env=env )


def _caches( root ):
    return list( root.rglob( "__pycache__" ) )


def test_the_no_flag_arm_still_purges( planted_root ):
    """
    THE POSITIVE CONTROL, and the arm this file was missing until Krishna ran it
    by hand. Every other test here asserts the script did NOT purge, and a suite
    made only of those is satisfied by a script that never purges at all -- the
    refusals would all pass against a no-op. This is the one that fails if the
    argument loop or the preflight ever refuses the ordinary case.
    """
    ( planted_root / "src" / "other" / "__pycache__" ).mkdir( parents=True )
    assert len( _caches( planted_root ) ) == 2

    env = dict( os.environ, LUPIN_ROOT=str( planted_root ), PYTHON=sys.executable )
    result = subprocess.run( [ str( SCRIPT ) ], capture_output=True, text=True, env=env )

    assert result.returncode == 0, result.stderr
    assert _caches( planted_root ) == []


def test_a_mistyped_dry_run_is_refused_and_purges_nothing( planted_root ):
    result = _run( planted_root, "--dryrun" )

    # The cache surviving is the real assertion — under the one-line parser this
    # spelling fell through to a real purge and removed it.
    assert _caches( planted_root ), "a mistyped flag purged the tree"
    assert result.returncode == 2
    assert "--dryrun" in result.stderr


def test_a_correct_flag_in_position_two_is_not_silently_ignored( planted_root ):
    # The old parser read $1 only, so the --dry-run here was discarded and the
    # stray positional was never refused: the operator asked to preview and purged.
    result = _run( planted_root, "stray", "--dry-run" )

    assert _caches( planted_root ), "a stray positional turned a preview into a purge"
    assert result.returncode == 2
    assert "stray" in result.stderr


def test_dry_run_still_previews_and_removes_nothing( planted_root ):
    result = _run( planted_root, "--dry-run" )

    assert result.returncode == 0
    assert _caches( planted_root )
    assert "Would remove" in result.stdout


def test_a_missing_interpreter_refuses_before_purging_anything( planted_root ):
    """
    The script promises purge and reconvert "cannot be half-done". The reconvert
    needs an interpreter; 35 of this repo's 80 worktrees have no .venv/bin/python.
    Before the preflight, running here purged and THEN failed, leaving the tree on
    timestamp invalidation -- the defect row 866f43ce closed -- and reported it at
    the moment it was too late to decline.
    """
    env = dict( os.environ, LUPIN_ROOT=str( planted_root ),
                PYTHON=str( planted_root / "no-such-interpreter" ) )
    result = subprocess.run( [ str( SCRIPT ) ], capture_output=True, text=True, env=env )

    # Survival first: the exit code says what it decided, the directory says what it did.
    assert _caches( planted_root ), "purged despite having no interpreter to reconvert with"
    assert result.returncode == 2
    assert "Refusing to purge" in result.stderr


def test_the_interpreter_default_matches_the_script_it_calls():
    """
    The preflight duplicates migrate-pyc-to-checked-hash.sh's PYTHON resolution.
    Duplication is the point -- it must fail closed BEFORE the purge -- so this
    fails if the two ever drift apart.
    """
    default = 'PYTHON="${PYTHON:-$LUPIN_ROOT/.venv/bin/python}"'
    sibling = SCRIPT.parent / "migrate-pyc-to-checked-hash.sh"

    assert default in SCRIPT.read_text()
    assert default in sibling.read_text()


def test_help_exits_zero_and_removes_nothing( planted_root ):
    result = _run( planted_root, "--help" )

    assert result.returncode == 0
    assert _caches( planted_root )
    assert "Usage: purge-pycache.sh" in result.stdout
