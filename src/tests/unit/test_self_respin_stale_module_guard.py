"""
Unit tests for the STALE-MCP-MODULE guard on self_respin (row b5035039).

THE DEFECT THESE TESTS SEE. Measured 2026-09-11 on two seats independently: a
seat whose cosa_voice_mcp.py process started BEFORE the idle-gate merge went on
running the pre-merge module for hours. `self_respin` returned "scheduled", the
clear fired ungated into a mid-turn pane, and nothing in the returned payload
told the seat its own gate was absent. The discriminator was the marker: current
code writes `idle_wait_max_seconds` unconditionally, and the stale seat's marker
had no such key.

WHY A MODULE CANNOT DETECT ITS OWN STALENESS BY INTROSPECTION. A stale process
runs stale core code, which has no check in it. The only signature a process can
actually read is DISK-AHEAD-OF-MEMORY: the source file on disk declares a marker
schema NEWER than the one this process imported. That is what
`stale_module_warning` compares, and it is why the guard is worth having even
though it could not have fired on the seat that motivated it — it fires on the
NEXT drift.

WARN, NEVER REFUSE. A refusal inside stale code would strand a seat that
genuinely needs to re-spin while the operator is away. Every assertion here
insists the verb still returns "scheduled".

Target: 100% lines + branches + functions on the code added for this row.
"""

import datetime
import json

import pytest

import cosa.agents.heartbeat_arbiter.self_respin_observer as obs
import lupin_mcp.self_respin_core as sr
from lupin_mcp.persona_normalization import persona_slug


UTC = datetime.timezone.utc


def _dt( minute, second=0 ):
    return datetime.datetime( 2026, 8, 14, 2, minute, second, tzinfo=UTC )


_REAL_BODY = ( "board state: row b5035039 in progress, manager maria, "
               "venue :8000 idle, next act is the stale-module guard.\n" ) * 5

_SEAT_PERSONA = "cheech"
_SEAT_SID     = "sid1"


def _seat( tmux="cheech-mgr" ):
    return lambda sid: tmux


def _write_memento( tmp_path, uuid, ts, *, persona=_SEAT_PERSONA, sid=_SEAT_SID ):
    """Write a real root-slot record+pointer pair under tmp_path; return the pointer path."""
    stamp  = ts.isoformat()
    slug   = persona_slug( persona )
    record = tmp_path / f".claude-memento-{slug}-{sid[ :8 ].lower()}.md"
    header = f"<!-- memento-record: persona={slug} session_id={sid[ :8 ].lower()} written_at={stamp} slot=root -->\n"
    body   = header + "# memento\n" + _REAL_BODY * 4
    record.write_text( body )

    pointer = tmp_path / f".claude-memento-{slug}.md"
    pointer.write_text(
        "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->\n"
        f"<!-- current: {record.name} -->\n"
        + body + "\n" + sr.build_nonce_line( uuid, ts ) + "\n"
    )
    return str( pointer )


def _perform( tmp_path, **overrides ):
    """Run the verb on the happy path; `overrides` replace any kwarg."""
    mp   = _write_memento( tmp_path, "u1", _dt( 20 ) )
    kw   = dict(
        persona          = _SEAT_PERSONA,
        memento_path     = mp,
        memento_nonce    = "u1",
        pre_clear_status = "over_budget",
        pre_clear_pct    = 61.0,
        now              = _dt( 21 ),
        resolve_tmux_fn  = _seat(),
        ask_fn           = lambda: "yes",
        schedule_fn      = lambda argv: None,
        base_dir         = str( tmp_path ),
        repo_root        = str( tmp_path ),
    )
    kw.update( overrides )
    return sr.perform_self_respin( _SEAT_SID, **kw )


# ---------------------------------------------------------------------------
# FIX 1a — the marker carries its own code/schema version
# ---------------------------------------------------------------------------
def test_build_marker_dict_stamps_the_schema_version():
    """A marker with no version cannot be told from a marker written by code that
    predates versioning — which is the whole ambiguity this row is about."""
    m = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=_dt( 20 ), delay_seconds=20, grace_seconds=100,
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        memento_path="/m", memento_verified=True,
    )
    assert m[ obs.MARKER_SCHEMA_VERSION_KEY ] == obs.MARKER_SCHEMA_VERSION
    assert isinstance( obs.MARKER_SCHEMA_VERSION, int )


