"""
Unit tests for the self-re-spin liveness observer (WI-1 of row 9e0678f6).

Target: 100% lines + branches + functions on
    src/cosa/agents/heartbeat_arbiter/self_respin_observer.py

The observer answers ONE question the self-clearing seat cannot answer for
itself: "did the seat clear and come back at low context, or did it fire and
die silently?" It rides the arbiter's OWN context-pressure payload — the marker
records the seat was over_budget (why the tick fired self_respin); RETURNED is
that SAME seat flipping to within_budget with a fresh turn after fired_at. There
is no second "low" threshold — observer and verb share the one INI fraction via
the payload's `status` field.

RED-FIRST DISCIPLINE (Cheech's gate): the marquee cases are the ALARM
(`test_dead_no_return_*`) and the NEGATIVE ARM (`test_negative_arm_*` — a seat
that never cleared must never green as RETURNED). A naive "is the seat alive"
oracle would FAIL those two, which is the whole point.

All fixtures are synthetic marker dicts + synthetic pressure records — no live
fleet, no network, no disk beyond tmp_path.
"""

import datetime
import json

import pytest

import cosa.agents.heartbeat_arbiter.self_respin_observer as obs


# ---------------------------------------------------------------------------
# Time helpers — everything is timezone-aware UTC
# ---------------------------------------------------------------------------
UTC = datetime.timezone.utc


def _dt( minute, second=0 ):
    """A fixed aware datetime at 2026-08-14T02:{minute}:{second}Z."""
    return datetime.datetime( 2026, 8, 14, 2, minute, second, tzinfo=UTC )


def _iso( dt ):
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _marker( *, session_id="a2715c0f", persona="cheech", tmux_session="cheech-mgr",
             fired_at=None, expected_return_by=None,
             pre_clear_status="over_budget", pre_clear_pct=62.4,
             memento_path="/data/lupin/.claude-memento.md", memento_verified=True ):
    """A synthetic self-respin marker dict (the on-disk schema)."""
    fired_at           = fired_at           if fired_at           is not None else _iso( _dt( 20 ) )
    expected_return_by = expected_return_by if expected_return_by is not None else _iso( _dt( 22 ) )
    return {
        "session_id"         : session_id,
        "persona"            : persona,
        "tmux_session"       : tmux_session,
        "fired_at"           : fired_at,
        "expected_return_by" : expected_return_by,
        "pre_clear_status"   : pre_clear_status,
        "pre_clear_pct"      : pre_clear_pct,
        "memento_path"       : memento_path,
        "memento_verified"   : memento_verified,
    }


def _pressure_record( *, session_id="a2715c0f", tmux_session="cheech-mgr",
                      status="within_budget", last_turn_age_s=5.0 ):
    """A synthetic arbiter context_pressure persona record (the fields we read)."""
    return {
        "session_id"      : session_id,
        "tmux_session"    : tmux_session,
        "status"          : status,
        "last_turn_age_s" : last_turn_age_s,
    }


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------
def test_parse_iso_roundtrips_aware():
    dt = _dt( 20 )
    assert obs._parse_iso( _iso( dt ) ) == dt


def test_parse_iso_none_and_garbage_return_none():
    assert obs._parse_iso( None ) is None
    assert obs._parse_iso( "not-a-timestamp" ) is None
    assert obs._parse_iso( 12345 ) is None


def test_parse_iso_naive_returns_none():
    """A NAIVE (offset-less) timestamp cannot be compared to aware now → None."""
    assert obs._parse_iso( "2026-08-14T02:20:00" ) is None


# ---------------------------------------------------------------------------
# THE RED CASE — the silently-dead seat the whole observer exists to catch
# ---------------------------------------------------------------------------
def test_dead_no_return_alarm_when_seat_stayed_over_budget():
    """Past deadline + seat still over_budget → DEAD_NO_RETURN alarm."""
    marker = _marker()
    rec    = _pressure_record( status="over_budget" )
    a = obs.classify_marker( marker, rec, now=_dt( 25 ) )   # 02:25 > 02:22 deadline
    assert a.verdict  == obs.SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True


