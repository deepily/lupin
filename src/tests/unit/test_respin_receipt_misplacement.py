"""
A receipt that is ABSENT and a receipt that is MISPLACED used to read identically
(row db56ac6d).

THE DEFECT. `find_receipt_by_identity` globs `<base_dir>/<prefix>*.json`
NON-RECURSIVELY. A receipt written anywhere else is not reported as misplaced — it
is not seen at all, so the check reports the same `None` it reports for a seat that
never booted. `classify_wake` turns that `None` into DEAD_NO_WAKE, so a re-spin that
LANDED and wrote its receipt to the wrong root is indistinguishable from one that
never came back. Two failures wanting opposite remedies — chase a dead seat, or fix
a writer — behind one output.

Measured on the real tree: three receipts of this family sit under
projects-data/lupin-mobile while the correct root holds 162. Two of the three were
written AFTER the sibling move, so this is not a leftover of the old nested layout.

WHAT IS BUILT HERE IS A DETECTOR AND NOTHING ELSE. No verdict changes, no alarm
changes, and nothing about WHERE anything is written. `misplaced` is evidence a
reader may ignore, and the tests below pin that: the verdict-and-alarm pair is
asserted to be identical with and without a misplaced receipt on disk.

The shape mirrors `heartbeat_hold.hold_is_misplaced` deliberately — the holds family
already solved this and two different shapes for one defect is a second thing to
learn.
"""

import datetime
import json
import os

import pytest

from cosa.agents.heartbeat_arbiter import respin_wake_check as rwc


UTC = datetime.timezone.utc


def _dt( minute, second=0 ):
    return datetime.datetime( 2026, 9, 2, 18, minute, second, tzinfo=UTC )


def _receipt_body( sid, *, persona="Sam", tmux="sam-pane", booted_at=None ):
    return rwc.build_receipt_dict(
        session_id         = sid,
        persona            = persona,
        tmux_session       = tmux,
        memento_path       = None,
        memento_written_at = None,
        repo_root          = "/repo",
        booted_at          = booted_at if booted_at is not None else _dt( 20 ),
    )


def _write( directory, sid, **kw ):
    """Write a real receipt into `directory`; return its path."""
    os.makedirs( directory, exist_ok=True )
    path = os.path.join( directory, f"{rwc.RECEIPT_PREFIX}{sid}.json" )
    with open( path, "w", encoding="utf-8" ) as fh:
        json.dump( _receipt_body( sid, **kw ), fh )
    return path


@pytest.fixture
def zone( tmp_path ):
    """
    The real layout in miniature: a data root holding sibling project roots.

    `correct` is what the check globs; `sibling` is where the three real strays
    landed; `nested` is one level deeper INSIDE correct, which the non-recursive
    glob misses just as completely.
    """
    correct = tmp_path / "lupin"
    sibling = tmp_path / "lupin-mobile"
    nested  = correct  / "nested"
    for d in ( correct, sibling, nested ):
        d.mkdir( parents=True, exist_ok=True )
    return { "root": tmp_path, "correct": correct, "sibling": sibling, "nested": nested }


# ---------------------------------------------------------------------------
# THE DEFECT ITSELF — pinned, so nobody "fixes" the detector by making the
# finder recursive and silently changing what the check reads.
# ---------------------------------------------------------------------------
def test_the_existing_finder_cannot_tell_absent_from_misplaced( zone ):
    """The premise, measured rather than asserted: three states, one output."""
    q = dict( persona="Sam", tmux_session="sam-pane" )

    nothing_anywhere = rwc.find_receipt_by_identity( str( zone[ "correct" ] ), **q )

    _write( str( zone[ "sibling" ] ), "sidB" )
    in_a_sibling_root = rwc.find_receipt_by_identity( str( zone[ "correct" ] ), **q )

    _write( str( zone[ "nested" ] ), "sidC" )
    one_level_deeper = rwc.find_receipt_by_identity( str( zone[ "correct" ] ), **q )

    assert nothing_anywhere  is None
    assert in_a_sibling_root is None
    assert one_level_deeper  is None

    # POSITIVE CONTROL. Without this the three Nones above would be equally
    # consistent with a finder that never finds anything.
    _write( str( zone[ "correct" ] ), "sidD" )
    found = rwc.find_receipt_by_identity( str( zone[ "correct" ] ), **q )
    assert found is not None
    assert found[ "session_id" ] == "sidD"


