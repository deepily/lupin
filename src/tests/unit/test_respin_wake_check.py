"""
Unit tests for the re-spin wake check (row b0570b67).

EVERY GUARD GETS ITS INVERSE CONTROL. A check with no test proving it FIRES is
not a check — it is a comment that happens to compile. So each alarm here is
paired with the case that must stay quiet, and the two incidents the row was
written from (Pocholo's lost wake, Krishna's stale memento) each have a test
named after them.
"""

import datetime
import json
import os

import pytest

from cosa.agents.heartbeat_arbiter import respin_wake_check as rwc


FIRED = datetime.datetime( 2026, 8, 21, 21, 26, tzinfo=datetime.timezone.utc )


def _at( seconds ):
    """An aware datetime `seconds` after the re-spin fired."""
    return FIRED + datetime.timedelta( seconds=seconds )


def _receipt( **overrides ):
    """A healthy boot receipt, overridable field by field."""
    body = {
        "session_id"         : "9e0b977d",
        "persona"            : "maya",
        "tmux_session"       : "cc-maya-1",
        "booted_at"          : _at( 5 ).isoformat(),
        "memento_path"       : "/repo/.claude-memento-maya-9e0b977d.md",
        "memento_written_at" : _at( -120 ).isoformat(),
        "memento_persona"    : "maya",
        "memento_slot"       : rwc.SLOT_ROOT,
        "repo_root"          : "/repo",
    }
    body.update( overrides )
    return body


# ── _parse_iso ────────────────────────────────────────────────────────────────

def test_parse_iso_accepts_an_aware_stamp():
    assert rwc._parse_iso( "2026-08-21T21:26:00+00:00" ) == FIRED


@pytest.mark.parametrize( "value", [ None, 42, "", "   ", "not-a-date", "2026-08-21T21:26:00" ] )
def test_parse_iso_rejects_empty_naive_and_unparseable( value ):
    # The naive case is the load-bearing one: assuming local time here would let a
    # wrong-by-hours comparison green a dead seat.
    assert rwc._parse_iso( value ) is None


# ── classify_memento_slot ─────────────────────────────────────────────────────

def test_slot_none_when_nothing_resolved():
    assert rwc.classify_memento_slot( None, "/repo" ) == rwc.SLOT_NONE


def test_slot_root_for_a_record_at_the_repo_root():
    assert rwc.classify_memento_slot( "/repo/.claude-memento-maya-1234abcd.md", "/repo" ) == rwc.SLOT_ROOT


def test_slot_repo_io_for_the_in_repo_io_slot():
    assert rwc.classify_memento_slot( "/repo/io/mementos/maya-1234abcd.md", "/repo" ) == rwc.SLOT_REPO_IO


def test_slot_mirror_at_the_mirror_top_level( tmp_path ):
    mirror = str( tmp_path / "mementos" )
    path   = os.path.join( mirror, "lupin", ".claude-memento-krishna-1234abcd.md" )
    assert rwc.classify_memento_slot( path, "/repo", mirror_root=mirror ) == rwc.SLOT_MIRROR


def test_slot_mirror_for_the_mirrors_own_io_sub_slot( tmp_path ):
    mirror = str( tmp_path / "mementos" )
    path   = os.path.join( mirror, "lupin", "io", "mementos", "krishna-1234abcd.md" )
    assert rwc.classify_memento_slot( path, "/repo", mirror_root=mirror ) == rwc.SLOT_MIRROR


def test_slot_mirror_derives_the_default_mirror_root_from_home( monkeypatch, tmp_path ):
    monkeypatch.setenv( "HOME", str( tmp_path ) )
    path = str( tmp_path / ".claude" / "mementos" / "lupin" / ".claude-memento-krishna-1234abcd.md" )
    assert rwc.classify_memento_slot( path, "/repo" ) == rwc.SLOT_MIRROR


def test_slot_repo_wins_when_the_repo_lives_under_the_mirror_root( tmp_path ):
    # The repo tests run first on purpose: a repo that happens to sit under the
    # mirror root is still a repo, and calling it a mirror would alarm forever.
    mirror = str( tmp_path / "mementos" )
    repo   = os.path.join( mirror, "checkout" )
    path   = os.path.join( repo, ".claude-memento-maya-1234abcd.md" )
    assert rwc.classify_memento_slot( path, repo, mirror_root=mirror ) == rwc.SLOT_ROOT