def test_dead_no_return_alarm_when_no_pressure_record_after_deadline():
    """Past deadline + seat absent from the pressure map → DEAD_NO_RETURN alarm."""
    a = obs.classify_marker( _marker(), None, now=_dt( 25 ) )
    assert a.verdict  == obs.SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True


# ---------------------------------------------------------------------------
# THE NEGATIVE ARM — a seat that never cleared must NEVER green as RETURNED
# (a bare alive-check would fail these; that is the control Krishna gated on)
# ---------------------------------------------------------------------------
def test_negative_arm_over_budget_before_deadline_is_pending_not_returned():
    marker = _marker()
    rec    = _pressure_record( status="over_budget" )     # never cleared: still HIGH
    a = obs.classify_marker( marker, rec, now=_dt( 21 ) )  # before 02:22 deadline
    assert a.verdict != obs.SelfRespinVerdict.RETURNED
    assert a.verdict == obs.SelfRespinVerdict.PENDING
    assert a.is_alarm is False


def test_negative_arm_over_budget_after_deadline_never_returns():
    marker = _marker()
    rec    = _pressure_record( status="over_budget" )
    a = obs.classify_marker( marker, rec, now=_dt( 30 ) )
    assert a.verdict != obs.SelfRespinVerdict.RETURNED


# ---------------------------------------------------------------------------
# THE HAPPY PATH — over_budget → within_budget for the same seat, fresh turn
# ---------------------------------------------------------------------------
def test_returned_on_over_to_within_transition_same_seat_fresh():
    marker = _marker()
    rec    = _pressure_record( status="within_budget", last_turn_age_s=5.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 23 ) )  # last turn at 02:22:55, after fired 02:20
    assert a.verdict  == obs.SelfRespinVerdict.RETURNED
    assert a.is_alarm is False


def test_returned_requires_fresh_turn_after_fired_at():
    """within_budget but the last turn PREDATES fired_at → not a proven return."""
    marker = _marker( fired_at=_iso( _dt( 20 ) ) )
    # now 02:21, last turn 10 min ago = 02:11 → BEFORE fired_at 02:20
    rec = _pressure_record( status="within_budget", last_turn_age_s=600.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 21 ) )
    assert a.verdict == obs.SelfRespinVerdict.PENDING


def test_returned_not_confirmed_when_last_turn_age_missing():
    marker = _marker()
    rec    = _pressure_record( status="within_budget", last_turn_age_s=None )
    a = obs.classify_marker( marker, rec, now=_dt( 21 ) )
    assert a.verdict == obs.SelfRespinVerdict.PENDING


def test_returned_requires_marker_recorded_over_budget():
    """A marker that never recorded over_budget cannot claim a high→low transition."""
    marker = _marker( pre_clear_status="within_budget" )
    rec    = _pressure_record( status="within_budget", last_turn_age_s=5.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 21 ) )
    assert a.verdict != obs.SelfRespinVerdict.RETURNED


def test_unparseable_fired_at_is_malformed_alarm_not_pending():
    """A garbage fired_at is UNTRUSTWORTHY, not patient — loud alarm, never PENDING."""
    marker = _marker( fired_at="garbage" )
    rec    = _pressure_record( status="within_budget", last_turn_age_s=5.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 21 ) )
    assert a.verdict  == obs.SelfRespinVerdict.MALFORMED_MARKER
    assert a.is_alarm is True


def test_naive_fired_at_is_malformed_alarm_not_crash( recwarn ):
    """The tz bug Krishna caught: a NAIVE fired_at must NOT raise and must NOT
    degrade to PENDING — it is a loud MALFORMED_MARKER alarm."""
    marker = _marker( fired_at="2026-08-14T02:20:00" )   # no offset
    rec    = _pressure_record( status="within_budget", last_turn_age_s=5.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 25 ) )   # would compare naive vs aware → TypeError pre-fix
    assert a.verdict  == obs.SelfRespinVerdict.MALFORMED_MARKER
    assert a.is_alarm is True