# ---------------------------------------------------------------------------
# receipt_is_misplaced — the predicate
# ---------------------------------------------------------------------------
def test_a_receipt_in_a_sibling_root_is_misplaced( zone ):
    path = _write( str( zone[ "sibling" ] ), "sidB" )
    assert rwc.receipt_is_misplaced( path, str( zone[ "correct" ] ) ) is True


def test_a_receipt_one_level_deeper_is_ALSO_misplaced( zone ):
    """
    The parent-vs-ancestry distinction, and it is the whole reason this predicate
    is not a copy of the holds one. An ancestry test would call this file correctly
    placed; the finder would still never see it. A detector that disagrees with the
    read it is describing is worse than no detector.
    """
    path = _write( str( zone[ "nested" ] ), "sidC" )
    assert rwc.receipt_is_misplaced( path, str( zone[ "correct" ] ) ) is True
    # ...and the finder really is blind to it, so the True above is not pedantry.
    assert rwc.find_receipt_by_identity( str( zone[ "correct" ] ),
                                         persona="Sam", tmux_session="sam-pane" ) is None


def test_a_receipt_in_the_right_place_is_not_misplaced( zone ):
    path = _write( str( zone[ "correct" ] ), "sidD" )
    assert rwc.receipt_is_misplaced( path, str( zone[ "correct" ] ) ) is False


def test_an_unresolvable_zone_never_over_flags( zone ):
    """Fail-safe: a false 'misplaced' sends a manager to fix a writer that works."""
    path = _write( str( zone[ "correct" ] ), "sidD" )
    assert rwc.receipt_is_misplaced( path, None ) is False


def test_an_unresolvable_path_never_over_flags( zone ):
    assert rwc.receipt_is_misplaced( "\x00not-a-path", str( zone[ "correct" ] ) ) is False


# ---------------------------------------------------------------------------
# find_misplaced_receipts — the scan
# ---------------------------------------------------------------------------
def test_it_finds_a_receipt_written_to_a_sibling_root( zone ):
    _write( str( zone[ "sibling" ] ), "sidB" )
    hits = rwc.find_misplaced_receipts( str( zone[ "correct" ] ),
                                        persona="Sam", tmux_session="sam-pane" )
    assert [ h[ "receipt" ][ "session_id" ] for h in hits ] == [ "sidB" ]
    assert hits[ 0 ][ "path" ].endswith( f"{rwc.RECEIPT_PREFIX}sidB.json" )


def test_it_reports_only_what_the_existing_read_is_blind_to( zone ):
    """A correctly-placed receipt is the finder's job, not this one's."""
    _write( str( zone[ "correct" ] ), "sidD" )
    _write( str( zone[ "sibling" ] ), "sidB" )
    hits = rwc.find_misplaced_receipts( str( zone[ "correct" ] ),
                                        persona="Sam", tmux_session="sam-pane" )
    assert [ h[ "receipt" ][ "session_id" ] for h in hits ] == [ "sidB" ]


def test_a_blank_query_claims_nothing( zone ):
    """Same rule find_receipt_by_identity follows: no identity, no claim."""
    _write( str( zone[ "sibling" ] ), "sidB" )
    assert rwc.find_misplaced_receipts( str( zone[ "correct" ] ) ) == []


def test_another_seats_stray_receipt_is_not_mine( zone ):
    _write( str( zone[ "sibling" ] ), "sidX", persona="Tiberius", tmux="tib-pane" )
    assert rwc.find_misplaced_receipts( str( zone[ "correct" ] ),
                                        persona="Sam", tmux_session="sam-pane" ) == []


def test_a_stray_from_before_the_respin_is_not_this_cycles( zone ):
    """The recency floor: an old stray is somebody's earlier problem, not evidence
    about the re-spin that just fired."""
    _write( str( zone[ "sibling" ] ), "sidOld", booted_at=_dt( 10 ) )
    assert rwc.find_misplaced_receipts( str( zone[ "correct" ] ), persona="Sam",
                                        tmux_session="sam-pane", since=_dt( 15 ) ) == []
    # ...and the same call with the floor moved back DOES see it, so the empty
    # result above is the floor working rather than the scan failing.
    assert len( rwc.find_misplaced_receipts( str( zone[ "correct" ] ), persona="Sam",
                                             tmux_session="sam-pane", since=_dt( 5 ) ) ) == 1


def test_an_undated_stray_cannot_be_shown_to_postdate_the_respin( zone ):
    path = _write( str( zone[ "sibling" ] ), "sidB" )
    body = json.loads( open( path, encoding="utf-8" ).read() )
    body.pop( "booted_at", None )
    open( path, "w", encoding="utf-8" ).write( json.dumps( body ) )
    assert rwc.find_misplaced_receipts( str( zone[ "correct" ] ), persona="Sam",
                                        tmux_session="sam-pane", since=_dt( 15 ) ) == []


