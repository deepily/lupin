#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pins the two field helpers behind the v2_eval response readers.

`_ok_field` is gated on `ok`; `_reported_field` is gated on the HTTP status. The six public readers
are thin calls to them, so each reader is checked against a record that only its own gate admits.
"""

import os
import sys

import pytest


def _load_module():
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import v2_eval
    return v2_eval


ve = _load_module()


def _ok( **payload ):
    return { "ok": True, "status_code": 200, "payload": payload }


def test_ok_field_reads_the_key_from_an_ok_record():
    assert ve._ok_field( _ok( path = "agent" ), "path" ) == "agent"


def test_ok_field_is_none_for_a_missing_key():
    assert ve._ok_field( _ok( path = "agent" ), "route_reason" ) is None


def test_ok_field_is_none_when_the_record_is_not_ok_even_if_the_payload_has_the_key():
    record = { "ok": False, "status_code": 200, "payload": { "path": "agent" } }
    assert ve._ok_field( record, "path" ) is None


def test_reported_field_reads_the_key_from_a_200_even_when_ok_is_false():
    record = { "ok": False, "status_code": 200, "payload": { "route_reason": "replay_error" } }
    assert ve._reported_field( record, "route_reason" ) == "replay_error"


@pytest.mark.parametrize( "record", [
    { "ok": True,  "status_code": 502, "payload": { "status": "done" } },
    { "ok": True,  "status_code": 200, "payload": None },
    { "ok": True,  "status_code": 200, "payload": "not a dict" },
    { "ok": True,                      "payload": { "status": "done" } },
] )
def test_reported_field_is_none_for_a_non_200_or_a_non_dict_payload( record ):
    assert ve._reported_field( record, "status" ) is None


@pytest.mark.parametrize( "reader,key", [
    ( "response_path",         "path" ),
    ( "response_route_reason", "route_reason" ),
    ( "matched_command",       "command" ),
    ( "response_trace_id",     "trace_id" ),
] )
def test_each_ok_gated_reader_asks_for_its_own_key( reader, key ):
    record = _ok( path = "p", route_reason = "r", command = "c", trace_id = "t" )
    expected = { "path": "p", "route_reason": "r", "command": "c", "trace_id": "t" }[ key ]
    assert getattr( ve, reader )( record ) == expected
    assert getattr( ve, reader )( { "ok": False, "payload": { key: "x" } } ) is None


@pytest.mark.parametrize( "reader,key", [
    ( "reported_route_reason", "route_reason" ),
    ( "response_status",       "status" ),
] )
def test_each_status_gated_reader_asks_for_its_own_key( reader, key ):
    record = { "ok": False, "status_code": 200, "payload": { "route_reason": "r", "status": "s" } }
    assert getattr( ve, reader )( record ) == { "route_reason": "r", "status": "s" }[ key ]
    assert getattr( ve, reader )( { "status_code": 500, "payload": { key: "x" } } ) is None
