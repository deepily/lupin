"""
Tests for project_from_bridge_cwd, the cwd walk the arbiter reuses.
"""

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge


@pytest.mark.parametrize( "cwd", [ None, "" ] )
def test_a_missing_cwd_has_no_project( cwd ):
    assert session_bridge.project_from_bridge_cwd( cwd ) is None


def test_a_cwd_inside_a_repo_names_the_repo_directory( tmp_path ):
    repo = tmp_path / "somerepo"
    ( repo / ".git" ).mkdir( parents=True )
    ( repo / "src" ).mkdir()
    assert session_bridge.project_from_bridge_cwd( str( repo / "src" ) ) == "somerepo"


def test_a_cwd_with_no_repo_names_its_own_directory( tmp_path ):
    plain = tmp_path / "PlainDir"
    plain.mkdir()
    assert session_bridge.project_from_bridge_cwd( str( plain ) ) == "plaindir"


def test_the_calling_sessions_own_resolver_agrees_with_the_split_out_walk( tmp_path, monkeypatch ):
    import json
    repo = tmp_path / "agreeing"
    ( repo / ".git" ).mkdir( parents=True )
    bridge = tmp_path / "cc-bridge.json"
    bridge.write_text( json.dumps( { "cwd": str( repo ) } ) )
    monkeypatch.setattr( session_bridge, "_find_session_file", lambda: ( str( bridge ), "env" ) )
    assert session_bridge._resolve_project_from_bridge_cwd() == session_bridge.project_from_bridge_cwd( str( repo ) ) == "agreeing"
