"""
Item 6 of row c9f4d613, at the layer the incident entered: a REAP, for a seat standing
in a linked worktree, must FIND a correctly-written memento — and must still report a
miss when there is none anywhere.

🔴 WHY THIS FILE EXISTS RATHER THAN A LINE IN AN EXISTING ONE. Both halves have to be
provable in ONE suite or the guard is worthless (Mr. Radio's ruling, 2026-09-04). Today
they are not. Measured across every `test_reap_memento*.py` in the tier:

  the NEGATIVE half   well covered — test_seat_with_nothing_at_the_slot_still_reports_
                      timeout_no_memento, and six more assertions on timeout_no_memento
  the POSITIVE half   ABSENT — no reap test builds a real linked worktree at all
                      (`grep -l "worktree add" test_reap_memento*.py` returns nothing)

⇒ The missing half is the one that would have caught the incident. On 2026-09-04 21:34 a
reap of a worktree seat returned `timeout_no_memento` naming
`<worktree>/io/mementos/<persona>.md`, while the memento sat in the MAIN checkout — 12,101
bytes, right session id, written nineteen minutes earlier. A suite that only ever proves
"nothing there ⇒ timeout" agrees with that outcome enthusiastically.

WHAT MAKES THE CURE WORK, and it is the thing under test here: `seat_repo_root` COLLAPSES a
linked worktree to its own main checkout (`repo_root_owning`), because the writer collapses
too — "memento canonicality is a REPO question" (memento_io row af0c5700). The reap then
derives its slot from the same tree the writer used.

⚠️ THE THIRD CASE IS THE POINT, NOT A BONUS. Arms 1 and 2 pass whether or not the collapse
exists as long as everything sits in one tree, so on their own they cannot tell you the
collapse is load-bearing. Arm 3 resolves the seat's cwd the PRE-FIX way — verbatim, no
collapse — and shows arm 1 inverts. Without it this file is two green assertions about a
mechanism it never exercises.

⚠️ REAL GIT, REAL WORKTREE, REAL FILES. The defect lives entirely in what git answers for a
linked worktree, so a canned `run_fn` would agree with whatever the implementation asked it
and the fixture would become the thing under test — the same reasoning
`test_the_memento_readers_resolve_the_writers_tree.py` gives for its own fixtures.
"""

import datetime
import shutil
import subprocess
from pathlib import Path

import pytest

from lupin_mcp.memento_repo_root import repo_root_owning
from lupin_mcp.reap_memento      import ( DEFAULT_MIN_BYTES, seat_memento_slot,
                                          seat_repo_root,
                                          verify_seat_memento_at_any_readable_slot )


pytestmark = pytest.mark.skipif( shutil.which( "git" ) is None,
                                 reason="this case drives the real git binary" )

PERSONA = "Pocholo"
SID8    = "0f26434c"


def _git( *argv, cwd ):
    subprocess.run( [ "git", *argv ], cwd=str( cwd ), check=True,
                    capture_output=True, text=True )


@pytest.fixture
def seat( tmp_path ):
    """A real repo plus a real linked worktree — the seat stands in the worktree."""
    main = tmp_path / "main"
    main.mkdir()
    _git( "init", "-q", ".", cwd=main )
    _git( "config", "user.email", "t@t", cwd=main )
    _git( "config", "user.name",  "t",   cwd=main )
    ( main / "README.md" ).write_text( "seed\n", encoding="utf-8" )
    _git( "add", "-A", cwd=main )
    _git( "commit", "-qm", "seed", cwd=main )

    worktree = tmp_path / "main-wt"
    _git( "worktree", "add", "-q", str( worktree ), "-b", "wt-branch", cwd=main )
    return { "main": main, "worktree": worktree }


def _read_text_fn( path ):
    p = Path( path )
    return p.read_text( encoding="utf-8" ) if p.is_file() else None


