"""
No source file in this tree is currently shadowed by stale cached bytecode — and the detector that
says so is itself proven able to see the condition.

Row `d18ce9ef`. CPython validates a `.pyc` on the source's **whole-second** mtime plus its **size**,
so an edit changing neither is invisible and the stale bytecode is served as valid. Measured twice
on 2026-08-29 without anyone hunting for it: on `src/cosa/rest/job_state.py` during the AC-G4
mutation sweep, and on `tests/helpers/pyc_freshness.py` while the helper was being written.

WHY A DOC WAS NOT ENOUGH, stated because the docs landed first (`4b5426da`) and this file is not a
duplicate of them. CLAUDE.md's own heartbeat-hold note records a correctly-worded instruction that
half the fleet broke anyway, where the remedy turned out to be a detector rather than better
wording. This is that detector.

🔴 THE FAILURE MODE THIS FILE IS BUILT AGAINST IS ITS OWN GREEN. A detector whose comparison is
broken reports zero findings forever and reads exactly like a clean tree. Two independent defenses,
both permanent:

  1. `test_the_detector_actually_sees_a_shadowing_pyc` manufactures the condition in a temp dir and
     requires the detector to catch it. If the comparison ever stops working, THIS goes red — the
     tree scan cannot, because a broken comparison and a clean tree produce the same output.
  2. `test_the_scan_examined_a_meaningful_number_of_files` fails on a scan that assessed too few
     files. A scan that examined nothing is the purest vacuous pass there is, and it is exactly
     what a wrong root path or an over-eager filter produces.

⚠️ NOT HYPOTHETICAL. The first version of this detector compared `marshal.dumps` output and
reported **1093** shadowed files in `src/cosa` where the truth was **zero** — `marshal` emits
back-references, so re-dumping equal objects yields different bytes. That defect was caught only
because 1093 was implausible. The inverse defect — a comparison that never differs — produces a
*plausible* zero, and nothing but defense 1 would ever catch it.
"""

import os
import subprocess
import sys

from pathlib import Path

import pytest

REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]
if str( REPO_ROOT / "src" ) not in sys.path: sys.path.insert( 0, str( REPO_ROOT / "src" ) )

from tests.helpers.pyc_freshness import (            # noqa: E402
    bytecode_files_for,
    describe_shadowing,
    find_shadowing_bytecode,
)

SCAN_ROOTS = [ REPO_ROOT / "src" / "cosa",
               REPO_ROOT / "src" / "tests",
               REPO_ROOT / "src" / "lupin_app" ]

# A scan that assesses fewer than this has not looked at the tree, whatever it returns. Set well
# below the ~2,100 observed on 2026-08-29 so ordinary growth or a pruned cache cannot make it flap;
# it exists to catch a scan that collapsed, not to pin a count.
MIN_ASSESSABLE = 200


def _manufacture_shadowed_source( tmp_path ):
    """
    Build a source file that a valid-looking `.pyc` shadows: compile one text, replace it with a
    DIFFERENT text of the SAME length, then force the source's mtime onto the pyc's whole second.
    `touch`-equivalent rather than a sleep, so it is deterministic rather than a timing gamble.
    """
    src = tmp_path / "shadowed.py"
    src.write_text( 'VALUE = "dead"\n', encoding="utf-8" )
    subprocess.run( [ sys.executable, "-c",
                      f"import sys; sys.path.insert( 0, {str( tmp_path )!r} ); import shadowed" ],
                    capture_output=True, timeout=60 )
    src.write_text( 'VALUE = "todo"\n', encoding="utf-8" )       # same length

    pycs = bytecode_files_for( src )
    assert pycs, "no .pyc was produced — this probe cannot manufacture the condition it needs"
    stat = pycs[ 0 ].stat()
    os.utime( src, ( stat.st_atime, stat.st_mtime ) )
    return src