def test_the_verb_writes_the_schema_version_to_disk( tmp_path ):
    r = _perform( tmp_path )
    assert r.status == "scheduled"
    written = json.loads( ( tmp_path / ".self-respin-sid1.json" ).read_text() )
    assert written[ obs.MARKER_SCHEMA_VERSION_KEY ] == obs.MARKER_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# FIX 1b — parsing the version out of the source ON DISK
# ---------------------------------------------------------------------------
def test_parse_marker_schema_version_reads_the_assignment():
    assert sr.parse_marker_schema_version( "MARKER_SCHEMA_VERSION = 7\n" ) == 7


def test_parse_marker_schema_version_ignores_the_key_constant_beside_it():
    """`MARKER_SCHEMA_VERSION_KEY` starts with the same characters. A pattern that
    matched it would parse a string constant as the version and read nothing at all.

    FAITHFUL BUT NOT DISCRIMINATING — see the next test for why this one alone is not
    enough. Kept because it is the real module's actual shape."""
    source = 'MARKER_SCHEMA_VERSION_KEY = "marker_schema_version"\nMARKER_SCHEMA_VERSION = 3\n'
    assert sr.parse_marker_schema_version( source ) == 3


def test_parse_marker_schema_version_is_not_fooled_by_a_DIGIT_BEARING_sibling():
    """THE NEGATIVE CONTROL for the sibling rule (Sam, review of 143bb57f).

    The faithful fixture above CANNOT FAIL. Its sibling's value holds no digit, so a
    pattern lax about what sits between the constant name and the `=` finds no number on
    the sibling line and falls through to the right line anyway — lax and strict return
    the same 3, and the test goes green over a regex that reads the wrong constant. It
    asserts a guard it cannot verify.

    This fixture makes the two patterns disagree: the sibling carries a NUMBER, so a lax
    pattern reads 99 and only a pattern that stops at the exact constant name reads 3.
    Order matters — the sibling is FIRST, because re.search takes the earliest match.

    The real MARKER_SCHEMA_VERSION_KEY holds a plain string, so this sibling is synthetic
    on purpose: a faithful miniature cannot discriminate here, and that IS the finding.
    Verified by mutation, not by argument — swapping the real pattern for a lax
    `MARKER_SCHEMA_VERSION\\w*[ \\t]*=[ \\t]*(\\d+)` turns THIS test red and leaves the
    faithful one above green."""
    source = 'MARKER_SCHEMA_VERSION_KEY = 99\nMARKER_SCHEMA_VERSION = 3\n'
    assert sr.parse_marker_schema_version( source ) == 3


def test_parse_marker_schema_version_ignores_an_indented_lookalike():
    """Only a MODULE-LEVEL assignment is the module's version; a local rebinding
    inside some function is not, and MULTILINE anchoring is what tells them apart."""
    assert sr.parse_marker_schema_version( "    MARKER_SCHEMA_VERSION = 9\n" ) is None


@pytest.mark.parametrize( "source", [ None, "", "nothing here\n" ] )
def test_parse_marker_schema_version_returns_none_without_an_assignment( source ):
    assert sr.parse_marker_schema_version( source ) is None


def test_the_live_observer_source_carries_a_parseable_version():
    """The reader and the file must actually agree — a guard whose parse silently
    misses the real file is a guard that never fires."""
    assert sr.parse_marker_schema_version( sr._default_observer_source() ) == obs.MARKER_SCHEMA_VERSION


def test_loaded_marker_schema_version_matches_the_imported_module():
    assert sr.loaded_marker_schema_version() == obs.MARKER_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# FIX 1c — the warning itself: loud, remedial, and never a refusal
# ---------------------------------------------------------------------------
def test_stale_module_warning_fires_when_disk_is_ahead_of_memory():
    w = sr.stale_module_warning( 1, "MARKER_SCHEMA_VERSION = 2\n" )
    assert w is not None
    assert sr.STALE_MODULE_BANNER in w
    assert "RESTART" in w
    assert "/clear does NOT reload it" in w            # the exact confusion that caused this row
    assert "v1" in w and "v2" in w                     # names both coordinates, not just "stale"


