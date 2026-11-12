"""Unit tests for the one fleet base-dir resolver and its three callers."""
import pathlib

from cosa.agents.heartbeat_arbiter import respin_wake_check as rwc
from cosa.agents.heartbeat_arbiter import self_respin_observer as obs
from cosa.utils.fleet_base_dir import fleet_base_dir
from lupin_mcp import self_respin_core as src


def test_a_given_directory_comes_back_unchanged_and_never_reaches_the_fleet_root( monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", "/should-not-be-read" )
    assert fleet_base_dir( "/somewhere", "/x/other" ) == "/somewhere"


def test_none_resolves_the_fleet_data_root_of_the_given_repo_as_a_string( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path ) )
    assert fleet_base_dir( None, "/x/myrepo" ) == str( tmp_path / "myrepo" )
    assert isinstance( fleet_base_dir(), str )


def test_the_wake_check_keeps_treating_an_empty_directory_as_none( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path ) )
    assert rwc._resolve_base_dir( "" ) == fleet_base_dir()


def test_the_observer_passes_an_explicit_directory_through( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path ) )
    assert obs._resolve_base_dir( "/d" ) == "/d" and obs._resolve_base_dir( None ) == fleet_base_dir()


def test_the_marker_writer_keys_on_the_seats_own_repo( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path ) )
    assert src._resolve_base_dir( "/x/seatrepo" ) == str( tmp_path / "seatrepo" )
    monkeypatch.setattr( src, "resolve_repo_root", lambda: "/x/livered" )
    assert src._resolve_base_dir( None ) == str( tmp_path / "livered" )