def test_slot_unknown_for_a_path_under_no_known_root( tmp_path ):
    assert rwc.classify_memento_slot( "/somewhere/else/m.md", "/repo",
                                      mirror_root=str( tmp_path ) ) == rwc.SLOT_UNKNOWN


def test_slot_unknown_when_no_repo_root_is_known( tmp_path ):
    assert rwc.classify_memento_slot( "/repo/.claude-memento-maya-1.md", None,
                                      mirror_root=str( tmp_path ) ) == rwc.SLOT_UNKNOWN


# ── build_receipt_dict / write_boot_receipt / read_receipt ───────────────────

def test_build_receipt_dict_classifies_the_slot_at_write_time():
    body = rwc.build_receipt_dict(
        session_id="s1", persona="maya", tmux_session="cc-1",
        memento_path="/repo/.claude-memento-maya-1.md", memento_written_at="2026-08-21T21:00:00+00:00",
        repo_root="/repo", booted_at=_at( 5 ),
    )
    assert body[ "memento_slot" ] == rwc.SLOT_ROOT
    assert body[ "booted_at" ]    == _at( 5 ).isoformat()
    assert body[ "tmux_session" ] == "cc-1"


def test_build_receipt_dict_records_slot_none_when_nothing_resolved():
    body = rwc.build_receipt_dict(
        session_id="s1", persona="maya", tmux_session=None,
        memento_path=None, memento_written_at=None, repo_root="/repo", booted_at=_at( 5 ),
    )
    assert body[ "memento_slot" ] == rwc.SLOT_NONE
    assert body[ "memento_path" ] is None


def test_write_boot_receipt_round_trips( tmp_path ):
    path = rwc.write_boot_receipt(
        session_id="s1", persona="maya", tmux_session="cc-1",
        memento_path="/repo/.claude-memento-maya-1.md", memento_written_at="2026-08-21T21:00:00+00:00",
        repo_root="/repo", base_dir=str( tmp_path ), now=_at( 5 ),
    )
    assert os.path.basename( path ) == f"{rwc.RECEIPT_PREFIX}s1.json"
    assert rwc.read_receipt( str( tmp_path ), "s1" )[ "memento_slot" ] == rwc.SLOT_ROOT


def test_write_boot_receipt_still_writes_when_no_memento_resolved( tmp_path ):
    # THE point of the receipt: "woke but consumed nothing" must not look like
    # "never woke". Skipping the write here would collapse the two.
    rwc.write_boot_receipt( session_id="s1", base_dir=str( tmp_path ), now=_at( 5 ) )
    assert rwc.read_receipt( str( tmp_path ), "s1" )[ "memento_slot" ] == rwc.SLOT_NONE


def test_write_boot_receipt_stamps_its_own_clock_when_none_is_given( tmp_path ):
    rwc.write_boot_receipt( session_id="s1", base_dir=str( tmp_path ) )
    assert rwc._parse_iso( rwc.read_receipt( str( tmp_path ), "s1" )[ "booted_at" ] ) is not None


def test_write_boot_receipt_returns_none_without_a_session_id( tmp_path ):
    assert rwc.write_boot_receipt( session_id=None, base_dir=str( tmp_path ) ) is None
    assert rwc.write_boot_receipt( session_id="",   base_dir=str( tmp_path ) ) is None


def test_write_boot_receipt_swallows_an_io_failure( tmp_path ):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text( "x" )
    assert rwc.write_boot_receipt( session_id="s1", base_dir=str( blocker / "sub" ) ) is None


def test_write_boot_receipt_resolves_fleet_data_root_when_no_base_dir( monkeypatch, tmp_path ):
    monkeypatch.setattr( rwc, "_resolve_base_dir", lambda base_dir: str( tmp_path ) )
    assert rwc.write_boot_receipt( session_id="s1" ) is not None


def test_read_receipt_returns_none_when_absent( tmp_path ):
    assert rwc.read_receipt( str( tmp_path ), "nope" ) is None


def test_read_receipt_returns_none_on_unparseable_json( tmp_path ):
    ( tmp_path / f"{rwc.RECEIPT_PREFIX}s1.json" ).write_text( "{ not json" )
    assert rwc.read_receipt( str( tmp_path ), "s1" ) is None


def test_read_receipt_returns_none_when_the_body_is_not_a_dict( tmp_path ):
    ( tmp_path / f"{rwc.RECEIPT_PREFIX}s1.json" ).write_text( "[1, 2, 3]" )
    assert rwc.read_receipt( str( tmp_path ), "s1" ) is None