def test_unreadable_and_non_dict_files_are_skipped_not_raised( zone ):
    os.makedirs( str( zone[ "sibling" ] ), exist_ok=True )
    open( os.path.join( str( zone[ "sibling" ] ), f"{rwc.RECEIPT_PREFIX}bad.json" ),
          "w", encoding="utf-8" ).write( "{ not json" )
    open( os.path.join( str( zone[ "sibling" ] ), f"{rwc.RECEIPT_PREFIX}list.json" ),
          "w", encoding="utf-8" ).write( "[ 1, 2 ]" )
    _write( str( zone[ "sibling" ] ), "sidB" )
    hits = rwc.find_misplaced_receipts( str( zone[ "correct" ] ),
                                        persona="Sam", tmux_session="sam-pane" )
    assert [ h[ "receipt" ][ "session_id" ] for h in hits ] == [ "sidB" ]


def test_a_missing_base_dir_yields_nothing_rather_than_raising():
    assert rwc.find_misplaced_receipts( None, persona="Sam" ) == []


# ---------------------------------------------------------------------------
# THE DISCRIMINATING PAIR — the reason any of this exists.
# ---------------------------------------------------------------------------
def _dead_no_wake( base, **kw ):
    """Drive the real check past its deadline so the verdict settles DEAD_NO_WAKE."""
    return rwc.check_respin_wake(
        fired_at         = _dt( 20 ),
        persona          = "Sam",
        tmux_session     = "sam-pane",
        base_dir         = str( base ),
        deadline_seconds = 1,
        now_fn           = lambda: _dt( 30 ),
        sleep_fn         = lambda _s: None,
        **kw,
    )


def test_a_seat_that_never_woke_reports_no_misplaced_evidence( zone ):
    a = _dead_no_wake( zone[ "correct" ] )
    assert a.verdict is rwc.WakeVerdict.DEAD_NO_WAKE
    assert a.misplaced == []


def test_a_seat_that_woke_and_wrote_elsewhere_is_now_DISTINGUISHABLE( zone ):
    """
    The pair. Same verdict, same alarm — and one carries the file, so a manager can
    tell 'chase a dead seat' from 'fix a writer' without going to look.
    """
    _write( str( zone[ "sibling" ] ), "sidB" )
    a = _dead_no_wake( zone[ "correct" ] )

    assert a.verdict is rwc.WakeVerdict.DEAD_NO_WAKE
    assert [ h[ "receipt" ][ "session_id" ] for h in a.misplaced ] == [ "sidB" ]
    assert a.misplaced[ 0 ][ "path" ].endswith( f"{rwc.RECEIPT_PREFIX}sidB.json" )


def test_the_detector_changes_no_verdict_and_no_alarm( zone ):
    """
    Scope, pinned. Build the detector, change no behaviour — so the verdict/alarm
    pair must be IDENTICAL with and without a misplaced receipt on disk. Asserted as
    the two runs' actual values, not as a message string.
    """
    without = _dead_no_wake( zone[ "correct" ] )
    _write( str( zone[ "sibling" ] ), "sidB" )
    with_stray = _dead_no_wake( zone[ "correct" ] )

    assert ( without.verdict, without.is_alarm ) == ( with_stray.verdict, with_stray.is_alarm )
    assert without.misplaced != with_stray.misplaced     # ...and only the evidence moved


def test_a_settled_non_dead_verdict_does_not_pay_for_the_scan( zone ):
    """
    The scan runs ONLY where the two failures are confusable. A seat that plainly
    woke has a receipt, so there is nothing to disambiguate and no tree to walk.

    ⚠️ The correctly-placed receipt must be booted AFTER fired_at. A receipt dated
    at or before the fire is treated as the PREDECESSOR's and is no receipt at all —
    the guard that stops a self_respin's own pre-clear boot greening its successor.
    Written the lazy way this test reads DEAD_NO_WAKE and looks like the scan firing
    where it should not; it is the fixture, not the code.
    """
    _write( str( zone[ "correct" ] ), "sidD", booted_at=_dt( 25 ) )
    _write( str( zone[ "sibling" ] ), "sidB", booted_at=_dt( 25 ) )
    a = _dead_no_wake( zone[ "correct" ] )
    assert a.verdict is not rwc.WakeVerdict.DEAD_NO_WAKE
    assert a.misplaced is None
