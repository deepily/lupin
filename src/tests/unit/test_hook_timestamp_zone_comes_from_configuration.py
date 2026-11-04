"""
The hook timestamp takes its zone from the `app timezone` key and nothing else.

This file checks three things:

- A configured zone is honoured: one instant stamps differently under America/Los_Angeles and Asia/Tokyo.
- The read happens once per process, however many stamps are taken.
- A failed read never stamps a guessed zone. The stamp ends in `+00:00`, stderr gets one line and stdout gets none.
"""
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import lupin_cli.claude_code.hooks.lib.hook_common as hc

FIXED_UTC_TIME = datetime( 2026, 10, 30, 22, 30, 5, 123000, tzinfo=timezone.utc )


@pytest.fixture( autouse=True )
def fresh_zone_cache():
    """Each test starts with an unread zone and leaves none behind."""
    hc._APP_ZONE.update( name=None, failed=False )
    yield
    hc._APP_ZONE.update( name=None, failed=False )


def _stamp_at_instant():
    """Stamp the fixed UTC time through the real zone conversion, so the configured zone decides."""
    with patch.object( hc.cu, "get_current_datetime_raw", side_effect=lambda tz_name: FIXED_UTC_TIME.astimezone( ZoneInfo( tz_name ) ) ):
        return hc.get_timestamp()


@pytest.mark.parametrize( "zone, expected", [
    ( "America/Los_Angeles", "2026.10.30 @ 15:30 05,123ms" ),
    ( "Asia/Tokyo",          "2026.10.31 @ 07:30 05,123ms" ),
] )
def test_the_configured_zone_decides_the_stamp( zone, expected ):
    with patch.object( hc, "get_app_timezone", return_value=zone ), patch.object( hc, "ConfigurationManager" ):
        assert _stamp_at_instant() == expected


def test_the_zone_is_read_once_per_process():
    with patch.object( hc, "get_app_timezone", return_value="Asia/Tokyo" ) as read, patch.object( hc, "ConfigurationManager" ) as mgr:
        _stamp_at_instant(); _stamp_at_instant(); _stamp_at_instant()
    assert read.call_count == 1 and mgr.call_count == 1


def test_the_read_runs_with_stdout_quieted(capsys):
    def noisy_manager( **kwargs ):
        print( "BANNER" )
    with patch.object( hc, "get_app_timezone", return_value="Asia/Tokyo" ), patch.object( hc, "ConfigurationManager", side_effect=noisy_manager ):
        _stamp_at_instant()
    assert capsys.readouterr().out == ""


def test_a_failed_read_stamps_utc_with_an_explicit_offset_and_says_so_once_on_stderr( capsys ):
    with patch.object( hc, "get_app_timezone", side_effect=ValueError( "Key [app timezone] is missing" ) ), patch.object( hc, "ConfigurationManager" ):
        first  = hc.get_timestamp()
        second = hc.get_timestamp()
    captured = capsys.readouterr()
    assert first.endswith( "ms+00:00" ) and second.endswith( "ms+00:00" )
    assert captured.out == ""
    assert captured.err.count( "app timezone" ) == 1 and captured.err.count( "\n" ) == 1


def test_a_failed_read_is_not_a_code_default():
    with patch.object( hc, "get_app_timezone", side_effect=ValueError( "x" ) ), patch.object( hc, "ConfigurationManager" ):
        stamp = hc.get_timestamp()
    assert hc._APP_ZONE == { "name": None, "failed": True }
    assert stamp.endswith( "ms+00:00" )
