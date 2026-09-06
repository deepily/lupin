"""
WRITER PATH == READER PATH, WITH THE **SLOT** AS THE VARIABLE (row c9f4d613).

🔴 WHAT THIS GUARDS THAT `test_the_memento_readers_resolve_the_writers_tree.py`
CANNOT. That file holds a real parity claim and holds it well — but it transcribes
ONE writer rule, `memento_io.find_repo_root`, and poses every case against it.
`find_repo_root` is the **io** answer. The writer has a SECOND rule, `find_seat_root`,
which the **root** slot uses and which does NOT collapse a linked worktree. So the
older guard certified the collapse as universally correct, and a root record written
into the seat's own tree while the reader looked in the main checkout is invisible to
every one of its cases.

⇒ IT NEVER VARIED THE SLOT, SO IT COULD NOT FAIL ON THE SLOT. Measured on
pocholo's own reap, 2026-09-04: `timeout_no_memento`, against a record that was on
disk the whole time.

WHAT WOULD BREAK WITHOUT THIS FILE: a self-respin verifies the root slot against the
MAIN checkout while the writer wrote to the worktree. It surfaces as
`STALE_MEMENTO` / `timeout_no_memento` — neither of which names a path, so it reads
as a missing memento rather than two trees.

⚠️ EVERY CASE DRIVES REAL `git` AGAINST A REAL `git worktree add`. The whole defect
lives in what git answers for a linked worktree; a fake `run_fn` returning canned
strings would agree with whatever the implementation asked it, and the fixture would
become the thing under test.

⚠️ AND THE WRITER'S RULES ARE TRANSCRIBED, NEVER IMPORTED. The writer lives in
planning-is-prompting and is not importable from here. If either helper below ever
delegates to the code under test, every assertion becomes a tautology that passes
whatever both sides do — a comparison whose two sides come from one source cannot
disagree.
"""
import os
import shutil
import subprocess

import pytest

from lupin_mcp.memento_repo_root import SLOT_IO, SLOT_ROOT, slot_base_root
from lupin_mcp.memento_slot      import resolve_repo_root, slot_record_path


pytestmark = pytest.mark.skipif( shutil.which( "git" ) is None,
                                 reason="these cases drive the real git binary" )


def _git( *args, cwd ):
    """Ensures: runs git in `cwd`, raising with git's own stderr on failure."""
    proc = subprocess.run( [ "git", *args ], cwd=str( cwd ), capture_output=True, text=True )
    if proc.returncode != 0:
        raise AssertionError( f"git {' '.join( args )} failed in {cwd}: {proc.stderr.strip()}" )
    return proc.stdout.strip()


@pytest.fixture
def trees( tmp_path ):
    """
    A main checkout and a REAL linked worktree of it.

    The worktree is the only shape where the two writer rules disagree, so it is the
    only shape that can catch a slot-blind reader. `main` is the negative control: in
    the main checkout both slots answer the same path, and a guard that only ever
    looked there would pass with the bug live — which is how this got to production.
    """
    main = tmp_path / "main"
    os.makedirs( main )
    _git( "init", "-q", cwd=main )
    _git( "-c", "user.email=t@t", "-c", "user.name=t",
          "commit", "-q", "--allow-empty", "-m", "init", cwd=main )

    worktree = tmp_path / "main-wt"
    _git( "worktree", "add", "-q", str( worktree ), "-b", "wt-branch", cwd=main )

    return { "main": str( main ), "worktree": str( worktree ) }


# ── The writer's TWO rules, transcribed independently ─────────────────────────
def _writers_io_root( start ):
    """
    `memento_io.find_repo_root` — "which REPO owns this work". Collapses a linked
    worktree to the MAIN checkout.
    """
    def resolved( flag ):
        answer = _git( "rev-parse", flag, cwd=start )
        path   = answer if os.path.isabs( answer ) else os.path.join( start, answer )
        return os.path.realpath( path )

    if resolved( "--git-dir" ) == resolved( "--git-common-dir" ):
        return os.path.realpath( _git( "rev-parse", "--show-toplevel", cwd=start ) )
    return os.path.dirname( resolved( "--git-common-dir" ) )


def _writers_root_root( start ):
    """
    `memento_io.find_seat_root` — "which TREE am I in". Does NOT collapse; from a
    linked worktree it returns THE WORKTREE.
    """
    return os.path.realpath( _git( "rev-parse", "--show-toplevel", cwd=start ) )


_WRITER = { SLOT_IO: _writers_io_root, SLOT_ROOT: _writers_root_root }


