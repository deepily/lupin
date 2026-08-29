"""
Unit tests for the POST-KILL RE-CHECK (row f94ab580).

THE DEFECT UNDER TEST. `coordinate_mementos` renders its verdict at ASK TIME, and the
kill happens afterwards — so a seat still writing its memento when the ask window
expires is GUARANTEED to be reported as having failed to write one. While it writes,
the slot legitimately holds the PRIOR holder's file, which is exactly what
`prior_holder_present` describes. The classifier reads a true fact about the wrong
moment.

MEASURED 2026-08-25 on a four-seat reap. The alarm named all four. Thirty seconds
later, on disk: clayton's memento (48 lines) and tiffany's (106 lines) were both
present, both complete, both self-naming their own reaped seat; maria's was absent;
maya's slot held a different session's file from the day before. Two of the four
alarms were races. Clayton even DM'd "ready for re-spin — memento on disk, verified"
AFTER he had been killed and logged as unproven.

WHAT THESE TESTS PIN — and the direction that is easy to break while fixing the
first one. The alarm exists because it used to be a silent no-op (row 0a36d83d), and
the three-way verdict vocabulary exists because a race and a genuine loss used to
return the SAME answer (row 3b0c5f90). So a fix that buys fewer false alarms with a
quieter, more forgiving, or slower alarm is worse than the bug. Every test below is
therefore paired: the race must go quiet, AND maria's shape (nothing at the slot) and
maya's shape (another session's file, always) must still fire. Mere existence at the
slot never upgrades anything — identity is re-proven on the same predicate the reap
used, which is what maya's wrong-but-plausible verdict came from getting wrong.

Every seam (clock, file read, DM send, sleep, tmux) is injected — no live server.
"""

import datetime
import json

import pytest

from lupin_mcp import reap_memento
from lupin_mcp import session_spawner as ss


# ── The measured four-seat reap, as fixtures ──────────────────────────────────
_NOW  = datetime.datetime( 2026, 8, 25, 21, 4, 30, tzinfo=datetime.timezone.utc )
_REPO = "/repos/lupin"

_CLAYTON_SID = "041e7a93aaaa"    # landed at 17:04:09, mid-write at ask time
_TIFFANY_SID = "8198f1d1bbbb"    # landed at 17:04:20, mid-write at ask time
_MARIA_SID   = "cccccccc1111"    # nothing at the slot, ever — really lost
_MAYA_SID    = "7ebbfb0cdddd"    # slot holds 127213b5 from the day before
_PRIOR_SID   = "d4af6641eeee"    # the prior holder clayton/tiffany's slots held
_MAYA_PRIOR  = "127213b5ffff"


def _now_fn():
    return _NOW


def _memento( persona, sid8, written_at="2026-08-25T21:04:00+00:00", body_bytes=1200 ):
    """A complete, fresh memento carrying a line-1 memento-record header."""
    header = ( f"<!-- memento-record: persona={persona} session_id={sid8} "
               f"written_at={written_at} slot=io -->\n" )
    return header + ( "x" * body_bytes )


class _Disk:
    """Injected file store: str(path) -> text; a missing key reads as None."""
    def __init__( self, files=None ):
        self.files = dict( files or {} )
    def read( self, path ):
        return self.files.get( str( path ) )


def _ident( name, sid, cwd=_REPO ):
    return { "persona": { "name": name }, "session_id": sid, "cwd": cwd }


def _slot( slug, repo=_REPO ):
    return f"{repo}/io/mementos/{slug}.md"


def _recheck( outcomes, identities, disk ):
    return reap_memento.recheck_losing_seats(
        outcomes, identities, now_fn=_now_fn, read_text_fn=disk.read )


def _losing( status, persona, sid ):
    """A `coordinate_mementos` outcome as it stands at ask time."""
    return { "status": status, "reason": f"asked, ... at ask time: {status}",
             "persona": persona, "session_id": sid, "slot": _slot( persona.lower() ) }