def test_stale_module_warning_fires_when_the_loaded_module_predates_versioning():
    """A module so old it has no version constant reads as 0, so ANY versioned disk
    is ahead of it — which is precisely the measured seat's situation."""
    assert sr.stale_module_warning( 0, "MARKER_SCHEMA_VERSION = 1\n" ) is not None


def test_stale_module_warning_silent_when_versions_match():
    assert sr.stale_module_warning( 2, "MARKER_SCHEMA_VERSION = 2\n" ) is None


def test_stale_module_warning_silent_when_memory_is_ahead_of_disk():
    """A worktree checked out to an older file must not accuse a current process."""
    assert sr.stale_module_warning( 3, "MARKER_SCHEMA_VERSION = 2\n" ) is None


def test_stale_module_warning_silent_when_disk_is_unreadable():
    """An unreadable source is an unknown, not an accusation — the guard's failure
    direction is silence, never a false alarm on the go-path."""
    assert sr.stale_module_warning( 1, None ) is None


def test_the_live_guard_is_silent_in_a_current_process():
    """Running tests ARE a current process, so the guard must say nothing here."""
    assert sr.stale_module_warning( sr.loaded_marker_schema_version(),
                                    sr._default_observer_source() ) is None


def test_the_verb_warns_but_still_schedules_when_the_module_is_stale( tmp_path ):
    """THE CENTRAL ASSERTION OF THIS ROW. The warning must reach the caller's payload,
    and the re-spin must still happen — a refusal here would strand the seat."""
    scheduled = []
    r = _perform(
        tmp_path,
        schedule_fn        = lambda argv: scheduled.append( argv ),
        observer_source_fn = lambda: f"MARKER_SCHEMA_VERSION = {obs.MARKER_SCHEMA_VERSION + 1}\n",
    )
    assert r.status == "scheduled"                        # WARN, NOT REFUSE
    assert len( scheduled ) == 1                          # the clear really was scheduled
    assert any( sr.STALE_MODULE_BANNER in w for w in r.warnings )
    assert sr.STALE_MODULE_BANNER in r.reason             # loud in the text too, not only the list
    assert r.reason.startswith( sr.STALE_MODULE_BANNER )  # FIRST thing a text-only reader sees


def test_the_verb_carries_no_warnings_on_a_current_process( tmp_path ):
    r = _perform( tmp_path )
    assert r.status   == "scheduled"
    assert r.warnings == []
    assert sr.STALE_MODULE_BANNER not in r.reason


# ---------------------------------------------------------------------------
# FIX 2 — the success text says what an ABSENT FIRE TOKEN means
# ---------------------------------------------------------------------------
def test_success_reason_explains_that_an_absent_fire_token_means_it_fired( tmp_path ):
    """The fire point rm's the token BEFORE typing, so 'token gone' is the SUCCESS
    signature. The measured seat read it as 'never scheduled' and nearly re-fired
    a second /clear onto its own rehydrated successor."""
    reason = _perform( tmp_path ).reason.lower()
    assert "fire token" in reason
    assert "fired"      in reason
    assert "re-fire"    in reason


# ---------------------------------------------------------------------------
# FIX 3 — the generic catch: re-read the marker and assert the fields
# ---------------------------------------------------------------------------
def test_required_fields_are_exactly_what_the_builder_writes():
    """The checker's list and the writer's literal must not drift apart, or the
    generic catch quietly stops checking whatever was added last."""
    m = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=_dt( 20 ), delay_seconds=20,
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        memento_path="/m", memento_verified=True,
    )
    assert set( obs.MARKER_REQUIRED_FIELDS ) == set( m )


def test_missing_marker_fields_empty_for_a_complete_marker():
    m = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=_dt( 20 ), delay_seconds=20,
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        memento_path="/m", memento_verified=True,
    )
    assert obs.missing_marker_fields( m ) == ()


def test_missing_marker_fields_keys_on_PRESENCE_not_truthiness():
    """`wake_nonce` and `pre_clear_pct` are legitimately None on real markers. A
    truthiness check would report every no-wake re-spin as malformed."""
    m = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=_dt( 20 ), delay_seconds=20,
        pre_clear_status="over_budget", pre_clear_pct=None,
        memento_path="/m", memento_verified=False, wake_nonce=None,
    )
    assert obs.missing_marker_fields( m ) == ()


