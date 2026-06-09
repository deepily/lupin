#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Hook poke-outcome event emitter.

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_events.py

All tests inject base_dir (tmp_path) so they NEVER touch the real fleet dir
(~/.claude/heartbeat-events). Canonical schema: design §0.2 (María).
"""
import json

from lupin_cli.claude_code.hooks.lib import heartbeat_events as e
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED, OUTCOME_NOT_OWED,
)


# ── events_path / _resolve_base_dir ───────────────────────────────────────────

def test_events_path_with_base_dir( tmp_path ):
    assert e.events_path( "abc123", base_dir=tmp_path ) == tmp_path / "abc123.jsonl"


def test_events_path_empty_session_collapses_to_unknown( tmp_path ):
    assert e.events_path( "", base_dir=tmp_path ) == tmp_path / "unknown.jsonl"


def test_events_path_default_is_fleet_dir():
    # None base_dir → the fleet dir (NOT project root)
    assert e.events_path( "abc123" ) == e.FLEET_EVENTS_DIR / "abc123.jsonl"


# ── emit_outcome — emitted outcomes ───────────────────────────────────────────

def test_emit_poke_writes_record_with_reason( tmp_path ):
    ok = e.emit_outcome( "s1", "Tiffany 💍", OUTCOME_POKE, 1, 3,
                         work_owed=None, awaiting="peer:Rachel",
                         reason="resume or declare a hold", ts="2026-06-04T20:00:00+00:00",
                         base_dir=tmp_path )
    assert ok is True
    recs = e.read_events( "s1", base_dir=tmp_path )
    assert len( recs ) == 1
    r = recs[ 0 ]
    assert r == {
        "schema_version" : 1,
        "session_id"     : "s1",
        "persona"        : "Tiffany 💍",
        "ts"             : "2026-06-04T20:00:00+00:00",
        "outcome"        : "poked",
        "poke_count"     : 1,
        "cap"            : 3,
        "work_owed"      : None,
        "awaiting"       : "peer:Rachel",
        "reason"         : "resume or declare a hold",
    }


def test_emit_honored_omits_reason_even_if_passed( tmp_path ):
    e.emit_outcome( "s2", "María 🌸", OUTCOME_HONORED, 0, 3,
                    reason="should be ignored", base_dir=tmp_path )
    r = e.read_events( "s2", base_dir=tmp_path )[ 0 ]
    assert r[ "outcome" ] == "honored"
    assert "reason" not in r


def test_emit_cap_reached_writes( tmp_path ):
    assert e.emit_outcome( "s3", "P", OUTCOME_CAP_REACHED, 3, 3, base_dir=tmp_path ) is True
    assert e.read_events( "s3", base_dir=tmp_path )[ 0 ][ "outcome" ] == "cap_reached"


def test_emit_poke_with_none_reason_omits_key( tmp_path ):
    e.emit_outcome( "s4", "P", OUTCOME_POKE, 1, 3, reason=None, base_dir=tmp_path )
    assert "reason" not in e.read_events( "s4", base_dir=tmp_path )[ 0 ]


def test_emit_default_ts_is_iso_utc( tmp_path ):
    e.emit_outcome( "s5", "P", OUTCOME_POKE, 1, 3, base_dir=tmp_path )
    ts = e.read_events( "s5", base_dir=tmp_path )[ 0 ][ "ts" ]
    assert ts.endswith( "+00:00" ) and "T" in ts


def test_emit_work_owed_explicit_bool_recorded( tmp_path ):
    e.emit_outcome( "s6", "P", OUTCOME_POKE, 1, 3, work_owed=True, base_dir=tmp_path )
    assert e.read_events( "s6", base_dir=tmp_path )[ 0 ][ "work_owed" ] is True


def test_emit_awaiting_defaults_null( tmp_path ):
    e.emit_outcome( "s7", "P", OUTCOME_HONORED, 0, 3, base_dir=tmp_path )
    assert e.read_events( "s7", base_dir=tmp_path )[ 0 ][ "awaiting" ] is None


# ── emit_outcome — skipped outcomes ───────────────────────────────────────────

def test_emit_not_owed_skipped( tmp_path ):
    assert e.emit_outcome( "s8", "P", OUTCOME_NOT_OWED, 0, 3, base_dir=tmp_path ) is False
    assert e.read_events( "s8", base_dir=tmp_path ) == [ ]


def test_emit_unknown_outcome_skipped( tmp_path ):
    assert e.emit_outcome( "s9", "P", "bogus_outcome", 0, 3, base_dir=tmp_path ) is False
    assert e.read_events( "s9", base_dir=tmp_path ) == [ ]


# ── emit_outcome — robustness (never raises) ──────────────────────────────────

def test_emit_creates_missing_fleet_dir( tmp_path ):
    nested = tmp_path / "does" / "not" / "exist"
    assert e.emit_outcome( "s10", "P", OUTCOME_POKE, 1, 3, base_dir=nested ) is True
    assert e.read_events( "s10", base_dir=nested )[ 0 ][ "outcome" ] == "poked"


def test_emit_oserror_returns_false( tmp_path ):
    # Make the target path a directory → open(..,"a") raises OSError → False
    ( tmp_path / "s11.jsonl" ).mkdir()
    assert e.emit_outcome( "s11", "P", OUTCOME_POKE, 1, 3, base_dir=tmp_path ) is False


def test_emit_serialization_error_returns_false( tmp_path ):
    # Non-JSON-serializable persona → json.dumps raises TypeError → caught → False
    assert e.emit_outcome( "s12", { 1, 2 }, OUTCOME_POKE, 1, 3, base_dir=tmp_path ) is False


# ── read_events ───────────────────────────────────────────────────────────────

def test_read_events_missing_file( tmp_path ):
    assert e.read_events( "nope", base_dir=tmp_path ) == [ ]


def test_read_events_skips_blank_and_malformed_and_non_object( tmp_path ):
    path = tmp_path / "s13.jsonl"
    path.write_text(
        '{"outcome": "poked"}\n'
        "\n"                       # blank → skipped
        "{not json\n"              # malformed → skipped
        "[1, 2, 3]\n"              # non-object → skipped
        '{"outcome": "honored"}\n'
    )
    recs = e.read_events( "s13", base_dir=tmp_path )
    assert [ r[ "outcome" ] for r in recs ] == [ "poked", "honored" ]


def test_read_events_oserror_returns_empty( tmp_path ):
    ( tmp_path / "s14.jsonl" ).mkdir()   # path is a dir → open raises → []
    assert e.read_events( "s14", base_dir=tmp_path ) == [ ]


# ── v2 idle beacon + edge-trigger helpers ─────────────────────────────────────

def test_emit_idle_writes_record( tmp_path ):
    ok = e.emit_outcome( "i1", "Tiffany 💍", e.EVENT_IDLE, 0, 3, work_owed=False, base_dir=tmp_path )
    assert ok is True
    r = e.read_events( "i1", base_dir=tmp_path )[ 0 ]
    assert r[ "outcome" ]   == "idle"
    assert r[ "work_owed" ] is False
    assert "reason" not in r


def test_should_emit_idle_pure():
    assert e.should_emit_idle( None )         is True   # first idle = transition from nothing
    assert e.should_emit_idle( "poked" )       is True
    assert e.should_emit_idle( "honored" )    is True
    assert e.should_emit_idle( e.EVENT_IDLE ) is False  # already idle → de-dup


def test_last_emitted_outcome_no_events( tmp_path ):
    assert e.last_emitted_outcome( "none", base_dir=tmp_path ) is None


def test_last_emitted_outcome_returns_last( tmp_path ):
    e.emit_outcome( "i2", "P", OUTCOME_POKE, 1, 3, base_dir=tmp_path )
    e.emit_outcome( "i2", "P", OUTCOME_CAP_REACHED, 3, 3, base_dir=tmp_path )
    assert e.last_emitted_outcome( "i2", base_dir=tmp_path ) == "cap_reached"


def test_last_emitted_outcome_missing_field_is_none( tmp_path ):
    ( tmp_path / "i3.jsonl" ).write_text( '{"no_outcome_field": 1}\n' )
    assert e.last_emitted_outcome( "i3", base_dir=tmp_path ) is None


def test_is_idle_transition_first_idle_is_transition( tmp_path ):
    assert e.is_idle_transition( "i4", base_dir=tmp_path ) is True   # no prior events


def test_is_idle_transition_after_active_outcome( tmp_path ):
    e.emit_outcome( "i5", "P", OUTCOME_POKE, 1, 3, base_dir=tmp_path )
    assert e.is_idle_transition( "i5", base_dir=tmp_path ) is True


def test_is_idle_transition_dedup_after_idle( tmp_path ):
    e.emit_outcome( "i6", "P", e.EVENT_IDLE, 0, 3, work_owed=False, base_dir=tmp_path )
    assert e.is_idle_transition( "i6", base_dir=tmp_path ) is False


# ── emit_idle_prompt — kind-tagged 4th-signal recency event (Step 1.3) ────────

def test_emit_idle_prompt_writes_kind_tagged_record( tmp_path ):
    ok = e.emit_idle_prompt( "ip1", persona="Tiffany 💍", base_dir=tmp_path )
    assert ok is True
    r = e.read_events( "ip1", base_dir=tmp_path )[ 0 ]
    assert r[ "kind" ]    == e.EVENT_KIND_IDLE_PROMPT == "idle_prompt"
    assert r[ "persona" ] == "Tiffany 💍"
    assert r[ "session_id" ] == "ip1"
    assert r[ "schema_version" ] == e.SCHEMA_VERSION
    # NO `outcome` key → can never map through _STATE_BY_OUTCOME
    assert "outcome" not in r


def test_emit_idle_prompt_persona_defaults_none( tmp_path ):
    e.emit_idle_prompt( "ip2", base_dir=tmp_path )
    assert e.read_events( "ip2", base_dir=tmp_path )[ 0 ][ "persona" ] is None


def test_emit_idle_prompt_default_ts_is_iso_utc( tmp_path ):
    e.emit_idle_prompt( "ip3", base_dir=tmp_path )
    ts = e.read_events( "ip3", base_dir=tmp_path )[ 0 ][ "ts" ]
    assert ts.endswith( "+00:00" ) and "T" in ts


def test_emit_idle_prompt_explicit_ts_honored( tmp_path ):
    e.emit_idle_prompt( "ip4", ts="2026-06-08T12:00:00+00:00", base_dir=tmp_path )
    assert e.read_events( "ip4", base_dir=tmp_path )[ 0 ][ "ts" ] == "2026-06-08T12:00:00+00:00"


def test_emit_idle_prompt_creates_missing_fleet_dir( tmp_path ):
    nested = tmp_path / "no" / "dir" / "yet"
    assert e.emit_idle_prompt( "ip5", base_dir=nested ) is True
    assert e.read_events( "ip5", base_dir=nested )[ 0 ][ "kind" ] == "idle_prompt"


def test_emit_idle_prompt_oserror_returns_false( tmp_path ):
    ( tmp_path / "ip6.jsonl" ).mkdir()   # path is a dir → open(..,"a") raises → False
    assert e.emit_idle_prompt( "ip6", base_dir=tmp_path ) is False


def test_emit_idle_prompt_serialization_error_returns_false( tmp_path ):
    # Non-JSON-serializable persona → json.dumps raises TypeError → caught → False
    assert e.emit_idle_prompt( "ip7", persona={ 1, 2 }, base_dir=tmp_path ) is False


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert e.quick_smoke_test() is True