# ── FALSIFIER (a): the race goes quiet ────────────────────────────────────────
def test_seat_whose_memento_lands_during_teardown_is_upgraded_to_written():
    """
    THE RED. clayton's exact shape: at ask time his slot held the prior holder
    d4af6641, so he was reported `prior_holder_present` and named in the alarm; his
    own 48-line memento hit the disk seconds later, during teardown. Before this
    change nothing looked again, so he was killed and recorded as having failed to
    write a memento he had in fact written.
    """
    disk = _Disk( { _slot( "clayton" ): _memento( "Clayton", _CLAYTON_SID[ :8 ] ) } )
    out  = _recheck(
        { "cc-clayton-1": _losing( "prior_holder_present", "Clayton", _CLAYTON_SID ) },
        { "cc-clayton-1": _ident( "Clayton", _CLAYTON_SID ) }, disk )
    seat = out[ "cc-clayton-1" ]

    # "written", NOT "verified": he WAS asked, and his file appeared after the ask.
    # Reporting "verified" would claim no DM was sent, which is false.
    assert seat[ "status" ] == "written"
    assert "during teardown" in seat[ "reason" ]
    # The ask-time verdict survives in the reason — the race is explained, not erased.
    assert "prior_holder_present" in seat[ "reason" ]
    assert reap_memento.memento_alarm( out ) is None


def test_the_upgrade_reaches_the_alarm_for_the_race_but_not_the_real_losses():
    """
    The measured four-seat reap, whole. Two races go quiet; the two genuine losses
    stay in the alarm, with their own verdicts intact. An alarm that went silent on
    all four would be the failure mode this row forbids.
    """
    disk = _Disk( {
        _slot( "clayton" ) : _memento( "Clayton", _CLAYTON_SID[ :8 ] ),   # landed during teardown
        _slot( "tiffany" ) : _memento( "Tiffany", _TIFFANY_SID[ :8 ] ),   # landed during teardown
        _slot( "maya" )    : _memento( "Maya",    _MAYA_PRIOR[ :8 ],      # yesterday's holder
                                       written_at="2026-08-24T22:44:00+00:00" ),
    } )                                                                    # maria: absent
    outcomes = {
        "cc-clayton-1" : _losing( "prior_holder_present", "Clayton", _CLAYTON_SID ),
        "cc-tiffany-1" : _losing( "unparseable_present",  "Tiffany", _TIFFANY_SID ),
        "cc-maria-1"   : _losing( "timeout_no_memento",   "Maria",   _MARIA_SID ),
        "cc-maya-1"    : _losing( "prior_holder_present", "Maya",    _MAYA_SID ),
    }
    identities = {
        "cc-clayton-1" : _ident( "Clayton", _CLAYTON_SID ),
        "cc-tiffany-1" : _ident( "Tiffany", _TIFFANY_SID ),
        "cc-maria-1"   : _ident( "Maria",   _MARIA_SID ),
        "cc-maya-1"    : _ident( "Maya",    _MAYA_SID ),
    }
    out   = _recheck( outcomes, identities, disk )
    alarm = reap_memento.memento_alarm( out )

    assert out[ "cc-clayton-1" ][ "status" ] == "written"
    assert out[ "cc-tiffany-1" ][ "status" ] == "written"
    assert alarm is not None
    assert "2 seat(s)" in alarm
    assert "cc-maria-1" in alarm and "cc-maya-1" in alarm
    assert "cc-clayton-1" not in alarm and "cc-tiffany-1" not in alarm
    # The alarm's own wording is untouched — habits are built on it.
    assert alarm.startswith( "REAPED WITHOUT A PROVEN MEMENTO" )