def test_the_detector_actually_sees_a_shadowing_pyc( tmp_path ):
    """
    DEFENSE 1 — the control that makes every other green in this file mean something.

    Ensures:
        - a manufactured shadowed source is reported
        - the count of assessable files is non-zero, so the finding came from a real scan
    """
    src = _manufacture_shadowed_source( tmp_path )

    shadowed, examined = find_shadowing_bytecode( [ tmp_path ] )

    assert examined >= 1
    assert src in shadowed, (
        "the detector did NOT see a shadowing .pyc that was deliberately manufactured. Its "
        "comparison is broken, which means its zero-findings result on the real tree is "
        "meaningless — a broken comparison and a clean tree look identical from the outside."
    )


def test_a_source_with_matching_bytecode_is_not_reported( tmp_path ):
    """
    The paired negative. Without it, a detector that flags EVERYTHING also passes defense 1, and
    the tree scan below would be the only thing objecting — from the wrong direction.

    Ensures:
        - an ordinary compiled source is not reported
    """
    src = tmp_path / "honest.py"
    src.write_text( 'VALUE = "todo"\n', encoding="utf-8" )
    subprocess.run( [ sys.executable, "-c",
                      f"import sys; sys.path.insert( 0, {str( tmp_path )!r} ); import honest" ],
                    capture_output=True, timeout=60 )

    shadowed, examined = find_shadowing_bytecode( [ tmp_path ] )

    assert examined >= 1
    assert shadowed == []


def test_the_scan_examined_a_meaningful_number_of_files():
    """
    DEFENSE 2 — a scan that assessed nothing reports a clean tree.

    Ensures:
        - the real scan assessed at least MIN_ASSESSABLE sources
    """
    _, examined = find_shadowing_bytecode( SCAN_ROOTS )

    assert examined >= MIN_ASSESSABLE, (
        f"the shadowing scan assessed only {examined} source file(s), below the {MIN_ASSESSABLE} "
        f"floor. Its clean verdict is not evidence of a clean tree — most likely the roots are "
        f"wrong, a filter is over-eager, or the bytecode cache was cleared out from under it.\n"
        f"Roots scanned: {[ str( r ) for r in SCAN_ROOTS ]}"
    )


def test_no_source_in_the_tree_is_shadowed_by_stale_bytecode():
    """
    THE ASSERTION ITSELF.

    A red here is not necessarily anyone's mistake: a peer editing a file in the same second its
    bytecode was compiled produces a genuine, transient instance. The remedy in the message is safe
    to run either way, and results touching the named files are void until it is.

    Ensures:
        - no assessable source in src/cosa, src/tests or src/lupin_app is shadowed
    """
    shadowed, examined = find_shadowing_bytecode( SCAN_ROOTS )

    assert not shadowed, describe_shadowing( shadowed )
    assert examined >= MIN_ASSESSABLE           # belt: a zero-file scan must not read as a pass


def test_the_failure_message_names_the_files_and_the_remedy():
    """
    The remedy is only reachable by making the test fail, so nobody would ever read it — unless it
    is asserted directly. A message that omits it turns a loud failure into a puzzle.

    Ensures:
        - every offending path appears in the text
        - the cache-clear command appears, runnable as written
        - the row id is present so the reader can find the measurement
    """
    text = describe_shadowing( [ Path( "/x/alpha.py" ), Path( "/x/beta.py" ) ] )

    assert "/x/alpha.py" in text and "/x/beta.py" in text
    assert "__pycache__" in text and "rm -rf" in text
    assert "d18ce9ef" in text


def test_empty_roots_are_refused_rather_than_reported_clean():
    """
    An empty root list is the shortest path to a vacuous green, and a caller can produce one by
    accident (a filtered list, a missing directory).

    Ensures:
        - an empty roots list raises
        - a non-existent root raises rather than being skipped
    """
    with pytest.raises( AssertionError, match="no roots given" ):
        find_shadowing_bytecode( [] )

    with pytest.raises( AssertionError, match="root does not exist" ):
        find_shadowing_bytecode( [ REPO_ROOT / "no_such_directory_here" ] )