def test_resolve_base_dir_passes_an_explicit_dir_through():
    assert rwc._resolve_base_dir( "/somewhere" ) == "/somewhere"


def test_resolve_base_dir_falls_back_to_fleet_data_root():
    # The fallback is the placement rule this file must not get wrong: receipts
    # live under fleet_data_root(), never the repo root, or no reader sees them.
    resolved = rwc._resolve_base_dir( None )
    assert isinstance( resolved, str ) and resolved


# ── find_receipt_by_identity ─────────────────────────────────────────────────

def _drop( tmp_path, sid, **overrides ):
    body = _receipt( session_id=sid, **overrides )
    ( tmp_path / f"{rwc.RECEIPT_PREFIX}{sid}.json" ).write_text( json.dumps( body ) )
    return body


def test_find_by_persona_returns_the_newest_after_the_floor( tmp_path ):
    _drop( tmp_path, "old", booted_at=_at( 2 ).isoformat() )
    _drop( tmp_path, "new", booted_at=_at( 30 ).isoformat() )
    found = rwc.find_receipt_by_identity( str( tmp_path ), persona="maya", since=FIRED )
    assert found[ "session_id" ] == "new"


def test_find_by_tmux_session_matches_exactly( tmp_path ):
    _drop( tmp_path, "a", tmux_session="cc-maya-1" )
    _drop( tmp_path, "b", tmux_session="cc-other-1" )
    found = rwc.find_receipt_by_identity( str( tmp_path ), tmux_session="cc-other-1" )
    assert found[ "session_id" ] == "b"


def test_find_is_case_and_space_insensitive_on_the_persona( tmp_path ):
    _drop( tmp_path, "a", persona="Maya" )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="  maya " )[ "session_id" ] == "a"


def test_find_skips_a_receipt_older_than_the_floor( tmp_path ):
    _drop( tmp_path, "a", booted_at=_at( -60 ).isoformat() )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="maya", since=FIRED ) is None


def test_find_skips_an_undated_receipt_when_a_floor_is_set( tmp_path ):
    _drop( tmp_path, "a", booted_at=None )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="maya", since=FIRED ) is None


def test_find_keeps_an_undated_receipt_when_no_floor_is_set( tmp_path ):
    _drop( tmp_path, "a", booted_at=None )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="maya" )[ "session_id" ] == "a"


def test_find_prefers_a_dated_receipt_over_an_undated_one( tmp_path ):
    _drop( tmp_path, "undated", booted_at=None )
    _drop( tmp_path, "dated",   booted_at=_at( 9 ).isoformat() )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="maya" )[ "session_id" ] == "dated"


def test_find_refuses_a_blank_query( tmp_path ):
    # A blank query must never hand back some arbitrary seat's receipt as if it
    # were the successor's — that would green a dead seat with a stranger's boot.
    _drop( tmp_path, "a" )
    assert rwc.find_receipt_by_identity( str( tmp_path ) ) is None


def test_find_skips_unreadable_and_non_dict_files( tmp_path ):
    ( tmp_path / f"{rwc.RECEIPT_PREFIX}bad.json"  ).write_text( "{ not json" )
    ( tmp_path / f"{rwc.RECEIPT_PREFIX}list.json" ).write_text( "[]" )
    _drop( tmp_path, "good" )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="maya" )[ "session_id" ] == "good"


def test_find_returns_none_when_nothing_matches( tmp_path ):
    _drop( tmp_path, "a", persona="someone-else" )
    assert rwc.find_receipt_by_identity( str( tmp_path ), persona="maya" ) is None


def test_norm_leaves_a_non_string_as_none():
    assert rwc._norm( 7 ) is None


# ── classify_wake — the alarms, each with its inverse control ────────────────

def test_pocholo_no_receipt_past_the_deadline_alarms():
    # The incident: /clear fired at 21:26, the wake never arrived, and the seat
    # sat at an empty prompt for twenty minutes with nothing alarming.
    got = rwc.classify_wake( None, fired_at=FIRED, now=_at( 200 ) )
    assert got.verdict is rwc.WakeVerdict.DEAD_NO_WAKE
    assert got.is_alarm
    assert "never reached a prompt" in got.reason


def test_inverse_no_receipt_inside_the_window_stays_quiet():
    got = rwc.classify_wake( None, fired_at=FIRED, now=_at( 10 ) )
    assert got.verdict is rwc.WakeVerdict.PENDING
    assert not got.is_alarm


