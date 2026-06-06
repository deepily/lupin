#!/usr/bin/env python3
"""
Unit tests for manager_resolver — v2.2 lane B6 / D5 (resolve a worker's manager
from spawn-lineage; filename-parse + re-slugify guard; layered escalate-don't-
guess degradation). 100% line+branch+function on the resolve + scan logic
(bridge/persona IO lookups are pragma'd boundaries).
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.manager_resolver import (
    find_manager_session_id, resolve_manager, quick_smoke_test,
    SOURCE_LINEAGE, SOURCE_DECLARED, SOURCE_UNRESOLVED,
)
from lupin_mcp.session_spawner import _manifest_path


def _write_manifest( d: Path, manager_id: str, session_names ):
    path = d / f"spawned-{manager_id}.json"
    path.write_text( json.dumps( [ { "session_name": n, "requested_role": "reviewer",
                                     "status": "spawned", "dry_run": False } for n in session_names ] ) )
    return path


# ── find_manager_session_id ────────────────────────────────────────────────────

class TestFindManager:
    def test_match_returns_manager_id( self, tmp_path ):
        _write_manifest( tmp_path, "a9f5c9bf-3987-489a-8f5f-aaaa", [ "cc-rev-tib-0", "cc-rev-tib-1" ] )
        assert find_manager_session_id( "cc-rev-tib-1", tmp_path ) == "a9f5c9bf-3987-489a-8f5f-aaaa"

    def test_no_match_returns_none( self, tmp_path ):
        _write_manifest( tmp_path, "mgr-uuid", [ "cc-rev-0" ] )
        assert find_manager_session_id( "cc-rev-NOPE", tmp_path ) is None

    def test_empty_tmux_returns_none( self, tmp_path ):
        assert find_manager_session_id( "", tmp_path ) is None

    def test_lossy_filename_rejected_by_guard( self, tmp_path ):
        # A manager id with a non-[alnum-_] char does NOT round-trip _slug → guard → None.
        _write_manifest( tmp_path, "bad@id", [ "cc-rev-x" ] )
        assert find_manager_session_id( "cc-rev-x", tmp_path ) is None

    def test_glob_oserror_returns_none( self, tmp_path ):
        with patch.object( Path, "glob", side_effect=OSError( "fs" ) ):
            assert find_manager_session_id( "cc-rev-x", tmp_path ) is None

    def test_no_manifests_returns_none( self, tmp_path ):
        assert find_manager_session_id( "cc-rev-x", tmp_path ) is None

    def test_multi_match_returns_none( self, tmp_path ):
        """María collision guard: same tmux_session in 2 managers' manifests → unresolved."""
        _write_manifest( tmp_path, "mgr-uuid-aaaa", [ "cc-rev-shared" ] )
        _write_manifest( tmp_path, "mgr-uuid-bbbb", [ "cc-rev-shared" ] )
        assert find_manager_session_id( "cc-rev-shared", tmp_path ) is None

    def test_manifest_path_slugify_does_not_truncate( self ):
        """Injective confirmation: _manifest_path (the filename transform) has NO
        length cap, so distinct long ids never collide by truncation."""
        long_id = "a" * 200
        assert _manifest_path( long_id ).name == f"spawned-{long_id}.json"
        # and a real UUID round-trips as identity (slug = identity on hex+hyphen)
        uuid = "a9f5c9bf-3987-489a-8f5f-5ebe6cc98127"
        assert _manifest_path( uuid ).name == f"spawned-{uuid}.json"


# ── resolve_manager ────────────────────────────────────────────────────────────

class TestResolveManager:
    def test_lineage_hit( self ):
        out = resolve_manager(
            "worker-1",
            bridge_lookup  = lambda sid: { "tmux_session": "cc-rev-tib-0" },
            manifest_scan  = lambda tmux, sd: "tib-uuid" if tmux == "cc-rev-tib-0" else None,
            persona_lookup = lambda mid: { "name": "Tiberius" },
        )
        assert out == { "manager_session_id": "tib-uuid", "manager_persona": "Tiberius", "source": SOURCE_LINEAGE }

    def test_lineage_miss_declared_fallback( self ):
        out = resolve_manager( "w", declared_manager="manager-on-duty",
                               bridge_lookup=lambda sid: { "tmux_session": "x" },
                               manifest_scan=lambda tmux, sd: None )
        assert out == { "manager_session_id": None, "manager_persona": "manager-on-duty", "source": SOURCE_DECLARED }

    def test_lineage_miss_no_declared_unresolved( self ):
        out = resolve_manager( "w",
                               bridge_lookup=lambda sid: { "tmux_session": "x" },
                               manifest_scan=lambda tmux, sd: None )
        assert out[ "source" ] == SOURCE_UNRESOLVED and out[ "manager_persona" ] is None

    def test_no_bridge_falls_back( self ):
        out = resolve_manager( "w", declared_manager="dut",
                               bridge_lookup=lambda sid: None )
        assert out[ "source" ] == SOURCE_DECLARED

    def test_bridge_without_tmux_falls_back( self ):
        out = resolve_manager( "w", bridge_lookup=lambda sid: { "no_tmux": True } )
        assert out[ "source" ] == SOURCE_UNRESOLVED

    def test_lineage_id_but_no_persona_does_not_guess( self ):
        # manager_session_id resolves but persona is None → never DM a None persona → fall back
        out = resolve_manager( "w", declared_manager="dut",
                               bridge_lookup=lambda sid: { "tmux_session": "t" },
                               manifest_scan=lambda tmux, sd: "mgr-uuid",
                               persona_lookup=lambda mid: None )
        assert out[ "source" ] == SOURCE_DECLARED

    def test_exception_anywhere_falls_back_never_raises( self ):
        def _boom( sid ):
            raise RuntimeError( "bridge fs error" )
        out = resolve_manager( "w", bridge_lookup=_boom )       # no declared → unresolved
        assert out[ "source" ] == SOURCE_UNRESOLVED


def test_quick_smoke_test():
    assert quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