# ── FALSIFIER (b): nothing at the slot still fires ────────────────────────────
def test_seat_with_nothing_at_the_slot_still_reports_timeout_no_memento():
    """
    maria's shape, and the reason this fix cannot be a blanket second chance. There
    is no file at all; a second look finds the same nothing and must say so, with the
    verdict and the reason it already had.
    """
    before = _losing( "timeout_no_memento", "Maria", _MARIA_SID )
    out    = _recheck( { "cc-maria-1": dict( before ) },
                       { "cc-maria-1": _ident( "Maria", _MARIA_SID ) }, _Disk() )

    assert out[ "cc-maria-1" ] == before          # verdict AND reason, verbatim
    assert reap_memento.memento_alarm( out ) is not None


# ── FALSIFIER (c): another session's file still fires ─────────────────────────
def test_seat_whose_slot_holds_another_session_still_reports_prior_holder():
    """
    maya's shape, and the trap: her slot DOES hold a complete, parseable, perfectly
    readable memento. A re-check that asked only "is a file there now?" would upgrade
    her and hand a manager somebody else's context under her name. The header's
    session_id is re-proven, so it does not.
    """
    disk   = _Disk( { _slot( "maya" ): _memento( "Maya", _MAYA_PRIOR[ :8 ],
                                                 written_at="2026-08-25T21:04:10+00:00" ) } )
    before = _losing( "prior_holder_present", "Maya", _MAYA_SID )
    out    = _recheck( { "cc-maya-1": dict( before ) },
                       { "cc-maya-1": _ident( "Maya", _MAYA_SID ) }, disk )

    assert out[ "cc-maya-1" ] == before
    assert reap_memento.memento_alarm( out ) is not None


# ── The re-check touches nothing it was not asked to ──────────────────────────
@pytest.mark.parametrize( "status", [ "verified", "written", "not_requested",
                                      "skipped", "skipped_no_cwd" ] )
def test_non_recheckable_verdicts_pass_through_untouched( status ):
    """
    Both `skipped*` verdicts name NO derivable slot — there is no file a second look
    could read — and the three settled verdicts have nothing to re-decide. A file
    sitting at the same-named slot must not tempt any of them into an upgrade.
    """
    disk   = _Disk( { _slot( "sam" ): _memento( "Sam", _CLAYTON_SID[ :8 ] ) } )
    before = { "status": status, "reason": "as recorded", "persona": "Sam",
               "session_id": _CLAYTON_SID }
    out    = _recheck( { "cc-sam-1": dict( before ) },
                       { "cc-sam-1": _ident( "Sam", _CLAYTON_SID ) }, disk )

    assert out[ "cc-sam-1" ] == before


def test_coordination_error_string_passes_through_untouched():
    """`_error` is a coordination failure, not a seat — it is a string, not a dict."""
    out = _recheck( { "_error": "coordinator exploded" }, {}, _Disk() )

    assert out[ "_error" ] == "coordinator exploded"


def test_seat_with_no_resolvable_repo_root_is_not_upgraded():
    """
    No cwd in the bridge means the seat's REPO is unknown. Verifying against a guessed
    root skips the merge-claim gate and reads a same-named slot in the wrong repo — a
    quieter alarm bought with a weaker check. Refuse, and keep the loud verdict.
    """
    before = _losing( "timeout_no_memento", "Maria", _MARIA_SID )
    out    = _recheck( { "cc-maria-1": dict( before ) },
                       { "cc-maria-1": _ident( "Maria", _MARIA_SID, cwd=None ) }, _Disk() )

    assert out[ "cc-maria-1" ] == before


def test_input_outcomes_are_never_mutated():
    """The caller keeps a usable ask-time record even after the re-check revises it."""
    disk     = _Disk( { _slot( "clayton" ): _memento( "Clayton", _CLAYTON_SID[ :8 ] ) } )
    outcomes = { "cc-clayton-1": _losing( "prior_holder_present", "Clayton", _CLAYTON_SID ) }
    out      = _recheck( outcomes, { "cc-clayton-1": _ident( "Clayton", _CLAYTON_SID ) }, disk )

    assert out is not outcomes
    assert outcomes[ "cc-clayton-1" ][ "status" ] == "prior_holder_present"
    assert out[ "cc-clayton-1" ][ "status" ] == "written"