def test_missing_marker_fields_names_what_is_absent():
    assert obs.missing_marker_fields( { "session_id": "s1" } ) == tuple(
        f for f in obs.MARKER_REQUIRED_FIELDS if f != "session_id" )


@pytest.mark.parametrize( "not_a_marker", [ None, [ "session_id" ], "session_id" ] )
def test_missing_marker_fields_treats_a_non_dict_as_wholly_missing( not_a_marker ):
    assert obs.missing_marker_fields( not_a_marker ) == tuple( obs.MARKER_REQUIRED_FIELDS )


def test_marker_field_warning_is_none_when_nothing_is_missing():
    assert sr.marker_field_warning( () ) is None


def test_marker_field_warning_names_the_fields_and_the_remedy():
    w = sr.marker_field_warning( ( "idle_wait_max_seconds", "wake_nonce" ) )
    assert w is not None
    assert "idle_wait_max_seconds" in w and "wake_nonce" in w
    assert "RESTART" in w
    assert sr.MARKER_WRITE_BANNER in w                   # write integrity, not staleness
    assert sr.STALE_MODULE_BANNER not in w


def test_the_field_check_is_BLIND_to_a_stale_writer_that_writes_completely():
    """Sam's finding, pinned as a test (review of e304b3e7). fix 3 was described as
    catching a stale writer. It cannot, and this is the proof: a stale writer emits a
    COMPLETE marker under its OWN older schema — here, every contracted field present
    but stamped with an older marker_schema_version — and the field check is silent.
    Only stale_module_warning sees that process. If someone re-words the field check as
    a staleness guard, this test is what contradicts them."""
    stale_writers_marker = obs.build_marker_dict(
        session_id="s1", persona="p1", tmux_session="t1",
        fired_at=_dt( 20 ), delay_seconds=20,
        pre_clear_status="over_budget", pre_clear_pct=51.0,
        memento_path="/m", memento_verified=True, wake_nonce="n1",
    )
    stale_writers_marker[ obs.MARKER_SCHEMA_VERSION_KEY ] = obs.MARKER_SCHEMA_VERSION - 1

    assert obs.missing_marker_fields( stale_writers_marker ) == ()
    assert sr.marker_field_warning(
        obs.missing_marker_fields( stale_writers_marker ) ) is None


def test_the_verb_warns_when_its_own_marker_reads_back_incomplete( tmp_path ):
    """THE WRITE-INTEGRITY CATCH. A marker that reached disk incomplete — a partial or
    truncated write, or a field the writer never populated — is caught here on ANY
    contracted field, not only the one that happened to expose the measured seat. The
    marker still names this session, so the durability read-back passes and only this
    check objects.

    This does NOT detect a stale writer, and the assertions below say so: the warning
    carries the write banner and NOT the staleness banner. A stale writer emits a
    complete marker under its own older schema, so this check would see nothing wrong
    with it — only stale_module_warning can see that."""
    def _lossy_write( path, data ):
        stripped = { k: v for k, v in data.items() if k != obs.IDLE_WAIT_MAX_SECONDS }
        with open( path, "w" ) as fh:
            json.dump( stripped, fh )

    r = _perform( tmp_path, write_json_fn=_lossy_write )
    assert r.status == "scheduled"                                    # warn, not refuse
    assert any( obs.IDLE_WAIT_MAX_SECONDS in w for w in r.warnings )
    assert any( sr.MARKER_WRITE_BANNER in w for w in r.warnings )     # write integrity…
    assert not any( sr.STALE_MODULE_BANNER in w for w in r.warnings ) # …NOT staleness


def test_an_unreadable_marker_still_aborts_rather_than_merely_warning( tmp_path ):
    """The pre-existing durability gate is NOT softened into a warning: a marker that
    does not survive at all is a genuine failure to record, and still aborts."""
    r = _perform( tmp_path, write_json_fn=lambda path, data: None )
    assert r.status == "aborted"
    assert "did not survive read-back" in r.reason


def test_read_marker_json_rejects_a_json_scalar( tmp_path ):
    """`json.loads("3")` succeeds and has no `.get` — a shape the parser must reject
    as 'not a marker' rather than raise inside the verb."""
    p = tmp_path / "m.json"
    p.write_text( "3" )
    assert sr._read_marker_json( sr._default_read_text, str( p ) ) is None
