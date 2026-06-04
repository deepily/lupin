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
        "outcome"        : "poke",
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
    assert e.read_events( "s10", base_dir=nested )[ 0 ][ "outcome" ] == "poke"


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
        '{"outcome": "poke"}\n'
        "\n"                       # blank → skipped
        "{not json\n"              # malformed → skipped
        "[1, 2, 3]\n"              # non-object → skipped
        '{"outcome": "honored"}\n'
    )
    recs = e.read_events( "s13", base_dir=tmp_path )
    assert [ r[ "outcome" ] for r in recs ] == [ "poke", "honored" ]


def test_read_events_oserror_returns_empty( tmp_path ):
    ( tmp_path / "s14.jsonl" ).mkdir()   # path is a dir → open raises → []
    assert e.read_events( "s14", base_dir=tmp_path ) == [ ]


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert e.quick_smoke_test() is True
