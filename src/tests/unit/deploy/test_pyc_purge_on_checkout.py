"""
`lupin-vm.sh` must purge stale bytecode whenever the VM's working tree MOVES —
row 70364793.

THE DEFECT
----------
The VM deploys by `git checkout`. `__pycache__` is gitignored, so when a commit
DELETES a .py, git removes the source and LEAVES the compiled .pyc behind. The
LanceDB sweep did exactly that: lancedb_solution_manager.py and
vector_store_backend.py were removed from the tree and their bytecode stayed on
the VM for three weeks. Nothing in the deploy path removed it.

TWO SHAPES, ONLY ONE OF WHICH EXECUTES
--------------------------------------
Measured on CPython 3.13 (see test_preflight_vm_lib.py ::
test_the_class_split_matches_what_cpython_ACTUALLY_does):

    pkg/__pycache__/mod.cpython-313.pyc   ModuleNotFoundError — INERT
    pkg/mod.pyc  (sibling, no cache dir)  imports and runs   — LIVE

The purge removes both, because inert is not the same as harmless: a .pyc the
source tree does not account for appears in no grep, no diff and no review, so
the tree lies about what it holds.

PREVENTION HERE, DETECTION IN PREFLIGHT — AND BOTH ARE NEEDED
-------------------------------------------------------------
This purge stops orphans being created. `preflight-vm.sh` check B5 finds any
that exist anyway (a hand-run `git checkout` on the VM, a restored snapshot, a
deploy from before this change). Neither substitutes for the other. Prevention
that is never verified is how "lupin-vm.sh deploy runs `up -d` WITHOUT
`--no-deps`" sat in a runbook with the words "Filing recommended" and then took
:7999 down the next day. PROSE IS NOT A GUARD, and neither is an unverified fix.

TWO KINDS OF ARM, AND THE SECOND IS THE ONE THAT MATTERS
--------------------------------------------------------
The first half asserts the SHAPE: the purge is defined ONCE and referenced by
BOTH moving modes, so `checkout` and `reset` cannot drift apart.

Shape alone would stay green if the command itself were nonsense. So the second
half EXTRACTS the purge command out of the script source and RUNS it against a
planted tree. It is deliberately not a copy of the command — a test that
re-types the thing it is testing proves only that the author can type twice.

Venue: :7999-eligible. No SSH, no gcloud, no network; the extracted command is
run with sudo stripped, against a temp directory.
"""
import os
import pathlib
import re
import subprocess

import pytest


SCRIPT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/lupin-vm.sh"
SOURCE = SCRIPT.read_text()


def _rcmd_line( mode_marker ):
    """
    Return the single `rcmd=` assignment line that builds the remote command for
    the mode whose completion marker is `mode_marker` (CHECKED_OUT /
    RESET_CHECKED_OUT). Matched as `echo <marker> ` and not as a bare substring:
    CHECKED_OUT is a suffix of RESET_CHECKED_OUT, so a plain `in` check finds
    both lines and the assertion below catches it.

    Requires:
        - mode_marker appears on exactly one rcmd= line in the script

    Ensures:
        - returns that line verbatim
        - fails the calling test if the line is absent or ambiguous, rather than
          returning None and letting a downstream `in` check pass vacuously
    """
    hits = [ l for l in SOURCE.split( "\n" )
             if l.lstrip().startswith( "rcmd=" ) and f"echo {mode_marker} " in l ]
    assert len( hits ) == 1, f"expected exactly one rcmd= line for {mode_marker}, got {len( hits )}"
    return hits[ 0 ]


# ══════════════════════════════════════════════════════════════════════════
# Shape — the purge exists once and both moving modes use it
# ══════════════════════════════════════════════════════════════════════════

def test_the_purge_is_defined_exactly_once():
    """
    One definition, so `checkout` and `reset` cannot drift into two subtly
    different purges — the same single-source-of-truth reason do_push_bundle
    exists rather than two copies of the sync.
    """
    assert len( re.findall( r"^\s*local purge_pyc=", SOURCE, re.M ) ) == 1


@pytest.mark.parametrize( "marker", [ "CHECKED_OUT", "RESET_CHECKED_OUT" ] )
def test_every_mode_that_moves_the_tree_purges( marker ):
    assert "$purge_pyc" in _rcmd_line( marker )


def test_the_purge_runs_after_the_tree_moves_and_before_the_chown():
    """
    Ordering is load-bearing in both directions. Purging BEFORE the checkout
    would delete bytecode the checkout is about to orphan all over again; purging
    AFTER the chown would leave the newly-created directories owned by root.
    """
    line = _rcmd_line( "RESET_CHECKED_OUT" )
    assert line.index( "checkout -B" ) < line.index( "$purge_pyc" ) < line.index( "chown" )


def test_the_fetch_only_path_does_not_purge():
    """
    push-bundle with no mode updates refs and leaves the working tree ALONE, so
    no .py is removed and no orphan is created. Purging there would be a deploy
    step that fires when nothing has changed — cost with no defect behind it.
    """
    base = [ l for l in SOURCE.split( "\n" )
             if l.lstrip().startswith( "local rcmd=" ) ]
    assert len( base ) == 1
    assert "purge_pyc" not in base[ 0 ]