def _write_memento( repo_root, now ):
    """
    A memento the way the WRITER lands it: at the io slot of the MAIN checkout, with a
    well-formed header, comfortably over the completeness floor.
    """
    slot = Path( seat_memento_slot( str( repo_root ), PERSONA ) )
    slot.parent.mkdir( parents=True, exist_ok=True )
    header = ( f"<!-- memento-record: persona={PERSONA.lower()} session_id={SID8} "
               f"written_at={now.isoformat()} slot=io -->\n" )
    # Over DEFAULT_MIN_BYTES on purpose: a header-only stub fails the completeness floor,
    # and a fixture under the floor makes every arm return the same refusal — the blind
    # instrument this row already got caught by once.
    body = ( "board state: row c9f4d613, the reap must find this file from the worktree.\n" ) * 30
    slot.write_text( header + body, encoding="utf-8" )
    assert len( slot.read_bytes() ) > DEFAULT_MIN_BYTES, "fixture is under the completeness floor"
    return slot


# A no-op merge-claim checker. These arms are about PATH RESOLUTION; the merge-claim gate
# is a different guard with its own tests, and letting it run here would make a
# resolution failure and a claim refusal print as the same red.
def _no_merge_claim( text, repo_root ):
    return None


def _verify_from( repo_root, now ):
    return verify_seat_memento_at_any_readable_slot(
        str( repo_root ), PERSONA, SID8, now,
        read_text_fn=_read_text_fn, merge_claim_fn=_no_merge_claim )


# ---------------------------------------------------------------------------
# ARM 1 — THE HALF THAT DID NOT EXIST
# ---------------------------------------------------------------------------
def test_the_reap_finds_a_correctly_written_memento_for_a_seat_in_a_worktree( seat ):
    now  = datetime.datetime.now().astimezone()
    slot = _write_memento( seat[ "main" ], now )

    # the seat's own bridge cwd is the WORKTREE — this is the whole shape of the incident
    resolved = seat_repo_root( { "cwd": str( seat[ "worktree" ] ) } )
    assert Path( resolved ) == seat[ "main" ], "the reap did not collapse the worktree to its main checkout"

    usable, reason, answered = _verify_from( resolved, now )
    assert usable is True, reason
    assert Path( answered ) == slot                  # and it answered from the io slot
    assert "verified" in reason


# ---------------------------------------------------------------------------
# ARM 2 — THE NEGATIVE HALF, IN THE SAME SUITE
# ---------------------------------------------------------------------------
def test_the_reap_still_reports_a_miss_when_no_memento_exists_anywhere( seat ):
    """
    ⚠️ THIS ARM CARRIES A PATH CLAIM AS WELL AS A MISS CLAIM, deliberately — do not read it
    as a bare timeout test. `usable is False` ALONE would pass under the unwired collapse and
    under a reap that had stopped working altogether, because "found nothing" is what a
    broken reader says too. Asserting WHICH slot answered is what stops the negative half
    being vacuous. Measured: unwire the collapse and this reddens on the path, not the miss.
    """
    now = datetime.datetime.now().astimezone()      # nothing written at all

    resolved = seat_repo_root( { "cwd": str( seat[ "worktree" ] ) } )
    usable, reason, answered = _verify_from( resolved, now )

    assert usable is False
    assert Path( answered ) == Path( seat_memento_slot( str( seat[ "main" ] ), PERSONA ) )
    assert reason                                    # it says why, rather than going quiet


# ---------------------------------------------------------------------------
# ARM 3 — THE CONTROL. Without the collapse, arm 1 inverts.
# ---------------------------------------------------------------------------
def test_without_the_collapse_the_worktree_seat_reads_as_a_missing_memento( seat ):
    """
    The pre-fix resolution, verbatim: take the seat's cwd as its repo root. This is what
    produced a `timeout_no_memento` on a seat whose memento was on disk the whole time.
    Arms 1 and 2 cannot distinguish a working collapse from no collapse; this can.
    """
    now = datetime.datetime.now().astimezone()
    _write_memento( seat[ "main" ], now )

    uncollapsed = seat[ "worktree" ]                 # <- the defect, reproduced by hand
    assert Path( repo_root_owning( str( uncollapsed ) ) ) == seat[ "main" ], \
        "fixture check: these two must differ, or this arm proves nothing"

    usable, reason, answered = _verify_from( uncollapsed, now )
    assert usable is False, "if this passed, arm 1 would pass with or without the collapse"
    assert Path( answered ).is_relative_to( seat[ "worktree" ] )   # it looked in the wrong tree
