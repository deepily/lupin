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
import time
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
    load_overflow_persona_from_config,
    display_name_for,
    _lowest_free_extra_n,
    _make_extra_persona,
    quick_smoke_test
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_voice_persona, set_voice_persona, find_active_voice_persona_sessions,
    find_active_sessions,
    find_session_path_by_id, prune_dead_persona_bridges
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

POOL_6 = [
    { "name": "maria",    "voice_id": "v_maria",    "icon": "🌸", "color": "#E91E63", "profile": "warm female"        },
    { "name": "mr radio", "voice_id": "v_mrnpr", "icon": "🦉", "color": "#FFA000", "profile": "authoritative male" },
    { "name": "Rachel",  "voice_id": "v_rachel",  "icon": "🕊️", "color": "#4CAF50", "profile": "calm female"        },
    { "name": "Tiberius",    "voice_id": "v_tiberius",    "icon": "🌑", "color": "#3F51B5", "profile": "deep male"          },
    { "name": "Rio",    "voice_id": "v_domi",    "icon": "⚡", "color": "#C2185B", "profile": "young female"       },
    { "name": "Arnold",  "voice_id": "v_arnold",  "icon": "🪨", "color": "#C62828", "profile": "gravelly male"      }
]


def _make_mock_config_mgr( pool_csv="maria, mr radio, Rachel, Tiberius, Rio, Arnold", overrides=None ):
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
        "Rio"    : { "voice id": "v_domi",    "icon": "⚡", "color": "#C2185B", "profile": "young female"       },
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
        "cc_pid"            : os.getpid(),  # liveness passes
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
        assert [ p[ "name" ] for p in pool ] == [ "maria", "mr radio", "Rachel", "Tiberius", "Rio", "Arnold" ]
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
        ( { "maria", "mr radio", "Rachel", "Tiberius", "Rio" },                                         1 )
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
                "cc_pid"            : os.getpid(),
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


# ── find_active_sessions: persona-optional discovery (bug d57dbfea) ───────────

def _bridge_without_persona( session_id, pid=None ):
    """A live bridge for a worker that booted with NO voice_persona."""
    return {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : "/tmp",
        "cc_pid"            : pid if pid is not None else os.getpid(),
        "hook_ppid"         : 1,
    }


