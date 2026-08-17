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
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( "author", "Tiffany", None )

    def test_reads_stamped_implicit_flag( self, tmp_path ):
        # The e5d600bd field is surfaced as the third tuple element.
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "Tiffany" },
                       "manager_figure_implicit": True } )
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( "author", "Tiffany", True )

    def test_missing_bridge_returns_nones( self, tmp_path ):
        _, find = bridge_factory( tmp_path )
        assert mf._read_bridge_fields( "absent", _find_path=find ) == ( None, None, None )

    def test_malformed_json_degrades( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", "{bad" )
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( None, None, None )

    def test_non_dict_persona_yields_no_name( self, tmp_path ):
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": "Tiffany" } )
        assert mf._read_bridge_fields( "s1", _find_path=find ) == ( "author", None, None )


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
        # Bridge says "mr radio"; env chain says "Mr. Radio" — must match. Uses
        # the EXACT live chain form "Mr. Radio,Tiberius,*" (ENV_LUPIN). The
        # keep-spaces canonical key preserves this match (verified-clear per the
        # plan's site-6 regression note).
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "mr radio" } } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is True

    def test_accent_tolerant_match_FLIP( self, tmp_path ):
        # FLIP (accent seam): bridge persona "maria" vs declared chain "María".
        # The pre-Phase-1 accent-keeping normalizer KEPT accents ("María" -> "maría")
        # and so MISSED this — canonical_persona_key accent-strips both to "maria".
        # Revert to the pre-Phase-1 accent-keeping normalizer and this assertion fails (False).
        env = { "LUPIN_ROOT": "/mnt/x/lupin", "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "María,Tiberius,*" }
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "maria" } } )
        assert mf.is_manager_figure( "s1", environ=env, _find_path=find ) is True

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
        # The locator raising inside _read_bridge_fields hits ITS except → (None, None, None).
        def exploding_find( _sid ):
            raise RuntimeError( "boom" )
        assert mf._read_bridge_fields( "s1", _find_path=exploding_find ) == ( None, None, None )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=exploding_find ) is False


class TestStampedImplicitFlag:
    """
    Bug e5d600bd — the STATIC bridge field is the source of truth server-side.
    The stamp is computed at registration with the caller's real env; the server
    reads it and NEVER re-derives the implicit source from its own (empty) env.
    """

    def test_stamped_true_wins_without_any_env_chain( self, tmp_path, monkeypatch ):
        # THE SERVER-SIDE FIX. environ=None (os.environ, empty of chain vars) and
        # NO persona match possible — yet a stamped True resolves True. This is the
        # exact caller shape of tasks.py:652 (is_manager_figure(session_id), no env)
        # that was universally returning False before the stamp existed.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "Tiffany" },
                       "manager_figure_implicit": True } )
        assert mf.is_manager_figure( "s1", _find_path=find ) is True

    def test_stamped_false_is_authoritative_over_a_matching_chain( self, tmp_path, monkeypatch ):
        # A present stamp is trusted even when the env WOULD have matched — the
        # stamp is the resolved answer, not a hint. Guards against a stratum
        # mis-classification sneaking back in via ambient env.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "Tiberius" },
                       "manager_figure_implicit": False } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is False

    def test_explicit_manager_role_beats_a_false_stamp( self, tmp_path, monkeypatch ):
        # Explicit source is checked first and independently of the stamp.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "manager", "voice_persona": { "name": "Tiffany" },
                       "manager_figure_implicit": False } )
        assert mf.is_manager_figure( "s1", environ={}, _find_path=find ) is True

    def test_absent_stamp_falls_back_to_env_compute( self, tmp_path, monkeypatch ):
        # Legacy bridge (no field): the env-based fallback still resolves it, so a
        # hook-side caller passing its own env is unchanged. Self-heals on re-reg.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "voice_persona": { "name": "Tiberius" } } )
        assert mf.is_manager_figure( "s1", environ=ENV_LUPIN, _find_path=find ) is True

    def test_maria_server_env_GREEN( self, tmp_path, monkeypatch ):
        # RED→GREEN receipt (bug e5d600bd), as a re-runnable test. María is a named
        # standing manager; pre-fix, the server-shaped caller (no chain in env) read
        # False — the reported bug. Post-fix, the registration-time stamp carries
        # the answer, so the SAME server-shaped caller reads True.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "María" },
                       "manager_figure_implicit": True } )
        # environ carries NO COSA_VOICE_PREFERRED_PERSONA__* — the container shape.
        assert mf.is_manager_figure( "s1", environ={ "LUPIN_ROOT": "/var/lupin" }, _find_path=find ) is True

    def test_sam_overflow_under_maria_chain_stays_false( self, tmp_path, monkeypatch ):
        # Sam is the overflow default persona, never a named standing manager.
        # Stamped False at registration; the server-shaped caller must keep it a
        # worker — the stratum half: an overflow seat must NOT bias the manager arm.
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
        write, find = bridge_factory( tmp_path )
        write( "s1", { "role": "author", "voice_persona": { "name": "Sam" },
                       "manager_figure_implicit": False } )
        assert mf.is_manager_figure( "s1", environ={ "LUPIN_ROOT": "/var/lupin" }, _find_path=find ) is False


class TestResolveImplicitManagerFigure:
    """The pure resolver register_session calls to compute the stamp."""

    @pytest.fixture( autouse=True )
    def _stub_project( self, monkeypatch ):
        monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )

    def test_named_entry_matches( self ):
        assert mf.resolve_implicit_manager_figure( "Tiberius", ENV_LUPIN ) is True

    def test_worker_persona_does_not_match( self ):
        assert mf.resolve_implicit_manager_figure( "Tiffany", ENV_LUPIN ) is False

    def test_no_persona_is_false( self ):
        assert mf.resolve_implicit_manager_figure( None, ENV_LUPIN ) is False

    def test_wildcard_is_never_a_match( self ):
        assert mf.resolve_implicit_manager_figure( "*", ENV_LUPIN ) is False

    def test_unset_chain_is_false( self ):
        assert mf.resolve_implicit_manager_figure( "Tiberius", { "LUPIN_ROOT": "/x/lupin" } ) is False

    def test_exploding_env_degrades_to_false( self ):
        class ExplodingEnv( dict ):
            def get( self, *a, **k ):
                raise RuntimeError( "boom" )
        assert mf.resolve_implicit_manager_figure( "Tiberius", ExplodingEnv() ) is False

    def test_sam_overflow_persona_under_maria_chain_is_false( self ):
        # Pair 2 (Cheech's ask): allocated="Sam" under chain "María,*" — the `*`
        # matches "anything free" for ALLOCATION but is NEVER a manager claim, and
        # Sam is not the named entry, so the implicit source is False.
        env = { "LUPIN_ROOT": "/x/lupin", "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "María,*" }
        assert mf.resolve_implicit_manager_figure( "Sam", env ) is False

    def test_maria_named_entry_under_own_chain_is_true( self ):
        env = { "LUPIN_ROOT": "/x/lupin", "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "María,*" }
        assert mf.resolve_implicit_manager_figure( "María", env ) is True