def test_live_seams_read_the_real_disk_and_the_real_clock( tmp_path ):
    """
    The default seams, exercised. `now_fn`/`read_text_fn` default to the live clock and
    a real file read, so the freshness window is measured against the wall clock — a
    memento stamped now must upgrade through the un-injected path.
    """
    slot = tmp_path / "io" / "mementos" / "clayton.md"
    slot.parent.mkdir( parents=True )
    written = datetime.datetime.now( datetime.timezone.utc ).isoformat()
    slot.write_text( _memento( "Clayton", _CLAYTON_SID[ :8 ], written_at=written ) )

    out = reap_memento.recheck_losing_seats(
        { "cc-clayton-1": _losing( "prior_holder_present", "Clayton", _CLAYTON_SID ) },
        { "cc-clayton-1": _ident( "Clayton", _CLAYTON_SID, cwd=str( tmp_path ) ) } )

    assert out[ "cc-clayton-1" ][ "status" ] == "written"


# ── End to end through dismiss_sessions: the file lands AT THE KILL ───────────
def _bridge( session_dir, tmux_name, persona, sid, cwd=_REPO ):
    ( session_dir / f"cc-{tmux_name}.json" ).write_text( json.dumps( {
        "tmux_session"      : tmux_name,
        "stable_session_id" : sid,
        "voice_persona"     : { "name": persona },
        "cwd"               : cwd,
    } ) )


def _reap( tmp_path, disk, seats, *, recheck=True, recheck_fn=None ):
    """
    Drive dismiss_sessions with the LIVE coordinator and (optionally) the LIVE
    re-check. The tmux runner writes the late mementos into `disk` — the seats land
    their files AT THE KILL, which is the exact moment the defect is about.
    """
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    for tmux_name, ( persona, sid, cwd ) in seats.items():
        _bridge( session_dir, tmux_name, persona, sid, cwd )

    def runner( argv, **kwargs ):
        # The kill is what ends a seat's chance to write. clayton and tiffany get
        # theirs down in the same instant.
        disk.files[ _slot( "clayton" ) ] = _memento( "Clayton", _CLAYTON_SID[ :8 ] )
        disk.files[ _slot( "tiffany" ) ] = _memento( "Tiffany", _TIFFANY_SID[ :8 ] )
        return type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )()

    def coord( identities ):
        return reap_memento.coordinate_mementos(
            identities, write_memento=True, now_fn=_now_fn, read_text_fn=disk.read,
            dm_fn=lambda p, s, b: { "status": "sent" }, sleep_fn=lambda _s: None,
            ask_timeout_sec=6, poll_interval_sec=3 )

    live = recheck_fn if recheck_fn is not None else (
        lambda outcomes, identities: reap_memento.recheck_losing_seats(
            outcomes, identities, now_fn=_now_fn, read_text_fn=disk.read ) )

    return ss.dismiss_sessions(
        "mgr-session", session_names=list( seats ), runner=runner, session_dir=session_dir,
        write_memento=True, memento_coord_fn=coord,
        memento_recheck_fn=live if recheck else None,
        emit_reap_fn=lambda ident, reason="": None, emit_reaped_fn=lambda ident: None )


_FOUR_SEATS = {
    "cc-clayton-1" : ( "Clayton", _CLAYTON_SID, _REPO ),
    "cc-tiffany-1" : ( "Tiffany", _TIFFANY_SID, _REPO ),
    "cc-maria-1"   : ( "Maria",   _MARIA_SID,   _REPO ),
    "cc-maya-1"    : ( "Maya",    _MAYA_SID,    _REPO ),
}