class TestFindActiveSessions:
    """`find_active_sessions( require_persona=... )` — the general scanner that
    makes null-persona workers discoverable for inbound DM resolution."""

    def test_require_persona_false_includes_null_persona( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "named001-aaaa-bbbb-cccc-dddddddddddd", "maria" ) )
            _write_bridge( sessions_dir, os.getpid() + 1,
                           _bridge_without_persona( "nullp001-aaaa-bbbb-cccc-dddddddddddd",
                                                    pid=os.getpid() + 1 ) )

            # Bypass the host-PID liveness check (its pid+1 liveness is racy) so the
            # null-persona bridge deterministically reaches the persona filter.
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                results = find_active_sessions( require_persona=False )

            by_sid = { sid: persona for _p, sid, persona in results }
            assert any( s.startswith( "named001" ) for s in by_sid )
            assert any( s.startswith( "nullp001" ) for s in by_sid )
            # null-persona session projected to {} (never None) so downstream
            # `p.get(...)` consumers stay safe.
            null_sid    = next( s for s in by_sid if s.startswith( "nullp001" ) )
            assert by_sid[ null_sid ] == {}

    def test_require_persona_true_excludes_null_persona( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "named001-aaaa-bbbb-cccc-dddddddddddd", "maria" ) )
            _write_bridge( sessions_dir, os.getpid() + 1,
                           _bridge_without_persona( "nullp001-aaaa-bbbb-cccc-dddddddddddd",
                                                    pid=os.getpid() + 1 ) )

            # trust=False → the null bridge reaches the persona filter and is
            # excluded THERE (not by the racy pid check), exercising the
            # `require_persona and not has_persona` continue branch deterministically.
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                results = find_active_sessions( require_persona=True )

            sids = [ sid for _p, sid, _persona in results ]
            assert any( s.startswith( "named001" ) for s in sids )
            assert not any( s.startswith( "nullp001" ) for s in sids )

    def test_delegate_equals_require_persona_true( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "named001-aaaa-bbbb-cccc-dddddddddddd", "maria" ) )
            _write_bridge( sessions_dir, os.getpid() + 1,
                           _bridge_without_persona( "nullp001-aaaa-bbbb-cccc-dddddddddddd",
                                                    pid=os.getpid() + 1 ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                delegated = find_active_voice_persona_sessions()
                direct    = find_active_sessions( require_persona=True )

            assert [ ( s, p ) for _pa, s, p in delegated ] == [ ( s, p ) for _pa, s, p in direct ]

    def test_skips_bridge_without_session_id( self ):
        # persona-less AND id-less → reaches the `if not sid` guard and is skipped.
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = { "cwd": "/tmp", "cc_pid": os.getpid(), "hook_ppid": 1 }  # no (stable_)session_id
            _write_bridge( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_sessions( require_persona=False )

            assert results == []

    def test_returns_empty_when_session_dir_missing( self ):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path( tmp ) / "does-not-exist"
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", missing ):
                assert find_active_sessions( require_persona=False ) == []

    def test_skips_buffer_and_listener_files( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            ( sessions_dir / f"cc-{os.getpid()}-buffer.json" ).write_text(
                json.dumps( _bridge_without_persona( "buf00001-aaaa-bbbb-cccc-dddddddddddd" ) )
            )
            ( sessions_dir / f"cc-{os.getpid()}-listener.json" ).write_text(
                json.dumps( _bridge_without_persona( "lis00001-aaaa-bbbb-cccc-dddddddddddd" ) )
            )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_sessions( require_persona=False )

            assert results == []

    def test_skips_stale_mtime( self ):
        """
        AMENDED for bug 6afc8b3e: the TTL filters a stale bridge only when liveness
        CANNOT be confirmed. This used to write the bridge under os.getpid() — a
        process that is alive by definition — and assert it was filtered, which is
        exactly the defect Rio measured: two running seats invisible for 14h+.
        Container context makes the TTL the deciding signal again, which is the
        behaviour this test was actually protecting.
        """
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_bridge( sessions_dir, os.getpid(),
                                  _bridge_without_persona( "stale001-aaaa-bbbb-cccc-dddddddddddd" ) )
            old = time.time() - 100_000   # well past the 10s threshold below
            os.utime( path, ( old, old ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                results = find_active_sessions( stale_threshold_seconds=10, require_persona=False )

            assert results == []

    def test_stale_mtime_is_KEPT_when_the_process_is_alive( self ):
        """The other half of 6afc8b3e: on the host, a live PID outranks the TTL."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_bridge( sessions_dir, os.getpid(),
                                  _bridge_without_persona( "alive001-aaaa-bbbb-cccc-dddddddddddd" ) )
            old = time.time() - 100_000
            os.utime( path, ( old, old ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                results = find_active_sessions( stale_threshold_seconds=10, require_persona=False )

            assert len( results ) == 1, "a running process must not vanish because its bridge aged"

    def test_skips_dead_pid( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, 999999,
                           _bridge_without_persona( "deadpid0-aaaa-bbbb-cccc-dddddddddddd", pid=999999 ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                results = find_active_sessions( require_persona=False )

            assert results == []

    def test_skips_malformed_json( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            ( sessions_dir / f"cc-{os.getpid()}.json" ).write_text( "{not valid json" )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_sessions( require_persona=False )

            assert results == []

    def test_skips_on_stat_oserror( self ):
        # A dangling symlink: glob finds it, but path.stat() raises OSError →
        # covers the mtime `except OSError: continue` branch.
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            link = sessions_dir / f"cc-{os.getpid()}.json"
            os.symlink( str( sessions_dir / "nonexistent-target.json" ), str( link ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_sessions( require_persona=False )

            assert results == []


# ── allocate_persona_for_session (end-to-end composition) ────────────────────

class TestAllocatePersonaForSession:

    @pytest.fixture( autouse=True )
    def _trust_synthetic_pids( self ):
        """
        Tests below write bridge files keyed by `os.getpid() + N`. Those PIDs
        are NOT guaranteed live on Linux (allocation isn't sequential), so on
        host-side runs `find_active_voice_persona_sessions` would skip the
        synthetic-PID bridges as dead and undercount the occupied set —
        defeating the test premise. Patching `_can_trust_host_pids` to False
        bypasses the alive-PID filter, mirroring the in-container path.
        """
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                    return_value=False ):
            yield

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
            for i, name in enumerate( [ "maria", "mr radio", "Rachel", "Tiberius", "Rio", "Arnold" ] ):
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
            assert result[ "name" ] in { "maria", "mr radio", "Rachel", "Tiberius", "Rio", "Arnold" }


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


# ── load_overflow_persona_from_config (Sam) ──────────────────────────────────

class TestLoadOverflowPersonaFromConfig:
    """
    Sam is the system-default voice AND the pool-exhaustion overflow persona.
    Voice_id is read from `elevenlabs tts default voice id` (single source of
    truth); icon/color/profile/display_name read from `cc session voice persona
    sam *` keys with documented defaults.
    """

    def test_returns_none_when_voice_id_missing( self ):
        mgr = MagicMock()
        mgr.get = lambda key, default=None, silent=False, return_type="string": (
            "" if key == "elevenlabs tts default voice id" else default
        )
        assert load_overflow_persona_from_config( mgr ) is None

    def test_returns_sam_with_overflow_flag( self ):
        mgr = MagicMock()
        config_values = {
            "elevenlabs tts default voice id"            : "G7ILShrCNLfmS0A37SXS",
            "cc session voice persona sam icon"          : "🎙️",
            "cc session voice persona sam color"         : "#00BCD4",
            "cc session voice persona sam profile"       : "System default voice (overflow)",
            "cc session voice persona sam display name"  : "Sam"
        }
        mgr.get = lambda key, default=None, silent=False, return_type="string": (
            config_values.get( key, default )
        )
        sam = load_overflow_persona_from_config( mgr )
        assert sam is not None
        assert sam[ "name" ]         == "sam"
        assert sam[ "display_name" ] == "Sam"
        assert sam[ "voice_id" ]     == "G7ILShrCNLfmS0A37SXS"
        assert sam[ "overflow" ]     is True

    def test_falls_back_to_defaults_when_optional_keys_missing( self ):
        # Only voice_id is required — others default to documented values
        mgr = MagicMock()
        mgr.get = lambda key, default=None, silent=False, return_type="string": (
            "v_sam" if key == "elevenlabs tts default voice id" else default
        )
        sam = load_overflow_persona_from_config( mgr )
        assert sam is not None
        assert sam[ "voice_id" ]     == "v_sam"
        assert sam[ "display_name" ] == "Sam"
        assert sam[ "icon" ]         == "🎙️"
        assert sam[ "color" ]        == "#00BCD4"
        assert sam[ "overflow" ]     is True

    def test_returns_none_when_overflow_name_blank( self ):
        # Setting `overflow name` to whitespace disables the overflow slot.
        mgr = MagicMock()
        mgr.get = lambda key, default=None, silent=False, return_type="string": (
            "   " if key == "cc session voice persona overflow name" else default
        )
        assert load_overflow_persona_from_config( mgr ) is None


# ── pick_unallocated_persona with overflow=Sam ───────────────────────────────

class TestPickUnallocatedPersonaOverflow:
    """
    With the Sam-overflow feature, pool-exhausted allocations should return Sam
    (overflow=True, borrowed=False) instead of the legacy hash-borrow path. The
    legacy borrow remains as a defensive fallback only when overflow_persona is
    None (e.g., Sam misconfigured).
    """

    SAM = {
        "name"         : "sam",
        "display_name" : "Sam",
        "voice_id"     : "v_sam",
        "icon"         : "🎙️",
        "color"        : "#00BCD4",
        "profile"      : "System default voice (overflow)",
        "overflow"     : True
    }

    def test_overflow_returns_sam_when_pool_exhausted( self ):
        all_names = { p[ "name" ] for p in POOL_6 }
        chosen    = pick_unallocated_persona( POOL_6, all_names, "sid", overflow_persona=self.SAM )
        assert chosen is not None
        assert chosen[ "name" ]     == "sam"
        assert chosen[ "overflow" ] is True
        assert chosen[ "borrowed" ] is False  # always set when allocating

    def test_overflow_not_used_when_pool_has_free_slots( self ):
        chosen = pick_unallocated_persona( POOL_6, { "maria" }, "sid", overflow_persona=self.SAM )
        assert chosen is not None
        assert chosen[ "name" ] != "sam", "Pool has 5 free slots — Sam must NOT be picked"
        assert chosen[ "borrowed" ] is False
        # overflow flag is False or absent on regular pool picks
        assert chosen.get( "overflow", False ) is False

    def test_first_overflow_verbatim_then_extra_n( self ):
        # Option A (2026-05-28): the FIRST overflow (overflow name not yet
        # occupied) gets Sam verbatim; once Sam is occupied, subsequent
        # concurrent overflows spill to numbered Extra-N identities. Simulate
        # the bridge recording each prior allocation by growing occupied_names.
        all_names = { p[ "name" ] for p in POOL_6 }

        first = pick_unallocated_persona( POOL_6, all_names, "sid-0", overflow_persona=self.SAM )
        assert first[ "name" ] == "sam" and first[ "overflow" ] is True

        occupied = all_names | { "sam" }
        second   = pick_unallocated_persona( POOL_6, occupied, "sid-1", overflow_persona=self.SAM )
        assert second[ "name" ]     == "extra 1"
        assert second[ "voice_id" ] == self.SAM[ "voice_id" ]   # shares Sam's voice
        assert second[ "overflow" ] is True

        occupied |= { "extra 1" }
        third     = pick_unallocated_persona( POOL_6, occupied, "sid-2", overflow_persona=self.SAM )
        assert third[ "name" ] == "extra 2"

    def test_overflow_none_falls_back_to_legacy_borrow( self ):
        # When Sam is unconfigured, the legacy hash-borrow path still works.
        all_names = { p[ "name" ] for p in POOL_6 }
        chosen    = pick_unallocated_persona( POOL_6, all_names, "sid", overflow_persona=None )
        assert chosen is not None
        assert chosen[ "borrowed" ] is True
        assert chosen.get( "overflow", False ) is False
        assert chosen[ "name" ] in all_names

    def test_overflow_copy_is_independent( self ):
        # Mutating the returned persona must not poison the source overflow dict
        original_overflow = dict( self.SAM )
        all_names         = { p[ "name" ] for p in POOL_6 }
        chosen            = pick_unallocated_persona( POOL_6, all_names, "sid", overflow_persona=self.SAM )
        chosen[ "polluted" ] = True
        assert "polluted" not in self.SAM, "Overflow source dict was mutated by caller"
        assert self.SAM == original_overflow


# ── Extra-N overflow identities (Option A, 2026-05-28) ───────────────────────

class TestLowestFreeExtraN:
    """
    _lowest_free_extra_n picks the smallest N≥1 whose "extra N" name is unused,
    reusing gaps so a dead Extra session's number is reclaimed.
    """

    def test_empty_returns_one( self ):
        assert _lowest_free_extra_n( set() ) == 1

    def test_skips_occupied_low( self ):
        assert _lowest_free_extra_n( { "extra 1" } )            == 2
        assert _lowest_free_extra_n( { "extra 1", "extra 2" } ) == 3

    def test_reuses_gap( self ):
        # extra 1 free though extra 2 taken → reuse 1, do not skip to 3
        assert _lowest_free_extra_n( { "extra 2" } )                       == 1
        assert _lowest_free_extra_n( { "extra 2", "extra 3" } )            == 1
        assert _lowest_free_extra_n( { "arnold", "extra 1", "extra 3" } )  == 2

    def test_ignores_non_extra_names( self ):
        assert _lowest_free_extra_n( { "maria", "arnold", "Tiberius" } ) == 1


class TestMakeExtraPersona:
    """
    _make_extra_persona builds a uniquified Extra-N dict that shares the base
    overflow voice/icon but carries a distinct name/display_name/color.
    """

    BASE = {
        "name"     : "arnold",
        "voice_id" : "v_arnold",
        "icon"     : "🪨",
        "color"    : "#FFD600",
        "profile"  : "gravelly male",
        "overflow" : True
    }
    PALETTE = [ "#4527A0", "#6A1B9A", "#9C27B0" ]

    def test_shape_and_shared_voice_icon( self ):
        e = _make_extra_persona( self.BASE, 1, self.PALETTE )
        assert e[ "name" ]         == "extra 1"
        assert e[ "display_name" ] == "Extra 1"
        assert e[ "voice_id" ]     == "v_arnold"   # shared voice
        assert e[ "icon" ]         == "🪨"          # shared icon
        assert e[ "color" ]        == "#4527A0"     # palette[0]
        assert e[ "overflow" ]     is True
        assert e[ "borrowed" ]     is False

    def test_color_cycles_modulo_palette( self ):
        # n=4 with a 3-color palette → index (4-1)%3 = 0
        assert _make_extra_persona( self.BASE, 4, self.PALETTE )[ "color" ] == "#4527A0"
        assert _make_extra_persona( self.BASE, 5, self.PALETTE )[ "color" ] == "#6A1B9A"

    def test_empty_palette_inherits_base_color( self ):
        assert _make_extra_persona( self.BASE, 1, None )[ "color" ]  == "#FFD600"
        assert _make_extra_persona( self.BASE, 2, [] )[ "color" ]    == "#FFD600"

    def test_does_not_alias_base( self ):
        e = _make_extra_persona( self.BASE, 1, self.PALETTE )
        e[ "polluted" ] = True
        assert "polluted" not in self.BASE


class TestPickUnallocatedPersonaExtraN:
    """
    End-to-end pick semantics for Option A: pool exhausted →
    Arnold-verbatim-first, then numbered Extras sharing Arnold's voice.
    """

    ARNOLD = {
        "name"     : "arnold",
        "display_name" : "Arnold",
        "voice_id" : "v_arnold",
        "icon"     : "🪨",
        "color"    : "#FFD600",
        "profile"  : "gravelly male",
        "overflow" : True
    }
    PALETTE = [ "#4527A0", "#6A1B9A", "#9C27B0" ]

    def _full( self ):
        return { p[ "name" ] for p in POOL_6 }

    def test_arnold_verbatim_when_free( self ):
        chosen = pick_unallocated_persona( POOL_6, self._full(), "sid",
                                           overflow_persona=self.ARNOLD, extra_colors=self.PALETTE )
        assert chosen[ "name" ] == "arnold" and chosen[ "borrowed" ] is False

    def test_extra_1_when_arnold_occupied( self ):
        occupied = self._full() | { "arnold" }
        chosen   = pick_unallocated_persona( POOL_6, occupied, "sid",
                                             overflow_persona=self.ARNOLD, extra_colors=self.PALETTE )
        assert chosen[ "name" ]     == "extra 1"
        assert chosen[ "color" ]    == "#4527A0"
        assert chosen[ "voice_id" ] == "v_arnold"
        assert chosen[ "overflow" ] is True

    def test_extra_2_when_arnold_and_extra_1_occupied( self ):
        occupied = self._full() | { "arnold", "extra 1" }
        chosen   = pick_unallocated_persona( POOL_6, occupied, "sid",
                                             overflow_persona=self.ARNOLD, extra_colors=self.PALETTE )
        assert chosen[ "name" ] == "extra 2" and chosen[ "color" ] == "#6A1B9A"

    def test_gap_reuse( self ):
        # arnold + extra 2 occupied, extra 1 free → extra 1
        occupied = self._full() | { "arnold", "extra 2" }
        chosen   = pick_unallocated_persona( POOL_6, occupied, "sid",
                                             overflow_persona=self.ARNOLD, extra_colors=self.PALETTE )
        assert chosen[ "name" ] == "extra 1"

    def test_empty_palette_extra_inherits_arnold_color( self ):
        occupied = self._full() | { "arnold" }
        chosen   = pick_unallocated_persona( POOL_6, occupied, "sid",
                                             overflow_persona=self.ARNOLD, extra_colors=None )
        assert chosen[ "name" ] == "extra 1" and chosen[ "color" ] == self.ARNOLD[ "color" ]


class TestExtraColorsGreenRule:
    """
    Codifies feedback_no_green_in_persona_pool for the shipped Extra-N palette:
    every color must have green RGB < 30% AND green not in the top two channels.
    """

    # Must stay in lockstep with `cc session voice persona extra colors` in
    # lupin-app.ini. If you change the shipped palette, change it here too.
    SHIPPED_PALETTE = [ "#4527A0", "#6A1B9A", "#9C27B0", "#AD1457", "#C2185B", "#7B1FA2" ]

    @staticmethod
    def _rgb( hex_color ):
        h = hex_color.lstrip( "#" )
        return int( h[0:2], 16 ), int( h[2:4], 16 ), int( h[4:6], 16 )

    def test_every_color_satisfies_green_rule( self ):
        for hex_color in self.SHIPPED_PALETTE:
            r, g, b = self._rgb( hex_color )
            assert g / 255.0 < 0.30, f"{hex_color}: green {g} ≥ 30% of 255"
            # green must be STRICTLY the lowest channel → never in the top two
            assert g < r and g < b, \
                f"{hex_color}: green {g} is not strictly lowest (r={r}, g={g}, b={b})"


class TestModuleSmoke:
    """Exercises the module's inline quick_smoke_test() body under pytest."""

    def test_quick_smoke_test_runs_clean( self ):
        # Self-contained: asserts internally, reseeds random, prints progress.
        quick_smoke_test()


# ── allocate_persona_for_session — Extra-N end-to-end ────────────────────────

class TestAllocatePersonaExtraN:
    """
    Full composition through allocate_persona_for_session: pool + overflow
    (arnold) all occupied via bridges → an Extra-N persona is returned, with
    the palette color read from config and `assigned_at` stamped.
    """

    def _mock_mgr_with_overflow( self ):
        mgr = MagicMock()
        config_values = {
            "cc session voice persona pool"            : "maria, mr radio, Rachel, Tiberius, Rio",
            "cc session voice persona overflow name"   : "arnold",
            "cc session voice persona arnold voice id" : "v_arnold",
            "cc session voice persona arnold icon"     : "🪨",
            "cc session voice persona arnold color"    : "#FFD600",
            "cc session voice persona arnold profile"  : "gravelly male",
            "cc session voice persona extra colors"    : "#4527A0, #6A1B9A, #9C27B0",
            "cc session voice persona maria voice id"    : "v_maria",
            "cc session voice persona mr radio voice id" : "v_mrnpr",
            "cc session voice persona Rachel voice id"   : "v_rachel",
            "cc session voice persona Tiberius voice id" : "v_tiberius",
            "cc session voice persona Rio voice id"      : "v_domi",
        }
        def get( key, default=None, silent=False, return_type="string" ):
            if key in config_values:
                return config_values[ key ]
            return default
        mgr.get = get
        return mgr

    def test_extra_n_allocated_end_to_end( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # Occupy the 5-name pool + arnold + extra 1 → next free is extra 2
            for i, name in enumerate( [ "maria", "mr radio", "Rachel", "Tiberius", "Rio", "arnold", "extra 1" ] ):
                _write_bridge(
                    sessions_dir, os.getpid() + i,
                    _bridge_with_persona( f"sid{i}aaa-aaaa-bbbb-cccc-dddddddddddd", name )
                )
            mgr = self._mock_mgr_with_overflow()
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                result = allocate_persona_for_session( mgr, "newsid12-aaaa-bbbb-cccc-dddddddddddd" )

            assert result is not None
            assert result[ "name" ]     == "extra 2"
            assert result[ "color" ]    == "#6A1B9A"      # palette[1], read from config
            assert result[ "voice_id" ] == "v_arnold"     # shares Arnold's voice
            assert result[ "overflow" ] is True
            assert "assigned_at" in result and result[ "assigned_at" ].endswith( "+00:00" )


# ── find_active_voice_persona_sessions — mtime TTL guard ─────────────────────

class TestFindActiveVoicePersonaSessionsTTL:
    """
    The mtime TTL treats aged-out bridges as free — but ONLY where liveness cannot
    be confirmed.

    ⚠️ AMENDED by bug 6afc8b3e. This class used to open "the mtime TTL guard fires
    regardless of host-vs-container context", and its stale-bridge cases wrote the
    bridge under os.getpid() — a live process — then asserted it was filtered. That
    is the defect, not the contract: Rio measured two RUNNING seats absent from every
    roster for 14h+ because their bridges had not been rewritten. PID liveness now
    outranks the TTL, so the stale-filtering cases run in CONTAINER context, where
    host PIDs are invisible and the TTL is genuinely the only signal left.

    See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md
    """

    def test_fresh_bridge_returned_under_default_ttl( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "fresh111-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_voice_persona_sessions()
            assert len( results ) == 1

    def test_stale_mtime_bridge_filtered_under_default_ttl( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_bridge( sessions_dir, os.getpid(),
                                  _bridge_with_persona( "stale111-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            # Push mtime back 50000 seconds (~14h, > 12h default)
            old_time = time.time() - 50000
            os.utime( path, ( old_time, old_time ) )
            # Container context: host PIDs invisible, so the TTL is the only signal.
            # On the host this same bridge is now KEPT — see the sibling test below.
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                results = find_active_voice_persona_sessions()
            assert results == [], "Stale-mtime bridge must be filtered when liveness is unknowable"

    def test_stale_mtime_named_seat_is_KEPT_on_the_host( self ):
        """
        Bug 6afc8b3e: the mtime filter ran BEFORE the persona branch, so a NAMED seat
        with a stale bridge disappeared identically to a nameless one. Its persona slot
        was then reclaimable while the session still held the voice.
        """
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_bridge( sessions_dir, os.getpid(),
                                  _bridge_with_persona( "stale333-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            old_time = time.time() - 50000
            os.utime( path, ( old_time, old_time ) )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                results = find_active_voice_persona_sessions()
            assert len( results ) == 1, "a live named seat must keep its persona slot"

    def test_caller_can_widen_ttl( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_bridge( sessions_dir, os.getpid(),
                                  _bridge_with_persona( "stale222-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            old_time = time.time() - 50000
            os.utime( path, ( old_time, old_time ) )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                results = find_active_voice_persona_sessions( stale_threshold_seconds=10**9 )
            assert len( results ) == 1, "Massive TTL must keep mtime-old bridge"

    def test_caller_can_tighten_ttl( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            path = _write_bridge( sessions_dir, os.getpid(),
                                  _bridge_with_persona( "fresh222-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            # Push 60s into the past (older than tight 30s TTL)
            old_time = time.time() - 60
            os.utime( path, ( old_time, old_time ) )
            # Container context — a tightened TTL still bites where liveness is
            # unknowable. On the host a live PID outranks any TTL, however tight.
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                results = find_active_voice_persona_sessions( stale_threshold_seconds=30 )
            assert results == [], "Tight TTL must filter the 60s-old bridge"


# ── prune_dead_persona_bridges (host-side housekeeper) ───────────────────────

class TestPruneDeadPersonaBridges:
    """
    Host-side prune helper runs at SessionStart. Nullifies voice_persona on
    bridges whose host PID is dead. Short-circuits to no-op inside a container.

    See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md
    """

    def test_no_op_in_container_context( self ):
        # Inside a container, _can_trust_host_pids() is False → every PID
        # would naively read as dead, so prune correctly does nothing.
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, 999999,
                           _bridge_with_persona( "dead-pid-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=False ):
                pruned = prune_dead_persona_bridges()
            assert pruned == 0
            # Bridge data untouched — voice_persona still attached
            data = json.loads( ( sessions_dir / "cc-999999.json" ).read_text() )
            assert isinstance( data[ "voice_persona" ], dict )

    def test_nullifies_dead_pid_bridge_persona( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            _write_bridge( sessions_dir, 999999,
                           _bridge_with_persona( "dead-pid-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                pruned = prune_dead_persona_bridges()
            assert pruned == 1
            data = json.loads( ( sessions_dir / "cc-999999.json" ).read_text() )
            assert data[ "voice_persona" ] is None, "Dead-PID bridge's persona should be nulled"

    def test_preserves_alive_pid_bridge_persona( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # os.getpid() is alive (this test process)
            _write_bridge( sessions_dir, os.getpid(),
                           _bridge_with_persona( "alive-pid-aaaa-bbbb-cccc-dddddddddddd", "Rio" ) )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                pruned = prune_dead_persona_bridges()
            assert pruned == 0
            data = json.loads( ( sessions_dir / f"cc-{os.getpid()}.json" ).read_text() )
            assert isinstance( data[ "voice_persona" ], dict )
            assert data[ "voice_persona" ][ "name" ] == "Rio"

    def test_skips_bridges_with_no_persona( self ):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # Bridge with persona=None on a dead PID
            data_no_persona = {
                "session_id"        : "xyz98765-aaaa-bbbb-cccc-dddddddddddd",
                "stable_session_id" : "xyz98765-aaaa-bbbb-cccc-dddddddddddd",
                "cwd"               : "/tmp",
                "voice_persona"     : None
            }
            _write_bridge( sessions_dir, 999999, data_no_persona )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                pruned = prune_dead_persona_bridges()
            assert pruned == 0, "Bridges without persona shouldn't be counted"

    def test_returns_zero_when_session_dir_missing( self ):
        nonexistent = Path( "/tmp/__nonexistent_session_dir_for_test__" )
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", nonexistent ):
            assert prune_dead_persona_bridges() == 0

    def test_skips_buffer_and_listener_files( self ):
        # Same convention as find_active_voice_persona_sessions — skip
        # auxiliary cc-*-buffer.json and cc-*-listener.json files
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            ( sessions_dir / "cc-999999-buffer.json"   ).write_text( "{}" )
            ( sessions_dir / "cc-999999-listener.json" ).write_text( "{}" )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._can_trust_host_pids",
                        return_value=True ):
                pruned = prune_dead_persona_bridges()
            assert pruned == 0
