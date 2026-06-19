#!/usr/bin/env python3
"""
Unit tests — manager-figure predicate (F4 write gate, Phase 2).

Venue: :7999-eligible / local — bridge files under tmp_path, env injected.
Covers _read_bridge_fields / is_manager_figure to 100% lines/branches/
functions. The predicate gates WRITES, so every doubt case must resolve
False (fail-closed). Project-name resolution converged onto the shared
session_bridge.resolve_project_name (bug 9bf1dc4a); the is_manager_figure
tests stub it so they exercise the predicate logic deterministically,
independent of the ambient session bridge (resolve_project_name's own
branches are covered in test_session_bridge_lookup::TestResolveProjectName).
"""
import json
import os
import sys
from pathlib import Path

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import manager_figure as mf


def bridge_factory( tmp_path ):
    """Build a bridge-file writer + locator pair for injection."""
    def write( session_id, content ):
        path = tmp_path / f"{session_id}.json"
        path.write_text( content if isinstance( content, str ) else json.dumps( content ) )
        return path

    def find( session_id ):
        path = tmp_path / f"{session_id}.json"
        return path if path.exists() else None

    return write, find


ENV_LUPIN = { "LUPIN_ROOT": "/mnt/x/lupin", "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "Mr. Radio,Tiberius,*" }


class TestReadBridgeFields:

    def test_reads_role_and_persona( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "Tiffany" } } )
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( "author", "Tiffany" )

    def test_missing_bridge_returns_nones( self, tmp_path ):
        _, find = bridge_factory( tmp_path )
        assert mf._read_bridge_fields( "absent", _find_path=find ) == ( None, None )

    def test_malformed_json_degrades( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", "{bad" )
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( None, None )

    def test_non_dict_persona_yields_no_name( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": "Tiffany" } )
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( "author", None )


class TestIsManagerFigure:

    @pytest.fixture( autouse=True )
    def _stub_project( self, monkeypatch ):
        # is_manager_figure resolves the project via the shared, bridge-cwd-
        # anchored session_bridge.resolve_project_name. Stub it to "lupin" so
        # these tests deterministically exercise the predicate's role/persona-
        # chain logic against ENV_LUPIN, independent of the ambient session
        # bridge running the test suite.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )

    def test_explicit_manager_role_wins( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "manager", "voice_persona": { "name": "Tiffany" } } )
        # No env chain at all — explicit role alone suffices.
        assert mf.is_manager_figure( "s1", environ={ "LUPIN_ROOT": "/x/lupin" }, _find_path=find ) is True

    def test_implicit_named_persona_matches( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "Tiberius" } } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is True

    def test_punctuation_tolerant_match( self, tmp_path ):
        # Bridge says "mr radio"; env chain says "Mr. Radio" — must match.
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "mr radio" } } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is True

    def test_worker_persona_is_not_manager( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "Tiffany" } } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is False

    def test_wildcard_entry_is_never_a_manager_claim( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "*" } } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is False

    def test_missing_bridge_fails_closed( self, tmp_path ):
        _, find = bridge_factory( tmp_path )
        assert mf.is_manager_figure( "absent", environ=ENV_LUPIN, _find_path=find ) is False

    def test_no_persona_fails_closed( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author" } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is False

    def test_unset_env_chain_fails_closed( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "Tiberius" } } )
        assert mf.is_manager_figure( "s1", environ={ "LUPIN_ROOT": "/x/lupin" }, _find_path=find ) is False

    def test_internal_error_fails_closed( self, tmp_path ):
        def exploding_find( _sid ):
            raise RuntimeError( "boom" )
        # _read_bridge_fields swallows the locator error; force the outer
        # belt instead via an environ whose .get explodes.
        class ExplodingEnv( dict ):
            def get( self, *a, **k ):
                raise RuntimeError( "boom" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "Tiberius" } } )
        assert mf.is_manager_figure( "s1", environ=ExplodingEnv(), _find_path=find ) is False

    def test_locator_error_degrades_to_nones_then_false( self, tmp_path ):
        # The locator raising inside _read_bridge_fields hits ITS except → (None, None).
        def exploding_find( _sid ):
            raise RuntimeError( "boom" )
        assert mf._read_bridge_fields( "s1", _find_path=exploding_find ) == ( None, None )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=exploding_find ) is False
