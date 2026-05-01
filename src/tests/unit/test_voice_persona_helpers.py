#!/usr/bin/env python3
"""
Unit tests for voice persona allocation helpers.

Covers the pure-function module at src/cosa/rest/voice_persona_helpers.py
and the bridge primitives at src/lupin_cli/claude_code/hooks/lib/session_bridge.py
that the helpers compose.

See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
"""
import json
import os
import random
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.voice_persona_helpers import (
    load_persona_pool_from_config,
    pick_unallocated_persona,
    borrowed_persona_for_sid,
    allocate_persona_for_session,
    display_name_for
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_voice_persona, set_voice_persona, find_active_voice_persona_sessions,
    find_session_path_by_id
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

POOL_6 = [
    { "name": "maria",    "voice_id": "v_maria",    "icon": "🌸", "color": "#E91E63", "profile": "warm female"        },
    { "name": "mr radio", "voice_id": "v_mrnpr", "icon": "🦉", "color": "#FFA000", "profile": "authoritative male" },
    { "name": "Rachel",  "voice_id": "v_rachel",  "icon": "🕊️", "color": "#4CAF50", "profile": "calm female"        },
    { "name": "Tiberius",    "voice_id": "v_tiberius",    "icon": "🌑", "color": "#3F51B5", "profile": "deep male"          },
    { "name": "Domi",    "voice_id": "v_domi",    "icon": "⚡", "color": "#C2185B", "profile": "young female"       },
    { "name": "Arnold",  "voice_id": "v_arnold",  "icon": "🪨", "color": "#C62828", "profile": "gravelly male"      }
]


def _make_mock_config_mgr( pool_csv="maria, mr radio, Rachel, Tiberius, Domi, Arnold", overrides=None ):
    """
    Build a mock ConfigurationManager that returns the configured pool plus
    matching per-persona keys. `overrides` lets a test inject a missing or
    bad value at a specific key.
    """
    overrides = overrides or {}
    mgr = MagicMock()

    persona_table = {
        "maria"    : { "voice id": "v_maria",    "icon": "🌸", "color": "#E91E63", "profile": "warm female"        },
        "mr radio" : { "voice id": "v_mrnpr", "icon": "🦉", "color": "#FFA000", "profile": "authoritative male" },
        "Rachel"  : { "voice id": "v_rachel",  "icon": "🕊️", "color": "#4CAF50", "profile": "calm female"        },
        "Tiberius"    : { "voice id": "v_tiberius",    "icon": "🌑", "color": "#3F51B5", "profile": "deep male"          },
        "Domi"    : { "voice id": "v_domi",    "icon": "⚡", "color": "#C2185B", "profile": "young female"       },
        "Arnold"  : { "voice id": "v_arnold",  "icon": "🪨", "color": "#C62828", "profile": "gravelly male"      }
    }

    def get( key, default=None, silent=False, return_type="string" ):
        if key in overrides:
            return overrides[ key ]
        if key == "cc session voice persona pool":
            return pool_csv
        # Pattern: "cc session voice persona <Name> <field>"
        prefix = "cc session voice persona "
        if key.startswith( prefix ):
            rest = key[ len( prefix ): ]
            for name, fields in persona_table.items():
                if rest.startswith( name + " " ):
                    field = rest[ len( name ) + 1: ]
                    return fields.get( field, default )
        return default

    mgr.get = get
    return mgr


def _write_bridge( sessions_dir, pid, data ):
    path = sessions_dir / f"cc-{pid}.json"
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


def _bridge_with_persona( session_id, persona_name, voice_id="v_maria", borrowed=False ):
    return {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : "/tmp",
        "ppid"              : os.getpid(),  # liveness passes
        "hook_ppid"         : 1,
        "voice_persona"     : {
            "name"     : persona_name,
            "voice_id" : voice_id,
            "icon"     : "🌸",
            "color"    : "#E91E63",
            "borrowed" : borrowed,
            "profile"  : ""
        }
    }


# ── display_name_for ─────────────────────────────────────────────────────────

class TestDisplayNameFor:
    """
    Pool names are stored lowercase no-punctuation per project key convention
    so they double as ConfigParser-safe key fragments. display_name_for
    converts them back to proper-noun form for UI surfaces.
    """

    def test_honorific_mr_gets_period( self ):
        assert display_name_for( "mr radio" ) == "Mr. Radio"

    def test_other_honorifics( self ):
        assert display_name_for( "dr who" )    == "Dr. Who"
        assert display_name_for( "mrs jones" ) == "Mrs. Jones"
        assert display_name_for( "ms smith" )  == "Ms. Smith"
        assert display_name_for( "prof x" )    == "Prof. X"

    def test_already_capitalized_round_trips( self ):
        # "maria" deliberately omitted — it carries a display override (María)
        # that is exercised in test_display_overrides_apply below.
        assert display_name_for( "Rachel" )   == "Rachel"
        assert display_name_for( "Tiberius" ) == "Tiberius"

    def test_display_overrides_apply( self ):
        """
        Personas whose display form carries diacritics or punctuation that
        the lowercase no-punctuation INI key cannot represent are routed
        through _DISPLAY_OVERRIDES. The override is matched case-insensitively
        on the pool key form.
        """
        assert display_name_for( "maria" ) == "María"
        assert display_name_for( "Maria" ) == "María"  # case-insensitive override match

    def test_lowercase_single_token( self ):
        assert display_name_for( "rachel" ) == "Rachel"

    def test_empty_returns_empty( self ):
        assert display_name_for( "" )   == ""
        assert display_name_for( None ) == ""

    def test_collapses_extra_whitespace( self ):
        assert display_name_for( "  mr   radio  " ) == "Mr. Radio"

    def test_honorific_only_when_token_exact( self ):
        # "mri" is not the honorific "mr" — should NOT get a period
        assert display_name_for( "mri scan" ) == "Mri Scan"


# ── load_persona_pool_from_config ────────────────────────────────────────────

class TestLoadPersonaPoolFromConfig:

    def test_loads_full_6_pool( self ):
        mgr = _make_mock_config_mgr()
        pool = load_persona_pool_from_config( mgr )
        assert len( pool ) == 6
        assert [ p[ "name" ] for p in pool ] == [ "maria", "mr radio", "Rachel", "Tiberius", "Domi", "Arnold" ]
        assert pool[ 0 ][ "voice_id" ] == "v_maria"
        assert pool[ 0 ][ "icon" ]     == "🌸"
        assert pool[ 0 ][ "color" ]    == "#E91E63"

    def test_display_name_stamped_on_pool_entries( self ):
        # display_name is stamped at construction so UI surfaces never need to
        # know about the lowercase no-punctuation key convention.
        mgr  = _make_mock_config_mgr()
        pool = load_persona_pool_from_config( mgr )
        by_name = { p[ "name" ]: p[ "display_name" ] for p in pool }
        assert by_name[ "mr radio" ] == "Mr. Radio"
        assert by_name[ "maria" ]    == "María"
        assert by_name[ "Rachel" ]   == "Rachel"
        assert pool[ 0 ][ "profile" ]  == "warm female"

    def test_empty_pool_csv_returns_empty_list( self ):
        mgr = _make_mock_config_mgr( pool_csv="" )
        assert load_persona_pool_from_config( mgr ) == []

    def test_missing_voice_id_skips_entry( self ):
        # Override "cc session voice persona Tiberius voice id" to empty string —
        # Tiberius should be silently skipped, others remain.
        mgr = _make_mock_config_mgr(
            overrides={ "cc session voice persona Tiberius voice id": "" }
        )
        pool  = load_persona_pool_from_config( mgr )
        names = [ p[ "name" ] for p in pool ]
        assert "Tiberius" not in names
        assert len( pool ) == 5

    def test_handles_whitespace_in_csv( self ):
        mgr = _make_mock_config_mgr( pool_csv="  maria ,mr radio  ,, Rachel " )
        pool = load_persona_pool_from_config( mgr )
        # Empty entry between two commas should be filtered out
        assert [ p[ "name" ] for p in pool ] == [ "maria", "mr radio", "Rachel" ]


# ── borrowed_persona_for_sid ─────────────────────────────────────────────────

class TestBorrowedPersonaForSid:

    def test_deterministic_same_sid( self ):
        b1 = borrowed_persona_for_sid( POOL_6, "deterministic-sid-1" )
        b2 = borrowed_persona_for_sid( POOL_6, "deterministic-sid-1" )
        assert b1 == b2
        assert b1[ "borrowed" ] is True

    def test_different_sids_can_pick_different_voices( self ):
        # Across many sids, we should see > 1 distinct name picked.
        # This is probabilistic but ~certain with 100 trials over a 6-element pool.
        names = { borrowed_persona_for_sid( POOL_6, f"sid-{i}" )[ "name" ] for i in range( 100 ) }
        assert len( names ) > 1, "Hash distribution too narrow"

    def test_empty_pool_returns_none( self ):
        assert borrowed_persona_for_sid( [], "sid" ) is None

    def test_empty_sid_returns_none( self ):
        assert borrowed_persona_for_sid( POOL_6, "" ) is None

    def test_borrowed_persona_has_all_fields( self ):
        b = borrowed_persona_for_sid( POOL_6, "sid" )
        assert set( b.keys() ) == { "name", "display_name", "voice_id", "icon", "color", "profile", "borrowed" }
        assert b[ "borrowed" ] is True


# ── pick_unallocated_persona ─────────────────────────────────────────────────

class TestPickUnallocatedPersona:

    def test_empty_pool_returns_none( self ):
        assert pick_unallocated_persona( [], set(), "sid" ) is None

    def test_fully_free_pool_returns_pool_member( self ):
        random.seed( 0 )
        chosen = pick_unallocated_persona( POOL_6, set(), "sid" )
        assert chosen is not None
        assert chosen[ "borrowed" ] is False
        assert chosen[ "name" ] in { p[ "name" ] for p in POOL_6 }

    @pytest.mark.parametrize( "occupied,expected_remaining", [
        ( set(),                                                                                   6 ),
        ( { "maria" },                                                                              5 ),
        ( { "maria", "mr radio" },                                                                   4 ),
        ( { "maria", "mr radio", "Rachel", "Tiberius", "Domi" },                                         1 )
    ] )
    def test_partial_occupancy_picks_from_free_subset( self, occupied, expected_remaining ):
        # Repeat picks to ensure we never pick from `occupied`
        random.seed( 0 )
        for _ in range( 50 ):
            chosen = pick_unallocated_persona( POOL_6, occupied, f"sid-{_}" )
            assert chosen[ "borrowed" ] is False
            assert chosen[ "name" ] not in occupied

    def test_full_occupancy_returns_borrowed( self ):
        all_names = { p[ "name" ] for p in POOL_6 }
        chosen    = pick_unallocated_persona( POOL_6, all_names, "borrow-sid" )
        assert chosen is not None
        assert chosen[ "borrowed" ] is True
        # Borrowed persona is still from the pool
        assert chosen[ "name" ] in all_names

    def test_uniform_distribution_over_many_picks( self ):
        # With 6 free voices and 600 picks, each voice should be picked
        # roughly 100 ± a few standard deviations (~10). Not strict; just
        # guards against a deterministic-first-element regression.
        random.seed( 42 )
        counts = { p[ "name" ]: 0 for p in POOL_6 }
        for _ in range( 600 ):
            chosen = pick_unallocated_persona( POOL_6, set(), "sid" )
            counts[ chosen[ "name" ] ] += 1
        # No single voice should have <30 or >170 — far from uniform tail
        assert all( 30 <= c <= 170 for c in counts.values() ), f"Distribution skewed: {counts}"


# ── Bridge integration: find_active_voice_persona_sessions ───────────────────

class TestFindActiveVoicePersonaSessions:

    def test_returns_only_bridges_with_persona( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # Bridge with persona
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "abc12345-aaaa-bbbb-cccc-dddddddddddd", "maria" ) )
            # Bridge without persona
            data_no_persona = {
                "session_id"        : "xyz98765-aaaa-bbbb-cccc-dddddddddddd",
                "stable_session_id" : "xyz98765-aaaa-bbbb-cccc-dddddddddddd",
                "cwd"               : "/tmp",
                "ppid"              : os.getpid(),
                "hook_ppid"         : 1
            }
            _write_bridge( sessions_dir, os.getpid() + 1, data_no_persona )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_voice_persona_sessions()

            assert len( results ) == 1
            _, sid, p = results[ 0 ]
            assert p[ "name" ] == "maria"
            assert sid.startswith( "abc12345" )

    def test_skips_dead_pid_bridges( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # Use PID 999999 (presumably not alive)
            _write_bridge( sessions_dir, 999999,
                           _bridge_with_persona( "deadpid1-aaaa-bbbb-cccc-dddddddddddd", "Tiberius" ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                with patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                            return_value=True ):
                    results = find_active_voice_persona_sessions()

            assert results == []

    def test_skips_malformed_bridge( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # Write malformed JSON
            ( sessions_dir / f"cc-{os.getpid()}.json" ).write_text( "{not valid json" )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_voice_persona_sessions()

            assert results == []


# ── allocate_persona_for_session (end-to-end composition) ────────────────────

class TestAllocatePersonaForSession:

    def test_picks_unallocated_when_pool_partially_occupied( self ):
        """
        Two bridges already hold maria and Tiberius. allocate_persona_for_session
        must pick from the remaining 4 voices.
        """
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "aaaa1111-aaaa-bbbb-cccc-dddddddddddd", "maria" ) )
            _write_bridge( sessions_dir, os.getpid() + 1,
                           _bridge_with_persona( "bbbb2222-aaaa-bbbb-cccc-dddddddddddd", "Tiberius" ) )

            mgr = _make_mock_config_mgr()
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                random.seed( 7 )
                allocated = allocate_persona_for_session( mgr, "newsid12-aaaa-bbbb-cccc-dddddddddddd" )

            assert allocated is not None
            assert allocated[ "name" ] not in { "maria", "Tiberius" }
            assert allocated[ "borrowed" ] is False
            assert "assigned_at" in allocated
            assert allocated[ "assigned_at" ].endswith( "+00:00" )

    def test_returns_none_when_pool_empty( self ):
        mgr = _make_mock_config_mgr( pool_csv="" )
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = allocate_persona_for_session( mgr, "sid" )
            assert result is None

    def test_borrows_when_pool_fully_occupied( self ):
        """Occupy all 6 names, then allocate_persona_for_session must borrow."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            for i, name in enumerate( [ "maria", "mr radio", "Rachel", "Tiberius", "Domi", "Arnold" ] ):
                _write_bridge(
                    sessions_dir,
                    os.getpid() + i,
                    _bridge_with_persona( f"sid{i}aaa-aaaa-bbbb-cccc-dddddddddddd", name )
                )

            mgr = _make_mock_config_mgr()
            # Disable host-PID trust so all bridges count even though only
            # one of those PIDs is actually alive (this test process).
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                result = allocate_persona_for_session( mgr, "newsid12-aaaa-bbbb-cccc-dddddddddddd" )

            assert result is not None
            assert result[ "borrowed" ] is True
            # Borrowed name is still in the pool
            assert result[ "name" ] in { "maria", "mr radio", "Rachel", "Tiberius", "Domi", "Arnold" }


# ── Bridge round-trip (get/set_voice_persona) ────────────────────────────────

class TestBridgeRoundTrip:

    def test_get_set_round_trip( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "abc12345-aaaa-bbbb-cccc-dddddddddddd"
            _write_bridge( sessions_dir, os.getpid(),
                           { "session_id": sid, "stable_session_id": sid, "cwd": "/tmp" } )

            persona = { "name": "Tiberius", "voice_id": "v_tiberius", "icon": "🌑",
                        "color": "#3F51B5", "borrowed": False, "profile": "deep male" }

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert get_voice_persona( sid ) is None
                assert set_voice_persona( sid, persona ) is True
                assert get_voice_persona( sid ) == persona
                # Clear with None
                assert set_voice_persona( sid, None ) is True
                assert get_voice_persona( sid ) is None

    def test_get_returns_none_on_missing_bridge( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert get_voice_persona( "doesnotexist" ) is None
                assert set_voice_persona( "doesnotexist", { "name": "X" } ) is False
