#!/usr/bin/env python3
"""
cosa.utils.iso_timestamp.parse_iso: the one ISO-8601 reader the arbiter modules share.

Venue: :7999-eligible / local, pure.
"""
import datetime
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.agents.heartbeat_arbiter import dependency_graph, fleet_data_model, operator_gate_routing
from cosa.utils.iso_timestamp import parse_iso

UTC = datetime.timezone.utc


def test_a_zulu_stamp_reads_as_utc():
    assert parse_iso( "2026-06-05T12:00:00Z" ) == datetime.datetime( 2026, 6, 5, 12, 0, tzinfo=UTC )


def test_an_explicit_offset_is_kept():
    parsed = parse_iso( "2026-06-05T12:00:00+05:00" )
    assert parsed.utcoffset() == datetime.timedelta( hours=5 )
    assert parsed.hour == 12


def test_a_zoneless_stamp_is_read_as_utc():
    parsed = parse_iso( "2026-06-05T12:00:00" )
    assert parsed == datetime.datetime( 2026, 6, 5, 12, 0, tzinfo=UTC )


def test_surrounding_whitespace_is_ignored():
    assert parse_iso( "  2026-06-05T12:00:00Z \n" ) == datetime.datetime( 2026, 6, 5, 12, 0, tzinfo=UTC )


@pytest.mark.parametrize( "value", [ None, "", "   ", 123, 1.5, [ "2026-06-05T12:00:00Z" ], "not-a-ts", "2026-13-45T00:00:00Z" ] )
def test_anything_unreadable_is_none_and_never_raises( value ):
    assert parse_iso( value ) is None
    assert parse_iso( value, naive=True ) is None


def test_the_naive_option_returns_the_same_instant_in_utc_without_a_zone():
    parsed = parse_iso( "2026-06-05T12:00:00+05:00", naive=True )
    assert parsed == datetime.datetime( 2026, 6, 5, 7, 0 )
    assert parsed.tzinfo is None


def test_the_naive_option_leaves_a_utc_wall_clock_alone():
    assert parse_iso( "2026-06-05T12:00:00Z", naive=True ) == datetime.datetime( 2026, 6, 5, 12, 0 )
    assert parse_iso( "2026-06-05T12:00:00", naive=True ) == datetime.datetime( 2026, 6, 5, 12, 0 )


@pytest.mark.parametrize( "module", [ dependency_graph, fleet_data_model, operator_gate_routing ] )
def test_the_three_arbiter_modules_call_the_shared_parser( module ):
    assert module._parse_iso is parse_iso