def test_naive_deadline_is_malformed_alarm():
    """A naive expected_return_by would silently pin the seat at PENDING forever."""
    marker = _marker( expected_return_by="2026-08-14T02:22:00" )   # no offset
    a = obs.classify_marker( marker, _pressure_record( status="over_budget" ), now=_dt( 59 ) )
    assert a.verdict  == obs.SelfRespinVerdict.MALFORMED_MARKER
    assert a.is_alarm is True


# ---------------------------------------------------------------------------
# IDENTITY — the seat must come back as the SAME session_id / tmux / persona
# ---------------------------------------------------------------------------
def test_identity_mismatch_tmux_is_alarm():
    marker = _marker( tmux_session="cheech-mgr" )
    rec    = _pressure_record( tmux_session="someone-else", status="within_budget", last_turn_age_s=5.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 23 ) )
    assert a.verdict  == obs.SelfRespinVerdict.IDENTITY_MISMATCH
    assert a.is_alarm is True


def test_identity_mismatch_session_id_is_alarm():
    marker = _marker( session_id="a2715c0f" )
    rec    = _pressure_record( session_id="ffffffff", status="within_budget", last_turn_age_s=5.0 )
    a = obs.classify_marker( marker, rec, now=_dt( 23 ) )
    assert a.verdict == obs.SelfRespinVerdict.IDENTITY_MISMATCH


# ---------------------------------------------------------------------------
# PENDING — no record yet, still inside the window
# ---------------------------------------------------------------------------
def test_pending_before_deadline_no_record():
    a = obs.classify_marker( _marker(), None, now=_dt( 21 ) )
    assert a.verdict  == obs.SelfRespinVerdict.PENDING
    assert a.is_alarm is False


def test_garbage_expected_return_by_is_malformed_alarm():
    """A garbage deadline is loud, not patient — else a dead seat hides in PENDING."""
    marker = _marker( expected_return_by="garbage" )
    a = obs.classify_marker( marker, _pressure_record( status="over_budget" ), now=_dt( 59 ) )
    assert a.verdict  == obs.SelfRespinVerdict.MALFORMED_MARKER
    assert a.is_alarm is True


def test_dead_seat_alarm_still_fires_on_wellformed_marker():
    """Cheech's proof: a well-formed marker past its deadline on a stuck seat
    still raises the DEAD alarm — the loud-malformed state did not muffle it."""
    a = obs.classify_marker( _marker(), _pressure_record( status="over_budget" ), now=_dt( 40 ) )
    assert a.verdict  == obs.SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True


# ---------------------------------------------------------------------------
# build_marker_dict — the shared schema constructor (verb + observer, one shape)
# ---------------------------------------------------------------------------
def test_build_marker_dict_shape_and_deadline_math():
    m = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=_dt( 20 ), delay_seconds=20, grace_seconds=100,
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        memento_path="/m", memento_verified=True,
    )
    assert m[ "session_id" ]         == "s1"
    assert m[ "pre_clear_status" ]   == "over_budget"
    assert m[ "memento_verified" ]   is True
    # deadline = fired_at + delay + grace = 02:20:00 + 120s = 02:22:00
    assert m[ "expected_return_by" ] == _iso( _dt( 22 ) )
    # round-trips through the classifier
    assert obs.classify_marker( m, _pressure_record( session_id="s1", tmux_session="t1", status="over_budget" ),
                                now=_dt( 30 ) ).verdict == obs.SelfRespinVerdict.DEAD_NO_RETURN


def test_build_marker_dict_normalizes_naive_fired_at_to_aware_utc():
    """Our OWN writer must never emit a naive timestamp (the malformed path is
    unreachable in our data). A naive fired_at is stamped +00:00."""
    naive = datetime.datetime( 2026, 8, 14, 2, 20, 0 )   # no tzinfo
    m = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=naive, delay_seconds=20, grace_seconds=100,
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        memento_path="/m", memento_verified=True,
    )
    assert m[ "fired_at" ].endswith( "+00:00" )
    assert obs._parse_iso( m[ "fired_at" ] ) is not None            # aware ⇒ parseable
    assert obs._parse_iso( m[ "expected_return_by" ] ) is not None