# ── The fixture has to be able to tell the two apart, or nothing below means anything ──
def test_the_two_writer_rules_actually_disagree_in_this_fixture( trees ):
    """
    THE POSITIVE CONTROL ON THE WHOLE FILE, so it runs first.

    Every assertion below compares a reader against one of the two writer rules. If
    those rules returned the same path here, every case would pass whether or not the
    reader varies on the slot — the file would be measuring nothing. This is the
    check that the variable is a variable.
    """
    assert _writers_io_root( trees[ "worktree" ] ) != _writers_root_root( trees[ "worktree" ] ), (
        "the two writer rules agree in this fixture, so the worktree cases below "
        "cannot discriminate — the `git worktree add` did not take"
    )
    assert _writers_io_root( trees[ "main" ] ) == _writers_root_root( trees[ "main" ] ), (
        "in the MAIN checkout the two rules must agree; if they do not, this "
        "transcription is wrong and every verdict below is suspect"
    )


# ── The parity claim, slot by slot ────────────────────────────────────────────
@pytest.mark.parametrize( "slot",  [ SLOT_IO, SLOT_ROOT ] )
@pytest.mark.parametrize( "shape", [ "main", "worktree" ] )
def test_the_reader_resolves_the_tree_the_writer_writes_to( trees, slot, shape ):
    """
    ONE VARIABLE AT A TIME, AND THE SLOT IS ONE OF THEM.

    Both arms are required and neither is decorative. The `root`/`worktree` cell is
    the defect; the `io`/`worktree` cell is what stops a root fix from silently
    breaking io, which is the trap this row already carries — you cannot repoint one
    side of a coincidence without deciding the rule for every side.
    """
    start = trees[ shape ]
    got   = slot_base_root( start, slot )

    assert got is not None, f"reader refused to resolve slot {slot!r} at {start!r}"
    assert os.path.realpath( str( got ) ) == _WRITER[ slot ]( start ), (
        f"slot {slot!r} in a {shape}: the reader resolved {str( got )!r} but the "
        f"writer writes to {_WRITER[ slot ]( start )!r} — a memento written there is "
        f"never found here, and the failure names no path"
    )


def test_the_two_slots_part_company_in_a_worktree_and_agree_in_the_main_checkout( trees ):
    """
    THE DISCRIMINATOR, STATED AS BOTH DIRECTIONS IN ONE TEST.

    Without the second half a reader that returned the seat's own tree for EVERYTHING
    would pass — and that is not a fix, it is the io defect (row af0c5700) re-created
    in the other direction: an io record in a worktree is written where no reap looks.
    """
    assert ( os.path.realpath( str( slot_base_root( trees[ "worktree" ], SLOT_ROOT ) ) )
             == os.path.realpath( trees[ "worktree" ] ) ), \
        "the ROOT slot must stay in the seat's own tree — self_respin reads it there"
    assert ( os.path.realpath( str( slot_base_root( trees[ "worktree" ], SLOT_IO ) ) )
             == os.path.realpath( trees[ "main" ] ) ), \
        "the IO slot must still collapse to the MAIN checkout — the reap reads it there"


def test_self_respins_own_reader_lands_in_the_seats_tree( trees ):
    """
    The DOOR, not just the helper.

    `slot_base_root` being right proves nothing about whether `self_respin` reaches
    it — that is this repo's implemented-but-not-installed shape. `resolve_repo_root`
    is the function `self_respin_core` actually calls, and it defaults to the root
    slot; this asserts the default, because the default is what ships.
    """
    got = resolve_repo_root( start=trees[ "worktree" ] )

    assert os.path.realpath( str( got ) ) == os.path.realpath( trees[ "worktree" ] ), (
        "self_respin's own resolver left the seat's tree — it would verify a memento "
        f"against {got!r} while the writer wrote to {trees[ 'worktree' ]!r}"
    )


def test_the_record_paths_a_seat_writes_and_reads_are_the_same_file( trees ):
    """
    END OF THE CHAIN: the actual FILE, not the base dir.

    A base dir can be right while the path built from it is not, and the base dir is
    not what a reap opens. This asserts the two slots land in different trees at the
    record level — the level the failure was reported at.
    """
    wt   = trees[ "worktree" ]
    root = slot_record_path( slot_base_root( wt, SLOT_ROOT ), "pocholo", "cd70f8e5", SLOT_ROOT )
    io   = slot_record_path( slot_base_root( wt, SLOT_IO   ), "pocholo", "cd70f8e5", SLOT_IO )

    assert str( root ).startswith( os.path.realpath( wt ) ), \
        f"the root-slot RECORD left the seat's tree: {root}"
    assert str( io ).startswith( os.path.realpath( trees[ "main" ] ) ), \
        f"the io-slot RECORD left the main checkout: {io}"
    assert root != io, "the two slots resolved to one file — the split is gone"


def test_an_unknown_slot_is_refused_rather_than_defaulted( trees ):
    """
    A typo must not silently pick a slot. A mis-slotted memento writes SUCCESSFULLY,
    to a place its reader does not look — the failure mode this whole row is about.
    """
    with pytest.raises( ValueError, match="unknown memento slot" ):
        slot_base_root( trees[ "main" ], "roto" )
