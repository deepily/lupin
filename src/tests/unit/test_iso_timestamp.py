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
from cosa.utils.iso_timestamp import aware_moment, parse_iso

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


@pytest.mark.parametrize( "module", [ dependency_graph, fleet_data_model, operator_gate_routing ] )
def test_the_three_arbiter_modules_call_the_shared_parser( module ):
    assert module._parse_iso is parse_iso


def test_aware_moment_passes_none_through():
    assert aware_moment( None ) is None


def test_aware_moment_reads_a_zoneless_string_and_a_zoneless_datetime_as_utc():
    expected = datetime.datetime( 2026, 6, 5, 12, 0, tzinfo=UTC )
    assert aware_moment( "2026-06-05T12:00:00" ) == expected
    assert aware_moment( datetime.datetime( 2026, 6, 5, 12, 0 ) ) == expected


def test_aware_moment_keeps_an_offset_it_is_given():
    stamp = datetime.datetime( 2026, 6, 5, 12, 0, tzinfo=datetime.timezone( datetime.timedelta( hours=5 ) ) )
    assert aware_moment( stamp ).utcoffset() == datetime.timedelta( hours=5 )
    assert aware_moment( "2026-06-05T12:00:00+05:00" ).utcoffset() == datetime.timedelta( hours=5 )


def test_aware_moment_raises_on_a_string_that_does_not_parse():
    with pytest.raises( AttributeError ):
        aware_moment( "not a time" )