# ---------------------------------------------------------------------------
# read_markers — glob + parse + skip malformed, never raise
# ---------------------------------------------------------------------------
def test_read_markers_missing_dir_returns_empty( tmp_path ):
    assert obs.read_markers( base_dir=str( tmp_path / "nope" ) ) == []


def test_read_markers_globs_and_skips_malformed( tmp_path ):
    good = _marker( session_id="good1" )
    ( tmp_path / f"{obs.MARKER_PREFIX}good1.json" ).write_text( json.dumps( good ) )
    ( tmp_path / f"{obs.MARKER_PREFIX}bad.json" ).write_text( "{not json" )
    ( tmp_path / f"{obs.MARKER_PREFIX}list.json" ).write_text( json.dumps( [ 1, 2 ] ) )   # valid JSON, not a dict
    ( tmp_path / "unrelated.json" ).write_text( json.dumps( { "x": 1 } ) )
    markers = obs.read_markers( base_dir=str( tmp_path ) )
    assert [ m[ "session_id" ] for m in markers ] == [ "good1" ]


def test_resolve_base_dir_none_uses_fleet_data_root( monkeypatch, tmp_path ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh
    monkeypatch.setattr( hh, "fleet_data_root", lambda: tmp_path )
    assert obs._resolve_base_dir( None ) == str( tmp_path )


# ---------------------------------------------------------------------------
# observe_fleet_self_respin — IO helper: match markers to records by session_id
# ---------------------------------------------------------------------------
def test_observe_fleet_matches_by_session_id( tmp_path ):
    ( tmp_path / f"{obs.MARKER_PREFIX}a2715c0f.json" ).write_text( json.dumps( _marker() ) )

    def fake_fetch():
        return { "personas": { "cheech": _pressure_record( status="within_budget", last_turn_age_s=5.0 ) } }

    results = obs.observe_fleet_self_respin(
        base_dir=str( tmp_path ), now=_dt( 23 ), fetch_pressure=fake_fetch
    )
    assert len( results ) == 1
    assert results[ 0 ].verdict == obs.SelfRespinVerdict.RETURNED


def test_observe_fleet_unmatched_marker_gets_none_record( tmp_path ):
    ( tmp_path / f"{obs.MARKER_PREFIX}a2715c0f.json" ).write_text( json.dumps( _marker() ) )

    def fake_fetch():
        return { "personas": {} }   # no record for this seat

    results = obs.observe_fleet_self_respin(
        base_dir=str( tmp_path ), now=_dt( 30 ), fetch_pressure=fake_fetch
    )
    assert results[ 0 ].verdict == obs.SelfRespinVerdict.DEAD_NO_RETURN


def test_observe_fleet_tolerates_unreachable_pressure( tmp_path ):
    ( tmp_path / f"{obs.MARKER_PREFIX}a2715c0f.json" ).write_text( json.dumps( _marker() ) )

    def fake_fetch():
        return { "status": "unreachable", "personas": None }

    results = obs.observe_fleet_self_respin(
        base_dir=str( tmp_path ), now=_dt( 21 ), fetch_pressure=fake_fetch
    )
    assert results[ 0 ].verdict == obs.SelfRespinVerdict.PENDING


def test_observe_fleet_empty_when_no_markers( tmp_path ):
    def fake_fetch():
        return { "personas": {} }
    assert obs.observe_fleet_self_respin( base_dir=str( tmp_path ), now=_dt( 21 ), fetch_pressure=fake_fetch ) == []


def test_observe_fleet_skips_bad_pressure_records( tmp_path ):
    """A persona record that is not a dict, or a dict with no session_id, is ignored."""
    ( tmp_path / f"{obs.MARKER_PREFIX}a2715c0f.json" ).write_text( json.dumps( _marker() ) )

    def fake_fetch():
        return { "personas": {
            "junk"      : "not-a-dict",
            "no_id"     : { "status": "within_budget" },                       # dict, but no session_id
        } }

    results = obs.observe_fleet_self_respin(
        base_dir=str( tmp_path ), now=_dt( 30 ), fetch_pressure=fake_fetch
    )
    # marker never matches → None record → past deadline → DEAD
    assert results[ 0 ].verdict == obs.SelfRespinVerdict.DEAD_NO_RETURN


def test_observe_fleet_default_now_and_fetch_no_markers( tmp_path ):
    """Exercise the now=None / fetch_pressure=None default arms (empty dir → no live fetch)."""
    assert obs.observe_fleet_self_respin( base_dir=str( tmp_path ) ) == []


# ---------------------------------------------------------------------------
# Rendering + smoke
# ---------------------------------------------------------------------------
def test_render_table_has_header_and_rows_alarm_and_clean():
    assessments = [
        obs.classify_marker( _marker(), _pressure_record( status="over_budget" ), now=_dt( 30 ) ),  # alarm row
        obs.classify_marker( _marker(), None, now=_dt( 21 ) ),                                        # PENDING (no alarm)
    ]
    table = obs.render_observer_table( assessments )
    assert "VERDICT" in table
    assert "DEAD_NO_RETURN" in table
    assert "PENDING" in table
    assert "ALARM" in table


def test_render_table_empty():
    assert "no self-re-spin markers" in obs.render_observer_table( [] ).lower()


def test_quick_smoke_test_runs( monkeypatch, capsys ):
    monkeypatch.setattr( obs, "observe_fleet_self_respin", lambda **kw: [] )
    obs.quick_smoke_test()
    assert "self-re-spin" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# TTL janitor — sweep confirmed-RETURNED markers (row 6d6a9da2)
#
# The safety property under test: a marker is deleted ONLY when it is BOTH
# confirmed RETURNED (via the real classifier) AND older than the TTL. A PENDING
# marker, any ALARM marker (even an old one), and a young RETURNED marker are all
# kept — the sweep never removes a record whose job is not yet done.
# ---------------------------------------------------------------------------
def _write_marker( tmp_path, sid, **kw ):
    """Write a marker file for `sid`, returning its path."""
    path = tmp_path / f"{obs.MARKER_PREFIX}{sid}.json"
    path.write_text( json.dumps( _marker( session_id=sid, persona=sid, tmux_session=f"{sid}-mgr", **kw ) ) )
    return path


def _returned_fetch( sid ):
    """A fetch whose record makes `sid` classify RETURNED (within_budget, fresh turn)."""
    def fake_fetch():
        return { "personas": { sid: _pressure_record(
            session_id=sid, tmux_session=f"{sid}-mgr", status="within_budget", last_turn_age_s=5.0 ) } }
    return fake_fetch


def test_sweep_empty_dir_returns_empty_and_defaults( tmp_path ):
    """No markers ⇒ [] before any fetch — exercises the now=None / fetch_pressure=None default arms."""
    assert obs.sweep_returned_markers( base_dir=str( tmp_path ) ) == []


def test_sweep_deletes_returned_older_than_ttl( tmp_path ):
    path = _write_marker( tmp_path, "cheech", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    # now = 20 min after fired_at (1200s) > 900s TTL ⇒ swept.
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 40 ), fetch_pressure=_returned_fetch( "cheech" ), ttl_seconds=900 )
    assert swept == [ "cheech" ]
    assert not path.exists()