def _four_seat_disk():
    return _Disk( {
        # clayton's and tiffany's slots hold the PRIOR holder while they write.
        _slot( "clayton" ) : _memento( "Clayton", _PRIOR_SID[ :8 ] ),
        _slot( "tiffany" ) : _memento( "Tiffany", _PRIOR_SID[ :8 ] ),
        _slot( "maya" )    : _memento( "Maya", _MAYA_PRIOR[ :8 ],
                                       written_at="2026-08-24T22:44:00+00:00" ),
    } )                                                          # maria: nothing, ever


def test_without_the_recheck_the_reap_alarms_on_all_four( tmp_path ):
    """
    THE RED, at the level the manager actually reads. This is the run that happened:
    with no second look, the result names four seats — and two of them have complete,
    self-named mementos sitting on disk by the time it is composed.
    """
    disk = _four_seat_disk()
    res  = _reap( tmp_path, disk, _FOUR_SEATS, recheck=False )

    assert "4 seat(s)" in res[ "memento_alarm" ]
    assert res[ "memento_outcomes" ][ "cc-clayton-1" ][ "status" ] != "written"
    # ...while the proof was on disk the whole time the alarm was being composed.
    assert disk.read( _slot( "clayton" ) ) is not None


def test_with_the_recheck_the_reap_alarms_only_on_the_two_real_losses( tmp_path ):
    """THE GREEN. Same reap, same disk, same instant — one look after the kill."""
    res = _reap( tmp_path, _four_seat_disk(), _FOUR_SEATS )

    assert "2 seat(s)" in res[ "memento_alarm" ]
    assert "cc-maria-1" in res[ "memento_alarm" ]
    assert "cc-maya-1"  in res[ "memento_alarm" ]
    assert res[ "memento_outcomes" ][ "cc-clayton-1" ][ "status" ] == "written"
    assert res[ "memento_outcomes" ][ "cc-tiffany-1" ][ "status" ] == "written"
    assert res[ "memento_outcomes" ][ "cc-maria-1"   ][ "status" ] == "timeout_no_memento"
    assert res[ "memento_outcomes" ][ "cc-maya-1"    ][ "status" ] == "prior_holder_present"
    # The reap itself is unchanged — every seat still dies.
    assert [ d[ "status" ] for d in res[ "dismissed" ] ] == [ "killed" ] * 4


def test_a_raising_recheck_never_breaks_the_reap_and_is_surfaced( tmp_path ):
    """
    FAIL-SAFE, same posture as the coordinator. A second look that explodes must not
    take the reap down, must not discard the honest ask-time verdicts, and must not
    vanish — a manager reading a clean-looking alarm has to know it may be stale.
    """
    def boom( outcomes, identities ):
        raise RuntimeError( "recheck exploded" )

    res = _reap( tmp_path, _four_seat_disk(), _FOUR_SEATS, recheck_fn=boom )

    assert "recheck exploded" in res[ "memento_outcomes" ][ "_recheck_error" ]
    assert "RuntimeError" in res[ "memento_outcomes" ][ "_recheck_error" ]
    assert "4 seat(s)" in res[ "memento_alarm" ]           # ask-time verdicts survive
    assert [ d[ "status" ] for d in res[ "dismissed" ] ] == [ "killed" ] * 4


def test_seat_with_no_identity_at_all_is_not_upgraded():
    """
    A seat whose bridge could not be read has no repo and no persona — the same
    refusal as a missing cwd, reached by a different road. It keeps its loud verdict
    rather than being verified against a slot nobody can derive.
    """
    disk   = _Disk( { _slot( "maria" ): _memento( "Maria", _MARIA_SID[ :8 ] ) } )
    before = _losing( "timeout_no_memento", "Maria", _MARIA_SID )
    out    = _recheck( { "cc-maria-1": dict( before ) }, { "cc-maria-1": None }, disk )

    assert out[ "cc-maria-1" ] == before
