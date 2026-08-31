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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path( __file__ ).resolve().parents[ 3 ] / "src" / "scripts" / "purge-pycache.sh"


def _plant_tree( root ):
    """
    Requires:
        - root is a path that may or may not exist yet

    Ensures:
        - root is a self-contained fake checkout: src/scripts/ holding COPIES of
          purge-pycache.sh and the migrate script it chains to, plus one
          src/pkg/__pycache__
        - returns the path of the purge script INSIDE that tree

    Copies rather than pointing the real script at a temp directory, because the
    behaviour under test is precisely that the script cleans THE TREE IT SITS IN.
    A test that ran the repo's own copy could not observe that property, and after
    the LUPIN_ROOT override was dropped it would purge this worktree for real.
    """
    scripts = root / "src" / "scripts"
    scripts.mkdir( parents=True )
    for name in ( "purge-pycache.sh", "migrate-pyc-to-checked-hash.sh" ):
        target = scripts / name
        shutil.copy2( SCRIPT.parent / name, target )
        target.chmod( 0o755 )

    cache = root / "src" / "pkg" / "__pycache__"
    cache.mkdir( parents=True )
    ( cache / "mod.cpython-313.pyc" ).write_bytes( b"not really bytecode" )
    return scripts / "purge-pycache.sh"


@pytest.fixture
def planted_root( tmp_path ):
    """
    Requires:
        - tmp_path is an existing empty directory

    Ensures:
        - returns a fake checkout holding its own copy of the script under test
        - the real repository tree is never the target of a run
    """
    _plant_tree( tmp_path )
    return tmp_path


def _run( root, *args ):
    """
    Requires:
        - root is a fake checkout produced by _plant_tree

    Ensures:
        - runs THAT TREE'S copy of the script, which is the only way to address a
          tree now that the environment override is gone
        - LUPIN_ROOT is deliberately left pointing somewhere else, so every case
          here doubles as evidence that it is ignored
    """
    env = dict( os.environ, LUPIN_ROOT="/nonexistent-elsewhere" )
    return subprocess.run( [ str( root / "src" / "scripts" / "purge-pycache.sh" ), *args ],
                           capture_output=True, text=True, env=env )


def _caches( root ):
    return list( root.rglob( "__pycache__" ) )


def test_it_cleans_its_own_tree_and_leaves_the_one_lupin_root_names_alone( tmp_path ):
    """
    POCHOLO'S CASE (📣, 2026-08-30 ~17:52), and the worst on this file: it damages a
    tree the operator does not own. `LUPIN_ROOT` is exported by every seat's shell
    pointing at the MAIN checkout, and the old line

        LUPIN_ROOT="${LUPIN_ROOT:-<derived from BASH_SOURCE>}"

    had a correct fallback that a SET variable simply beat. Running the worktree's
    own copy purged /…/lupin — measured at 188 directories from this worktree —
    printed its success banner, and left the worktree as poisoned as it found it.

    ASSERTS ON BOTH TREES ON PURPOSE. Checking only that the calling tree was
    cleaned is satisfied by a script that cleaned NEITHER; checking only that the
    other tree survived is satisfied by a script that did nothing at all. One
    assertion each way is what distinguishes "targeted the right tree" from
    "happened not to run".
    """
    caller = tmp_path / "caller"
    other  = tmp_path / "other"
    script = _plant_tree( caller )
    _plant_tree( other )

    env = dict( os.environ, LUPIN_ROOT=str( other ), PYTHON=sys.executable )
    result = subprocess.run( [ str( script ) ], capture_output=True, text=True, env=env )

    assert result.returncode == 0, result.stderr
    assert _caches( caller ) == [], "the calling tree was not cleaned"
    assert _caches( other ),        "purged the tree LUPIN_ROOT named, not its own"


def test_the_scripts_do_not_consult_lupin_root_for_their_root( ):
    """
    The remedy is the ABSENCE of an override, which no behavioural test can show
    directly -- a passing run cannot prove the variable was never read. This holds
    the shape instead, on both scripts, because Pocholo's entry says the same
    defect lives in the one this chains to.
    """
    derived = 'LUPIN_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"'
    overridden = 'LUPIN_ROOT="${LUPIN_ROOT:-'

    for name in ( "purge-pycache.sh", "migrate-pyc-to-checked-hash.sh" ):
        text = ( SCRIPT.parent / name ).read_text()
        assert derived in text, name
        assert overridden not in text, name


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
    result = subprocess.run( [ str( planted_root / "src" / "scripts" / "purge-pycache.sh" ) ],
                             capture_output=True, text=True, env=env )

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


def test_an_explicitly_named_interpreter_is_honoured( planted_root ):
    """
    THE PROPERTY THE PUBLISHED STOPGAP RESTS ON, asserted under its own name.

        PYTHON="$( git rev-parse --git-common-dir )/../.venv/bin/python" purge-pycache.sh

    is what CLAUDE.md tells a seat in a venv-less worktree to run, and it works
    only because the preflight reads PYTHON="${PYTHON:-...}". The distinction the
    script is built on is that a deliberate override is HONOURED while silent
    borrowing is REFUSED -- and until now only the refusing half had a test of its
    own. The honouring half was exercised incidentally by two tests named for
    other things, so a change that dropped it would have reddened them under
    names that do not mention interpreters.

    The fixture has no .venv, so the default resolution CANNOT succeed here: if
    this passes, the explicit value was used.
    """
    assert not ( planted_root / ".venv" ).exists()

    env = dict( os.environ, PYTHON=sys.executable )
    result = subprocess.run( [ str( planted_root / "src" / "scripts" / "purge-pycache.sh" ) ],
                             capture_output=True, text=True, env=env )

    assert result.returncode == 0, result.stderr
    assert _caches( planted_root ) == []


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
    result = subprocess.run( [ str( planted_root / "src" / "scripts" / "purge-pycache.sh" ) ],
                             capture_output=True, text=True, env=env )

    # Survival first: the exit code says what it decided, the directory says what it did.
    assert _caches( planted_root ), "purged despite having no interpreter to reconvert with"
    assert result.returncode == 2
    assert "Refusing to purge" in result.stderr

    # A refusal that only says what it declined leaves the seat stuck. Both
    # supported ways forward must be named, and both are load-bearing: the
    # PYTHON= form is the stopgap already published in CLAUDE.md, and it still
    # works -- an explicitly named interpreter is honoured, only silent borrowing
    # is refused.
    assert "PYTHON=" in result.stderr
    assert "link-worktree-venv.sh" in result.stderr


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