def test_sweep_keeps_returned_within_ttl( tmp_path ):
    path = _write_marker( tmp_path, "rachel", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    # now = 5 min after fired_at (300s) <= 900s TTL ⇒ RETURNED but too young, kept.
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 25 ), fetch_pressure=_returned_fetch( "rachel" ), ttl_seconds=900 )
    assert swept == []
    assert path.exists()


def test_sweep_leaves_pending_marker( tmp_path ):
    path = _write_marker( tmp_path, "mrradio", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    def fake_fetch():
        return { "personas": {} }                         # no record ⇒ before deadline ⇒ PENDING
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 21 ), fetch_pressure=fake_fetch, ttl_seconds=1 )
    assert swept == []
    assert path.exists()


def test_sweep_never_removes_old_alarm_marker( tmp_path ):
    """The critical safety case: a DEAD_NO_RETURN alarm, even far past the TTL, is KEPT."""
    path = _write_marker( tmp_path, "ghost", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    def fake_fetch():
        return { "personas": None }                       # unreachable ⇒ past deadline ⇒ DEAD_NO_RETURN
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 55 ), fetch_pressure=fake_fetch, ttl_seconds=1 )
    assert swept == []
    assert path.exists()


def test_sweep_tolerates_non_dict_section( tmp_path ):
    """A truthy non-dict pressure section ⇒ no records ⇒ marker matches nothing (kept as DEAD)."""
    path = _write_marker( tmp_path, "weird", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 55 ), fetch_pressure=lambda: "not-a-section", ttl_seconds=1 )
    assert swept == []
    assert path.exists()