def test_the_purge_reports_that_it_ran():
    """
    A silent cleanup is an unverifiable one. The marker is what an operator (or a
    later forensic read of the deploy log) uses to tell "purged nothing" from
    "never ran".
    """
    definition = re.search( r"^\s*local purge_pyc=.*$", SOURCE, re.M ).group( 0 )
    assert "PYCACHE_PURGED" in definition


def test_dry_run_narration_mentions_the_purge():
    """
    --dry-run exists to say what a real run would do. A step it omits is a step
    the reader does not know is coming.
    """
    for marker in ( "checkout)", "reset)" ):
        line = [ l for l in SOURCE.split( "\n" )
                 if l.lstrip().startswith( marker ) and "move_desc=" in l ]
        assert len( line ) == 1
        assert "purge" in line[ 0 ]


# ══════════════════════════════════════════════════════════════════════════
# Behaviour — the extracted command actually removes orphans
# ══════════════════════════════════════════════════════════════════════════

def _extract_purge_command():
    """
    Pull the purge command out of the script SOURCE and make it runnable here.

    Requires:
        - the script defines `local purge_pyc="..."`

    Ensures:
        - returns the command body with `sudo ` stripped (this test is not root)
        - raises AssertionError if the definition cannot be found, so a renamed
          variable fails the test rather than silently testing an empty string
    """
    m = re.search( r'^\s*local purge_pyc="(.+)"\s*$', SOURCE, re.M )
    assert m, "could not find the purge_pyc definition — did it get renamed?"
    return m.group( 1 ).replace( "sudo ", "" )


def _plant_vm_tree( root ):
    src = root / "src" / "pkg"
    ( src / "__pycache__" ).mkdir( parents=True )
    ( src / "live.py" ).write_text( "x = 1\n" )
    ( src / "__pycache__" / "live.cpython-313.pyc" ).write_bytes( b"" )
    ( src / "__pycache__" / "gone.cpython-313.pyc" ).write_bytes( b"" )   # DEAD orphan
    ( src / "ghost.pyc" ).write_bytes( b"" )                              # SOURCELESS orphan
    return src


def test_the_extracted_purge_removes_both_orphan_shapes( tmp_path ):
    src = _plant_vm_tree( tmp_path )
    assert len( list( src.rglob( "*.pyc" ) ) ) == 3

    cmd = _extract_purge_command()
    r = subprocess.run(
        [ "bash", "-c", f'VM_ROOT="{tmp_path}"; {cmd}' ],
        capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert "PYCACHE_PURGED" in r.stdout
    assert list( src.rglob( "*.pyc" ) ) == []
    assert list( src.rglob( "__pycache__" ) ) == []


def test_the_extracted_purge_leaves_sources_alone( tmp_path ):
    """
    The negative control. A purge that also deleted .py files would pass every
    assertion in the test above and destroy the deploy.
    """
    src = _plant_vm_tree( tmp_path )
    cmd = _extract_purge_command()
    subprocess.run( [ "bash", "-c", f'VM_ROOT="{tmp_path}"; {cmd}' ], capture_output=True )
    assert ( src / "live.py" ).exists()
    assert ( src / "live.py" ).read_text() == "x = 1\n"


def test_the_extracted_purge_succeeds_on_an_already_clean_tree( tmp_path ):
    """
    A deploy that removes no module must not fail the purge step — which is
    chained with && into the remote command, so a non-zero here would abort the
    checkout that just succeeded.
    """
    ( tmp_path / "src" ).mkdir()
    ( tmp_path / "src" / "only.py" ).write_text( "x = 1\n" )
    cmd = _extract_purge_command()
    r = subprocess.run(
        [ "bash", "-c", f'VM_ROOT="{tmp_path}"; {cmd}' ], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert "PYCACHE_PURGED" in r.stdout


def test_the_purge_and_the_detector_agree( tmp_path ):
    """
    THE HANDSHAKE. The prevention and the detection are in different files by
    different mechanisms; this proves they mean the same thing by running the
    detector over a tree the purge has just cleaned. If either side's idea of
    "orphan" drifts, this fails.
    """
    lib = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/lib/preflight-vm-lib.sh"
    src = _plant_vm_tree( tmp_path )

    before = subprocess.run(
        [ "bash", "-c", f"source '{lib}'; pfv_scan_orphan_pyc '{src}'" ],
        capture_output=True, text=True
    )
    assert before.returncode == 1                      # the detector sees the orphans
    assert "DEAD" in before.stdout and "SOURCELESS" in before.stdout

    cmd = _extract_purge_command()
    subprocess.run( [ "bash", "-c", f'VM_ROOT="{tmp_path}"; {cmd}' ], capture_output=True )

    after = subprocess.run(
        [ "bash", "-c", f"source '{lib}'; pfv_scan_orphan_pyc '{src}'" ],
        capture_output=True, text=True
    )
    assert after.returncode == 0                       # and none survive the purge
    assert after.stdout == ""
