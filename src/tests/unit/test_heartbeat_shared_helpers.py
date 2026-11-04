"""
Unit tests for the helpers that replaced copied bodies in the heartbeat hook lib.

They are heartbeat_events._append_record and _emit_kind, and heartbeat_work_owed._debounced_need.
"""

import inspect
import json

import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_events as e
from lupin_cli.claude_code.hooks.lib import heartbeat_work_owed as o

NOW = 1_800_000_000.0


def ago( seconds ):
    import datetime
    return datetime.datetime.fromtimestamp( NOW - seconds, datetime.timezone.utc ).isoformat()


class TestAppendRecord:

    def test_it_appends_one_json_line_and_creates_the_fleet_dir( self, tmp_path ):
        base = tmp_path / "nested" / "fleet"
        assert e._append_record( "s1", { "a": 1 }, base_dir=base ) is True
        assert e._append_record( "s1", { "b": 2 }, base_dir=base ) is True
        lines = e.events_path( "s1", base_dir=base ).read_text().splitlines()
        assert [ json.loads( l ) for l in lines ] == [ { "a": 1 }, { "b": 2 } ]

    def test_an_oserror_returns_false( self, tmp_path ):
        blocker = tmp_path / "file"
        blocker.write_text( "x" )
        assert e._append_record( "s2", { "a": 1 }, base_dir=blocker ) is False

    def test_an_unserializable_record_returns_false_and_writes_nothing( self, tmp_path ):
        assert e._append_record( "s3", { "a": { 1, 2 } }, base_dir=tmp_path ) is False
        assert e.events_path( "s3", base_dir=tmp_path ).read_text() == ""

    def test_a_circular_record_returns_false( self, tmp_path ):
        loop = {}
        loop[ "me" ] = loop
        assert e._append_record( "s4", loop, base_dir=tmp_path ) is False


class TestEmitKind:

    def test_it_writes_the_kind_tagged_record_with_no_outcome_key( self, tmp_path ):
        assert e._emit_kind( "some_kind", "s5", "Persona", "2026-10-18T00:00:00+00:00", tmp_path ) is True
        record = json.loads( e.events_path( "s5", base_dir=tmp_path ).read_text() )
        assert record == { "schema_version": e.SCHEMA_VERSION, "session_id": "s5", "persona": "Persona",
                           "ts": "2026-10-18T00:00:00+00:00", "kind": "some_kind" }

    def test_a_missing_ts_is_filled_with_now( self, tmp_path ):
        e._emit_kind( "k", "s6", None, None, tmp_path )
        record = json.loads( e.events_path( "s6", base_dir=tmp_path ).read_text() )
        assert record[ "persona" ] is None and record[ "ts" ].endswith( "+00:00" )

    @pytest.mark.parametrize( "emitter, kind", [
        ( e.emit_idle_prompt,     "idle_prompt" ),
        ( e.emit_reaped,          "reaped" ),
        ( e.emit_task_transition, "task_transition" ),
    ] )
    def test_each_public_emitter_sends_its_own_literal_kind( self, tmp_path, emitter, kind ):
        assert emitter( "s7", persona="P", ts="2026-10-18T00:00:00+00:00", base_dir=tmp_path ) is True
        assert json.loads( e.events_path( "s7", base_dir=tmp_path ).read_text() )[ "kind" ] == kind

    def test_emit_outcome_refuses_an_unhashable_outcome_without_raising( self, tmp_path ):
        assert e.emit_outcome( "s8", "P", [ "poked" ], 1, 3, base_dir=tmp_path ) is False


class TestDebouncedNeed:

    def test_no_truthy_item_is_false_whatever_the_stamp( self ):
        assert o._debounced_need( [], None, NOW, 600 ) is False
        assert o._debounced_need( None, None, NOW, 600 ) is False
        assert o._debounced_need( [ None, 0, {} ], ago( 9999 ), NOW, 600 ) is False

    def test_an_undatable_stamp_owes( self ):
        assert o._debounced_need( [ "x" ], None, NOW, 600 ) is True
        assert o._debounced_need( [ "x" ], "not-a-ts", NOW, 600 ) is True

    def test_the_age_is_compared_with_greater_or_equal( self ):
        assert o._debounced_need( [ "x" ], ago( 599 ), NOW, 600 ) is False
        assert o._debounced_need( [ "x" ], ago( 600 ), NOW, 600 ) is True
        assert o._debounced_need( [ "x" ], ago( 601 ), NOW, 600 ) is True

    def test_the_threshold_argument_is_the_one_used( self ):
        assert o._debounced_need( [ "x" ], ago( 300 ), NOW, 240 ) is True
        assert o._debounced_need( [ "x" ], ago( 300 ), NOW, 360 ) is False


class TestPublicPredicatesKeepTheirShape:

    @pytest.mark.parametrize( "fn, items_name, ts_name, constant", [
        ( o.manager_needs_verification,     "outstanding_delegations", "last_verification_ts",        o.VERIFICATION_DEBOUNCE_SECONDS ),
        ( o.manager_needs_question_surface, "open_operator_gates",     "last_surfaced_questions_ts",  o.SURFACE_QUESTIONS_DEBOUNCE_SECONDS ),
    ] )
    def test_parameter_names_and_default_threshold_are_unchanged( self, fn, items_name, ts_name, constant ):
        params = inspect.signature( fn ).parameters
        assert list( params ) == [ items_name, ts_name, "now_epoch", "threshold_seconds" ]
        assert params[ "threshold_seconds" ].default == constant == 600

    def test_verification_passes_its_arguments_through_by_keyword( self ):
        call = lambda stamp: o.manager_needs_verification( outstanding_delegations=[ "x" ], last_verification_ts=stamp, now_epoch=NOW )
        assert call( ago( 600 ) ) is True and call( ago( 599 ) ) is False
        assert o.manager_needs_verification( outstanding_delegations=[], last_verification_ts=None, now_epoch=NOW ) is False

    def test_question_surface_passes_its_arguments_through_by_keyword( self ):
        call = lambda stamp: o.manager_needs_question_surface( open_operator_gates=[ "x" ], last_surfaced_questions_ts=stamp, now_epoch=NOW )
        assert call( ago( 600 ) ) is True and call( ago( 599 ) ) is False
        assert o.manager_needs_question_surface( open_operator_gates=[], last_surfaced_questions_ts=None, now_epoch=NOW ) is False