def test_sweep_skips_bad_pressure_records_and_still_deletes( tmp_path ):
    """Junk records in the personas map are ignored; the good RETURNED+old marker still sweeps."""
    path = _write_marker( tmp_path, "cheech", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    def fake_fetch():
        return { "personas": {
            "cheech" : _pressure_record( session_id="cheech", tmux_session="cheech-mgr",
                                         status="within_budget", last_turn_age_s=5.0 ),
            "junk"   : "not-a-dict",                       # skipped (not a dict)
            "no_id"  : { "status": "within_budget" },      # skipped (no session_id)
        } }
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 40 ), fetch_pressure=fake_fetch, ttl_seconds=900 )
    assert swept == [ "cheech" ]
    assert not path.exists()


def test_sweep_unlink_failure_is_not_counted( tmp_path, monkeypatch ):
    """A failed unlink ⇒ the session id is NOT reported swept (and no raise)."""
    path = _write_marker( tmp_path, "cheech", fired_at=_iso( _dt( 20 ) ), expected_return_by=_iso( _dt( 22 ) ) )
    monkeypatch.setattr( obs, "_best_effort_unlink", lambda p: False )
    swept = obs.sweep_returned_markers(
        base_dir=str( tmp_path ), now=_dt( 40 ), fetch_pressure=_returned_fetch( "cheech" ), ttl_seconds=900 )
    assert swept == []
    assert path.exists()                                  # our fake unlink left it in place


# ---------------------------------------------------------------------------
# _read_markers_with_paths + _best_effort_unlink — the janitor's IO leaves
# ---------------------------------------------------------------------------
def test_read_markers_with_paths_missing_dir_and_skips( tmp_path ):
    assert obs._read_markers_with_paths( base_dir=str( tmp_path / "nope" ) ) == []
    ( tmp_path / f"{obs.MARKER_PREFIX}good1.json" ).write_text( json.dumps( _marker( session_id="good1" ) ) )
    ( tmp_path / f"{obs.MARKER_PREFIX}bad.json" ).write_text( "{not json" )                 # ValueError → skipped
    ( tmp_path / f"{obs.MARKER_PREFIX}list.json" ).write_text( json.dumps( [ 1, 2 ] ) )     # non-dict → skipped
    pairs = obs._read_markers_with_paths( base_dir=str( tmp_path ) )
    assert [ sid for _, m in pairs for sid in [ m[ "session_id" ] ] ] == [ "good1" ]
    assert pairs[ 0 ][ 0 ].endswith( f"{obs.MARKER_PREFIX}good1.json" )


def test_best_effort_unlink_success_and_failure( tmp_path ):
    p = tmp_path / "victim.json"
    p.write_text( "x" )
    assert obs._best_effort_unlink( str( p ) ) is True
    assert not p.exists()
    assert obs._best_effort_unlink( str( tmp_path / "already-gone.json" ) ) is False
