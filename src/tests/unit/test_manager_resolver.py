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

import cosa.agents.heartbeat_arbiter.manager_resolver as MR
from cosa.agents.heartbeat_arbiter.manager_resolver import (
    find_manager_session_id, resolve_manager, quick_smoke_test,
    pick_declared_managers_from_env,
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
    # ── spawned_by PRIMARY path (collision fix, 2026-06-09) ──────────────────

    def test_spawned_by_primary_lineage_hit( self ):
        """spawned_by present → lineage hit from it; manifest scan NOT consulted."""
        scan_calls = [ ]
        def _scan( tmux, sd ):
            scan_calls.append( tmux )
            return "WRONG-mgr-uuid"
        out = resolve_manager(
            "worker-1",
            bridge_lookup  = lambda sid: { "tmux_session": "cc-rev-tib-1", "spawned_by": "tib-uuid-real" },
            manifest_scan  = _scan,
            persona_lookup = lambda mid: { "name": "Tiberius" } if mid == "tib-uuid-real" else { "name": "WRONG" },
        )
        assert out == { "manager_session_id": "tib-uuid-real", "manager_persona": "Tiberius", "source": SOURCE_LINEAGE }
        assert scan_calls == [ ]   # PRIMARY short-circuits the ambiguous name join

    def test_spawned_by_beats_manifest_collision( self, tmp_path ):
        """The production bug: reused child name in 3 manifests would collide →
        None on the scan path, but spawned_by resolves it unambiguously."""
        _write_manifest( tmp_path, "aaaaaaaa-0000-0000-0000-000000000000", [ "cc-reviewer-tiberius-1" ] )
        _write_manifest( tmp_path, "bbbbbbbb-0000-0000-0000-000000000000", [ "cc-reviewer-tiberius-1" ] )
        _write_manifest( tmp_path, "cccccccc-0000-0000-0000-000000000000", [ "cc-reviewer-tiberius-1" ] )
        out = resolve_manager(
            "worker-1",
            bridge_lookup  = lambda sid: { "tmux_session" : "cc-reviewer-tiberius-1",
                                           "spawned_by"   : "aaaaaaaa-0000-0000-0000-000000000000" },
            persona_lookup = lambda mid: { "name": "Tiberius" },
            session_dir    = tmp_path,
        )
        assert out[ "source" ] == SOURCE_LINEAGE
        assert out[ "manager_session_id" ] == "aaaaaaaa-0000-0000-0000-000000000000"

    def test_spawned_by_but_no_persona_degrades_declared( self ):
        # spawned_by resolves but persona is un-DM-able → declared, never guess
        out = resolve_manager( "w", declared_manager="dut",
                               bridge_lookup=lambda sid: { "spawned_by": "dead-mgr-uuid" },
                               persona_lookup=lambda mid: None )
        assert out == { "manager_session_id": None, "manager_persona": "dut", "source": SOURCE_DECLARED }

    def test_spawned_by_but_no_persona_degrades_unresolved( self ):
        out = resolve_manager( "w",
                               bridge_lookup=lambda sid: { "spawned_by": "dead-mgr-uuid" },
                               persona_lookup=lambda mid: { "no_name": True } )
        assert out[ "source" ] == SOURCE_UNRESOLVED

    def test_empty_spawned_by_falls_back_to_manifest_scan( self ):
        """Legacy-shaped bridge (spawned_by empty) → the original scan path."""
        out = resolve_manager(
            "worker-1",
            bridge_lookup  = lambda sid: { "tmux_session": "cc-rev-tib-0", "spawned_by": "" },
            manifest_scan  = lambda tmux, sd: "tib-uuid" if tmux == "cc-rev-tib-0" else None,
            persona_lookup = lambda mid: { "name": "Tiberius" },
        )
        assert out == { "manager_session_id": "tib-uuid", "manager_persona": "Tiberius", "source": SOURCE_LINEAGE }

    # ── manifest-scan FALLBACK path (legacy bridges, unchanged behavior) ─────

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


# ── pick_declared_managers_from_env (COSA_VOICE_MANAGERS__<PROJECT>) ───────────

class TestPickDeclaredManagersFromEnv:
    """Declared-manager roster parsing — multi-manager-per-repo (Rick 2026-06-11)."""

    def test_csv_with_multiword_names( self ):
        env = { "COSA_VOICE_MANAGERS__LUPIN": "Tiberius, Mr. Radio" }
        assert pick_declared_managers_from_env( "lupin", environ=env ) == [ "Tiberius", "Mr. Radio" ]

    def test_project_normalization_hyphen_and_case( self ):
        env = { "COSA_VOICE_MANAGERS__COSA_VOICE": "Rio" }
        assert pick_declared_managers_from_env( "cosa-voice", environ=env ) == [ "Rio" ]
        assert pick_declared_managers_from_env( "  Cosa-Voice  ", environ=env ) == [ "Rio" ]

    def test_case_insensitive_dedupe_first_wins( self ):
        env = { "COSA_VOICE_MANAGERS__LUPIN": "Rio, rio, RIO, Krishna" }
        assert pick_declared_managers_from_env( "lupin", environ=env ) == [ "Rio", "Krishna" ]

    def test_punct_tolerant_dedupe_first_wins( self ):
        """F-B: the dedup key is normalize-keyed — "Mr. Radio" and "mr radio"
        declare ONE manager; the first (verbatim) spelling is emitted."""
        env = { "COSA_VOICE_MANAGERS__LUPIN": "Mr. Radio, mr radio, MR.RADIO, Tiberius" }
        assert pick_declared_managers_from_env( "lupin", environ=env ) == [ "Mr. Radio", "Tiberius" ]

    def test_wildcard_elements_dropped( self ):
        # A copy-pasted chain expression must not poison the roster.
        env = { "COSA_VOICE_MANAGERS__LUPIN": "Mr. Radio,Tiberius,*" }
        assert pick_declared_managers_from_env( "lupin", environ=env ) == [ "Mr. Radio", "Tiberius" ]

    def test_unset_empty_whitespace_value( self ):
        assert pick_declared_managers_from_env( "lupin", environ={ } ) == [ ]
        assert pick_declared_managers_from_env( "lupin", environ={ "COSA_VOICE_MANAGERS__LUPIN": "" } ) == [ ]
        assert pick_declared_managers_from_env( "lupin", environ={ "COSA_VOICE_MANAGERS__LUPIN": " , ,*" } ) == [ ]

    def test_project_none_empty_whitespace( self ):
        env = { "COSA_VOICE_MANAGERS__LUPIN": "Rio" }
        assert pick_declared_managers_from_env( None, environ=env )  == [ ]
        assert pick_declared_managers_from_env( "", environ=env )    == [ ]
        assert pick_declared_managers_from_env( "   ", environ=env ) == [ ]

    def test_default_environ_is_os_environ( self, monkeypatch ):
        monkeypatch.setenv( "COSA_VOICE_MANAGERS__LUPIN", "Tiffany" )
        assert pick_declared_managers_from_env( "lupin" ) == [ "Tiffany" ]


# ── resolve_active_managers — declared-roster union ────────────────────────────

class TestResolveActiveManagersDeclared:
    """Declared ∪ lineage union; phantom guard applies to declared identically."""

    def test_declared_live_bridge_no_manifest_included( self ):
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "mgr-new": "Mr. Radio" },
            list_managers=lambda sd: set(),                       # owns NO manifest yet
            declared_managers=[ "Mr. Radio" ] )
        assert managers == [ "Mr. Radio" ]

    def test_declared_match_is_case_insensitive_bridge_casing_wins( self ):
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "mgr-new": "mr. radio" },
            list_managers=lambda sd: set(),
            declared_managers=[ "MR. RADIO" ] )
        assert managers == [ "mr. radio" ]                        # bridge is the name authority

    def test_declared_match_is_punct_tolerant_JOURNAL_REGRESSION( self ):
        """F-B regression pin (2026-06-11): the EVENT-shape persona "mr radio"
        (no period) must satisfy declared "Mr. Radio" on the fanout site too —
        pre-fix this site shared fleet_render's exact-compare miss."""
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "mgr-new": "mr radio" },
            list_managers=lambda sd: set(),
            declared_managers=[ "Mr. Radio" ] )
        assert managers == [ "mr radio" ]                         # bridge casing emitted, role granted

    def test_declared_union_with_lineage_manager( self ):
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "mgr-a": "Tiberius", "mgr-b": "Mr. Radio" },
            list_managers=lambda sd: { "mgr-a" },                 # only Tiberius owns a manifest
            declared_managers=[ "Mr. Radio" ] )
        assert managers == [ "Mr. Radio", "Tiberius" ]            # sorted distinct union

    def test_declared_without_live_bridge_excluded_phantom_guard( self ):
        managers = MR.resolve_active_managers(
            who_rows=[ { "session_id": "mgr-x", "persona_name": "Mr. Radio" } ],
            bridge_sessions={ },                                  # declared but PID-dead
            list_managers=lambda sd: set(),
            declared_managers=[ "Mr. Radio" ] )
        assert managers == [ ]

    def test_declared_does_not_promote_other_personas( self ):
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "wkr-1": "Rio" },
            list_managers=lambda sd: set(),
            declared_managers=[ "Mr. Radio" ] )
        assert managers == [ ]                                    # Rio is not declared, not lineage

    def test_no_manifests_no_declared_short_circuits( self ):
        assert MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "s": "P" },
            list_managers=lambda sd: set(), declared_managers=None ) == [ ]

    def test_declared_blank_names_ignored( self ):
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "mgr-new": "Ann" },
            list_managers=lambda sd: set(),
            declared_managers=[ "  ", "Ann" ] )
        assert managers == [ "Ann" ]

    def test_declared_with_none_persona_bridge_excluded( self ):
        # A live bridge with no persona can never match a declared name.
        managers = MR.resolve_active_managers(
            who_rows=[ ], bridge_sessions={ "mgr-new": None },
            list_managers=lambda sd: set(),
            declared_managers=[ "Mr. Radio" ] )
        assert managers == [ ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )


def test_resolve_active_managers_falsy_bridge_sid_skipped():
    """An empty-string bridge key (corrupt discovery row) is skipped, never a candidate."""
    managers = MR.resolve_active_managers(
        who_rows=[ ], bridge_sessions={ "": "Ann", "mgr-a": "Ann" },
        list_managers=lambda sd: set(),
        declared_managers=[ "Ann" ] )
    assert managers == [ "Ann" ]