def test_krishna_a_mirror_slot_read_alarms():
    # The incident: the successor woke, but rehydrated from a stale copy under
    # ~/.claude/mementos instead of the live record. Alive and wrong.
    got = rwc.classify_wake( _receipt( memento_slot=rwc.SLOT_MIRROR,
                                       memento_path="/home/x/.claude/mementos/lupin/m.md" ),
                             fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.STALE_SLOT
    assert got.is_alarm
    assert got.memento_path == "/home/x/.claude/mementos/lupin/m.md"


def test_krishna_variant_alarms_even_when_the_mirror_copy_looks_fresh():
    # The slot is disqualifying on its own. A mirror copy written one second ago
    # is still not the live record.
    got = rwc.classify_wake( _receipt( memento_slot=rwc.SLOT_MIRROR,
                                       memento_written_at=_at( 29 ).isoformat() ),
                             fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.STALE_SLOT


def test_an_unknown_slot_alarms_too():
    got = rwc.classify_wake( _receipt( memento_slot=rwc.SLOT_UNKNOWN ), fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.STALE_SLOT


def test_inverse_the_repo_io_slot_is_live_and_stays_quiet():
    got = rwc.classify_wake( _receipt( memento_slot=rwc.SLOT_REPO_IO ), fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.RETURNED
    assert not got.is_alarm


def test_a_live_slot_record_older_than_the_limit_alarms():
    got = rwc.classify_wake( _receipt( memento_written_at=_at( -7200 ).isoformat() ),
                             fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.STALE_MEMENTO
    assert got.is_alarm


def test_inverse_a_record_inside_the_age_limit_stays_quiet():
    got = rwc.classify_wake( _receipt( memento_written_at=_at( -600 ).isoformat() ),
                             fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.RETURNED


def test_an_undated_live_record_is_returned_not_stale():
    # An undated record is UNMEASURABLE. Inventing an alarm out of an absent
    # measurement is how a check earns its way into being ignored.
    got = rwc.classify_wake( _receipt( memento_written_at=None ), fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.RETURNED


def test_woke_with_no_memento_at_all_alarms():
    got = rwc.classify_wake( _receipt( memento_path=None, memento_slot=rwc.SLOT_NONE ),
                             fired_at=FIRED, now=_at( 30 ) )
    assert got.verdict is rwc.WakeVerdict.SEED_NOT_CONSUMED
    assert got.is_alarm


def test_inverse_no_memento_is_fine_when_none_was_expected():
    got = rwc.classify_wake( _receipt( memento_path=None, memento_slot=rwc.SLOT_NONE ),
                             fired_at=FIRED, now=_at( 30 ), expect_memento=False )
    assert got.verdict is rwc.WakeVerdict.RETURNED


def test_the_predecessors_own_receipt_cannot_green_the_check():
    # A self_respin keeps its session id, so the PRE-clear boot already left a
    # receipt under that id. Without the fired_at guard this dead seat reads green.
    got = rwc.classify_wake( _receipt( booted_at=_at( -5 ).isoformat() ),
                             fired_at=FIRED, now=_at( 200 ) )
    assert got.verdict is rwc.WakeVerdict.DEAD_NO_WAKE
    assert "PREDECESSOR" in got.reason


def test_a_receipt_dated_exactly_at_fire_time_is_still_the_predecessors():
    got = rwc.classify_wake( _receipt( booted_at=FIRED.isoformat() ), fired_at=FIRED, now=_at( 200 ) )
    assert got.verdict is rwc.WakeVerdict.DEAD_NO_WAKE


def test_inverse_only_the_predecessors_receipt_inside_the_window_stays_pending():
    got = rwc.classify_wake( _receipt( booted_at=_at( -5 ).isoformat() ), fired_at=FIRED, now=_at( 10 ) )
    assert got.verdict is rwc.WakeVerdict.PENDING


def test_an_unreadable_booted_at_alarms_past_the_deadline():
    got = rwc.classify_wake( _receipt( booted_at="whenever" ), fired_at=FIRED, now=_at( 200 ) )
    assert got.verdict is rwc.WakeVerdict.MALFORMED_RECEIPT
    assert got.is_alarm
    assert got.memento_path == "/repo/.claude-memento-maya-9e0b977d.md"


def test_inverse_an_unreadable_booted_at_inside_the_window_stays_pending():
    got = rwc.classify_wake( _receipt( booted_at="whenever" ), fired_at=FIRED, now=_at( 10 ) )
    assert got.verdict is rwc.WakeVerdict.PENDING


@pytest.mark.parametrize( "fired,now", [ ( None, _at( 5 ) ), ( FIRED, None ) ] )
def test_a_missing_clock_alarms_rather_than_greening( fired, now ):
    got = rwc.classify_wake( _receipt(), fired_at=fired, now=now )
    assert got.verdict is rwc.WakeVerdict.MALFORMED_RECEIPT
    assert got.is_alarm


def test_a_non_dict_receipt_is_treated_as_no_receipt():
    assert rwc.classify_wake( "not a dict", fired_at=FIRED, now=_at( 200 ) ).verdict is rwc.WakeVerdict.DEAD_NO_WAKE


def test_identity_falls_back_to_the_receipt_then_to_the_caller():
    from_receipt = rwc.classify_wake( _receipt(), fired_at=FIRED, now=_at( 30 ) )
    assert ( from_receipt.session_id, from_receipt.persona ) == ( "9e0b977d", "maya" )

    from_caller = rwc.classify_wake( None, fired_at=FIRED, now=_at( 200 ),
                                     session_id="explicit", persona="cheech" )
    assert ( from_caller.session_id, from_caller.persona ) == ( "explicit", "cheech" )


# ── render_alert ─────────────────────────────────────────────────────────────

def test_render_alert_names_the_verdict_persona_and_memento():
    got  = rwc.classify_wake( _receipt( memento_slot=rwc.SLOT_MIRROR ), fired_at=FIRED, now=_at( 30 ) )
    line = rwc.render_alert( got, fired_at=FIRED )
    assert "STALE_SLOT" in line
    assert "maya" in line
    assert "/repo/.claude-memento-maya-9e0b977d.md" in line
    assert FIRED.isoformat() in line


def test_render_alert_survives_a_bare_assessment():
    line = rwc.render_alert( rwc.WakeAssessment( session_id=None, persona=None,
                                                 verdict=rwc.WakeVerdict.DEAD_NO_WAKE,
                                                 reason="gone", is_alarm=True ) )
    assert "unknown persona" in line and "unknown session" in line
    assert "Memento it opened" not in line


# ── check_respin_wake — the bounded poll ─────────────────────────────────────

def test_the_poll_settles_as_soon_as_the_receipt_appears():
    reads  = [ None, None, _receipt() ]
    clock  = iter( [ _at( 0 ), _at( 3 ), _at( 6 ) ] )
    slept  = []
    got = rwc.check_respin_wake(
        fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=lambda: reads.pop( 0 ), now_fn=lambda: next( clock ),
        sleep_fn=slept.append,
    )
    assert got.verdict is rwc.WakeVerdict.RETURNED
    assert slept == [ 3.0, 3.0 ]


def test_the_poll_gives_up_loudly_at_the_deadline():
    clock = iter( [ _at( 0 ), _at( 50 ), _at( 95 ) ] )
    got = rwc.check_respin_wake(
        fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=lambda: None, now_fn=lambda: next( clock ), sleep_fn=lambda s: None,
    )
    assert got.verdict is rwc.WakeVerdict.DEAD_NO_WAKE


def test_the_poll_never_sleeps_past_its_own_deadline():
    slept = []
    clock = iter( [ _at( 89 ), _at( 91 ) ] )
    rwc.check_respin_wake(
        fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=lambda: None, now_fn=lambda: next( clock ), sleep_fn=slept.append,
    )
    assert slept == [ 1.0 ]


def test_the_poll_reads_by_session_id_off_disk( tmp_path ):
    _drop( tmp_path, "s1" )
    got = rwc.check_respin_wake( fired_at=FIRED, session_id="s1", base_dir=str( tmp_path ),
                                 now_fn=lambda: _at( 30 ), sleep_fn=lambda s: None )
    assert got.verdict is rwc.WakeVerdict.RETURNED


def test_the_poll_reads_by_identity_when_no_session_id_is_known( tmp_path ):
    # The dismiss-then-spawn path: the successor mints its own id, so the tmux
    # session name is the only identity that survives the boundary.
    _drop( tmp_path, "brand-new", tmux_session="cc-maya-7" )
    got = rwc.check_respin_wake( fired_at=FIRED, tmux_session="cc-maya-7", base_dir=str( tmp_path ),
                                 now_fn=lambda: _at( 30 ), sleep_fn=lambda s: None )
    assert got.verdict is rwc.WakeVerdict.RETURNED


def test_the_poll_uses_its_real_clock_and_sleep_by_default( tmp_path, monkeypatch ):
    _drop( tmp_path, "s1", booted_at=datetime.datetime.now().astimezone().isoformat(),
           memento_written_at=datetime.datetime.now().astimezone().isoformat() )
    got = rwc.check_respin_wake( fired_at=datetime.datetime.now().astimezone() - datetime.timedelta( seconds=1 ),
                                 session_id="s1", base_dir=str( tmp_path ) )
    assert got.verdict is rwc.WakeVerdict.RETURNED


# ── verify_respin_wake — the SHOUT ───────────────────────────────────────────

def test_a_failure_shouts_exactly_once():
    shouts = []
    got = rwc.verify_respin_wake(
        alert_fn=shouts.append, fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=lambda: None, now_fn=lambda: _at( 200 ), sleep_fn=lambda s: None,
    )
    assert got.verdict is rwc.WakeVerdict.DEAD_NO_WAKE
    assert len( shouts ) == 1
    assert "RE-SPIN WAKE CHECK" in shouts[ 0 ]


def test_inverse_a_healthy_return_shouts_at_nobody():
    shouts = []
    got = rwc.verify_respin_wake(
        alert_fn=shouts.append, fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=_receipt, now_fn=lambda: _at( 30 ), sleep_fn=lambda s: None,
    )
    assert got.verdict is rwc.WakeVerdict.RETURNED
    assert shouts == []


def test_a_shout_that_raises_does_not_cost_the_caller_its_verdict():
    def _explode( _message ):
        raise RuntimeError( "the DM rail is down" )
    got = rwc.verify_respin_wake(
        alert_fn=_explode, fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=lambda: None, now_fn=lambda: _at( 200 ), sleep_fn=lambda s: None,
    )
    assert got.verdict is rwc.WakeVerdict.DEAD_NO_WAKE


# ── start_wake_watch ─────────────────────────────────────────────────────────

class _FakeThread:
    """Runs the body inline on start(), so the watch is provable without a race."""
    def __init__( self, target=None, daemon=None, name=None ):
        self.target, self.daemon, self.name, self.started = target, daemon, name, False

    def start( self ):
        self.started = True
        self.target()


def test_the_watch_runs_on_a_daemon_thread_and_shouts():
    shouts = []
    thread = rwc.start_wake_watch(
        alert_fn=shouts.append, fired_at=FIRED, thread_factory=_FakeThread,
        session_id="s1", base_dir="/unused",
        read_fn=lambda: None, now_fn=lambda: _at( 200 ), sleep_fn=lambda s: None,
    )
    assert thread.started and thread.daemon and thread.name == "RespinWakeCheck"
    assert len( shouts ) == 1


def test_an_exploding_watch_body_never_escapes_the_thread():
    def _boom():
        raise RuntimeError( "clock exploded" )
    thread = rwc.start_wake_watch( alert_fn=lambda m: None, fired_at=FIRED,
                                   thread_factory=_FakeThread, session_id="s1",
                                   base_dir="/unused", read_fn=lambda: None, now_fn=_boom )
    assert thread.started


def test_the_watch_uses_a_real_daemon_thread_by_default():
    shouts = []
    thread = rwc.start_wake_watch(
        alert_fn=shouts.append, fired_at=FIRED, session_id="s1", base_dir="/unused",
        read_fn=lambda: None, now_fn=lambda: _at( 200 ), sleep_fn=lambda s: None,
    )
    thread.join( timeout=5 )
    assert thread.daemon and shouts


# ── arm_watches_for_spawn ────────────────────────────────────────────────────

def test_one_watch_is_armed_per_seat_that_actually_launched():
    armed = []
    rwc.arm_watches_for_spawn(
        { "spawned": [ { "session_name": "cc-a", "status": "spawned" },
                       { "session_name": "cc-b", "status": "spawned" } ] },
        alert_fn=lambda m: None, fired_at=FIRED,
        start_fn=lambda **kw: armed.append( kw[ "tmux_session" ] ),
    )
    assert armed == [ "cc-a", "cc-b" ]


def test_a_failed_spawn_arms_no_watch():
    # It is already loud at the call site; a wake alarm on top would report the
    # same failure twice under a different name.
    armed = []
    rwc.arm_watches_for_spawn(
        { "spawned": [ { "session_name": "cc-a", "status": "failed" } ] },
        alert_fn=lambda m: None, fired_at=FIRED,
        start_fn=lambda **kw: armed.append( kw[ "tmux_session" ] ),
    )
    assert armed == []


@pytest.mark.parametrize( "payload", [
    None,
    "not a dict",
    {},
    { "spawned": None },
    { "spawned": [ "not a dict" ] },
    { "spawned": [ { "status": "spawned" } ] },          # no session_name
] )
def test_a_malformed_spawn_result_arms_nothing_rather_than_raising( payload ):
    armed = []
    assert rwc.arm_watches_for_spawn( payload, alert_fn=lambda m: None, fired_at=FIRED,
                                      start_fn=lambda **kw: armed.append( kw ) ) == []
    assert armed == []


def test_arm_watches_defaults_to_the_real_starter():
    result = rwc.arm_watches_for_spawn(
        { "spawned": [ { "session_name": "cc-a", "status": "spawned" } ] },
        alert_fn=lambda m: None, fired_at=FIRED,
        base_dir="/unused", read_fn=lambda: _receipt(), now_fn=lambda: _at( 30 ),
        sleep_fn=lambda s: None,
    )
    assert len( result ) == 1
    result[ 0 ].join( timeout=5 )


# ── the inline smoke block ───────────────────────────────────────────────────

def test_quick_smoke_test_runs_green( capsys ):
    rwc.quick_smoke_test()
    out = capsys.readouterr().out
    assert "4/4" in out
    assert "✗" not in out


def test_the_poll_stops_rather_than_spinning_if_pending_survives_the_deadline( monkeypatch ):
    # classify_wake cannot return PENDING past the deadline today, so this guard
    # is proven by forcing the condition it exists for: a clock that steps
    # backward between the two reads. Without it the watch would never exit and
    # the thread would leak.
    monkeypatch.setattr( rwc, "classify_wake",
                         lambda *a, **kw: rwc.WakeAssessment( session_id=None, persona=None,
                                                              verdict=rwc.WakeVerdict.PENDING,
                                                              reason="forced", is_alarm=False ) )
    slept = []
    got = rwc.check_respin_wake( fired_at=FIRED, session_id="s1", base_dir="/unused",
                                 read_fn=lambda: None, now_fn=lambda: _at( 500 ),
                                 sleep_fn=slept.append )
    assert got.verdict is rwc.WakeVerdict.PENDING
    assert slept == []


# ── persona_slugs — the comparison key (row c3670edc) ─────────────────────────

@pytest.mark.parametrize( "value", [ None, 42, "", "   ", "🕊️", "—" ] )
def test_persona_slugs_is_empty_for_an_unknowable_name( value ):
    """An identity that cannot be read must never be reported as a WRONG one."""
    assert rwc.persona_slugs( value ) == frozenset()


def test_persona_slugs_strips_case_space_and_emoji():
    assert rwc.persona_slugs( "  Rachel 🕊️  " ) == frozenset( { "rachel" } )


def test_persona_slugs_yields_BOTH_spellings_of_an_accented_name():
    """The two writers in this fleet disagree, so both forms have to be offered."""
    assert rwc.persona_slugs( "María" ) == frozenset( { "maria", "mar-a" } )


@pytest.mark.parametrize( "seat,record", [ ( "María", "maria" ), ( "María", "mar-a" ),
                                           ( "Cheech 🌿", "cheech" ) ] )
def test_persona_slugs_never_calls_one_real_seat_two_people( seat, record ):
    """The false-alarm control: a live roster persona must never read as an impostor."""
    assert not rwc.persona_slugs( seat ).isdisjoint( rwc.persona_slugs( record ) )


def test_persona_slugs_does_separate_two_actually_different_people():
    assert rwc.persona_slugs( "rachel" ).isdisjoint( rwc.persona_slugs( "clayton" ) )


# ── WRONG_PERSONA — the question the first cut did not ask (row c3670edc) ─────

def test_the_clayton_case_alarms_instead_of_greening():
    """THE ROW'S OWN SCENARIO. A successor seeded from the repo-wide root pointer
    reads a record that is live, in a live slot, and freshly written — and belongs
    to somebody else. Under the first cut this walked every rung and came out
    RETURNED."""
    receipt = _receipt( persona="cheech", memento_persona="clayton",
                        memento_path="/repo/.claude-memento-clayton-8002a94e.md" )
    out = rwc.classify_wake( receipt, fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict  is rwc.WakeVerdict.WRONG_PERSONA
    assert out.is_alarm is True
    assert out.memento_path == "/repo/.claude-memento-clayton-8002a94e.md"
    assert "cheech"  in out.reason
    assert "clayton" in out.reason


def test_inverse_a_record_that_IS_yours_stays_quiet():
    out = rwc.classify_wake( _receipt(), fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict  is rwc.WakeVerdict.RETURNED
    assert out.is_alarm is False


def test_inverse_a_differently_spelled_but_same_seat_stays_quiet():
    """María's own record, stamped by the writer that does not fold accents."""
    out = rwc.classify_wake( _receipt( persona="María", memento_persona="mar-a" ),
                             fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict is rwc.WakeVerdict.RETURNED


def test_a_record_that_does_not_say_whose_it_is_cannot_alarm():
    """Unprovable is not an alarm — the same rule the undated-record case follows."""
    out = rwc.classify_wake( _receipt( memento_persona=None ), fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict is rwc.WakeVerdict.RETURNED


def test_a_seat_with_no_allocated_persona_cannot_alarm():
    out = rwc.classify_wake( _receipt( persona=None, memento_persona="clayton" ),
                             fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict is rwc.WakeVerdict.RETURNED


def test_an_emoji_only_persona_on_either_side_cannot_alarm():
    """Reduces to no slug at all, so nothing can be proven about it."""
    assert rwc.classify_wake( _receipt( persona="🕊️", memento_persona="clayton" ),
                              fired_at=FIRED, now=_at( 10 ) ).verdict is rwc.WakeVerdict.RETURNED
    assert rwc.classify_wake( _receipt( persona="rachel", memento_persona="🕊️" ),
                              fired_at=FIRED, now=_at( 10 ) ).verdict is rwc.WakeVerdict.RETURNED


def test_wrong_persona_is_asked_BEFORE_the_slot_question():
    """A mirror copy of somebody else's record is both wrong things at once; the
    identity finding is the one the manager needs first."""
    out = rwc.classify_wake( _receipt( persona="cheech", memento_persona="clayton",
                                       memento_slot=rwc.SLOT_MIRROR ),
                             fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict is rwc.WakeVerdict.WRONG_PERSONA


def test_wrong_persona_is_asked_BEFORE_the_age_question():
    out = rwc.classify_wake( _receipt( persona="cheech", memento_persona="clayton",
                                       memento_written_at=_at( -99999 ).isoformat() ),
                             fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict is rwc.WakeVerdict.WRONG_PERSONA


def test_seed_not_consumed_still_wins_when_there_is_no_path_at_all():
    """No file was read, so there is no record to be somebody else's."""
    out = rwc.classify_wake( _receipt( memento_path=None, memento_persona="clayton" ),
                             fired_at=FIRED, now=_at( 10 ) )
    assert out.verdict is rwc.WakeVerdict.SEED_NOT_CONSUMED


def test_the_alarm_line_names_the_file_the_seat_actually_opened():
    out  = rwc.classify_wake( _receipt( persona="cheech", memento_persona="clayton",
                                        memento_path="/repo/.claude-memento-clayton-8002a94e.md" ),
                              fired_at=FIRED, now=_at( 10 ) )
    line = rwc.render_alert( out, fired_at=FIRED )
    assert "WRONG_PERSONA" in line
    assert "/repo/.claude-memento-clayton-8002a94e.md" in line


# ── the receipt carries the record's own claim ────────────────────────────────

def test_build_receipt_dict_records_the_mementos_declared_persona():
    body = rwc.build_receipt_dict(
        session_id="s1", persona="cheech", tmux_session="t", memento_path="/repo/m.md",
        memento_written_at=None, repo_root="/repo", booted_at=_at( 1 ),
        memento_persona="clayton",
    )
    assert body[ "persona" ]         == "cheech"
    assert body[ "memento_persona" ] == "clayton"


def test_build_receipt_dict_leaves_the_declared_persona_none_when_unstated():
    body = rwc.build_receipt_dict(
        session_id="s1", persona="cheech", tmux_session="t", memento_path=None,
        memento_written_at=None, repo_root="/repo", booted_at=_at( 1 ),
    )
    assert body[ "memento_persona" ] is None


def test_write_boot_receipt_round_trips_the_declared_persona( tmp_path ):
    rwc.write_boot_receipt( session_id="s1", persona="cheech", memento_path="/repo/m.md",
                            memento_persona="clayton", base_dir=str( tmp_path ) )
    assert rwc.read_receipt( str( tmp_path ), "s1" )[ "memento_persona" ] == "clayton"
