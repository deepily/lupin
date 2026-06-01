"""
Unit tests for voice persona allocation helpers (cosa.rest.voice_persona_helpers).

Covers display_name_for, load_persona_pool_from_config, load_overflow_persona_from_config,
_lowest_free_extra_n, _make_extra_persona, borrowed_persona_for_sid,
pick_unallocated_persona (free / Arnold-overflow / Extra-N / legacy-borrow / empty),
allocate_persona_for_session, _find_persona_in_pool, pick_requested_persona,
allocate_requested_persona_for_session, and pick_preferred_persona_from_env — to
genuine 100% line + branch + function.

config_mgr is a dict-backed stand-in; session_bridge.find_active_voice_persona_sessions
and random.choice are patched. ZERO config-file / bridge-file / env mutation leaks.
"""

import unittest
from unittest.mock import patch

from cosa.rest import voice_persona_helpers as vph
from cosa.rest.voice_persona_helpers import (
    display_name_for,
    load_persona_pool_from_config,
    load_overflow_persona_from_config,
    _lowest_free_extra_n,
    _make_extra_persona,
    borrowed_persona_for_sid,
    pick_unallocated_persona,
    allocate_persona_for_session,
    _find_persona_in_pool,
    pick_requested_persona,
    allocate_requested_persona_for_session,
    pick_preferred_persona_from_env,
)


class _MockConfig:
    """Dict-backed ConfigurationManager stand-in honoring default + return_type."""
    def __init__( self, values=None ):
        self.values = values or {}

    def get( self, key, default=None, return_type=None, silent=False ):
        v = self.values.get( key, default )
        if return_type == "int" and v is not None:
            return int( v )
        return v


class TestDisplayNameFor( unittest.TestCase ):
    def test_empty_returns_empty( self ):
        self.assertEqual( display_name_for( "" ), "" )

    def test_override_diacritics( self ):
        self.assertEqual( display_name_for( "maria" ), "María" )

    def test_honorific_token_gets_period( self ):
        self.assertEqual( display_name_for( "mr radio" ), "Mr. Radio" )
        self.assertEqual( display_name_for( "dr who" ), "Dr. Who" )

    def test_plain_token_capitalized( self ):
        self.assertEqual( display_name_for( "rachel" ), "Rachel" )

    def test_multi_token_collapses_whitespace( self ):
        self.assertEqual( display_name_for( "wise   penguin" ), "Wise Penguin" )


class TestLoadPersonaPoolFromConfig( unittest.TestCase ):
    def test_empty_pool_key_returns_empty( self ):
        self.assertEqual( load_persona_pool_from_config( _MockConfig() ), [] )

    def test_builds_pool_in_order_and_skips_missing_voice_id( self ):
        cfg = _MockConfig( {
            "cc session voice persona pool"            : "nora, quentin, ghost",
            "cc session voice persona nora voice id"   : "v-nora",
            "cc session voice persona nora icon"       : "🌸",
            "cc session voice persona nora color"      : "#E91E63",
            "cc session voice persona nora profile"    : "calm",
            "cc session voice persona quentin voice id": "v-quentin",
            # 'ghost' has NO voice id → skipped
        } )
        pool = load_persona_pool_from_config( cfg )
        names = [ p[ "name" ] for p in pool ]
        self.assertEqual( names, [ "nora", "quentin" ] )   # ghost skipped, order preserved
        self.assertEqual( pool[ 0 ][ "voice_id" ], "v-nora" )
        self.assertEqual( pool[ 0 ][ "display_name" ], "Nora" )
        # quentin falls back to default icon/color/profile
        self.assertEqual( pool[ 1 ][ "icon" ], "🎙️" )
        self.assertEqual( pool[ 1 ][ "color" ], "#888888" )


class TestLoadOverflowPersonaFromConfig( unittest.TestCase ):
    def test_overflow_name_empty_returns_none( self ):
        self.assertIsNone( load_overflow_persona_from_config( _MockConfig( {
            "cc session voice persona overflow name": "   "
        } ) ) )

    def test_sam_backward_compat_voice_from_tts_default( self ):
        cfg = _MockConfig( {
            "cc session voice persona overflow name": "sam",
            "elevenlabs tts default voice id"       : "v-sam-default",
        } )
        p = load_overflow_persona_from_config( cfg )
        self.assertEqual( p[ "name" ], "sam" )
        self.assertEqual( p[ "voice_id" ], "v-sam-default" )
        self.assertTrue( p[ "overflow" ] )

    def test_no_resolvable_voice_returns_none( self ):
        # overflow_name 'arnold', no explicit voice id, not sam → None
        self.assertIsNone( load_overflow_persona_from_config( _MockConfig( {
            "cc session voice persona overflow name": "arnold"
        } ) ) )

    def test_explicit_overflow_persona( self ):
        cfg = _MockConfig( {
            "cc session voice persona overflow name"        : "arnold",
            "cc session voice persona arnold voice id"      : "v-arnold",
            "cc session voice persona arnold icon"          : "🪨",
            "cc session voice persona arnold color"         : "#FFD600",
            "cc session voice persona arnold profile"       : "gravelly",
            "cc session voice persona arnold display name"  : "Arnold",
        } )
        p = load_overflow_persona_from_config( cfg )
        self.assertEqual( p[ "name" ], "arnold" )
        self.assertEqual( p[ "voice_id" ], "v-arnold" )
        self.assertEqual( p[ "display_name" ], "Arnold" )
        self.assertTrue( p[ "overflow" ] )


class TestLowestFreeExtraN( unittest.TestCase ):
    def test_empty( self ):
        self.assertEqual( _lowest_free_extra_n( set() ), 1 )

    def test_one_taken( self ):
        self.assertEqual( _lowest_free_extra_n( { "extra 1" } ), 2 )

    def test_gap_reuse( self ):
        self.assertEqual( _lowest_free_extra_n( { "extra 2" } ), 1 )

    def test_consecutive( self ):
        self.assertEqual( _lowest_free_extra_n( { "extra 1", "extra 2" } ), 3 )


class TestMakeExtraPersona( unittest.TestCase ):
    _BASE = { "name": "arnold", "voice_id": "v-arnold", "icon": "🪨", "color": "#FFD600" }

    def test_with_palette_cycles_by_modulo( self ):
        palette = [ "#111", "#222", "#333" ]
        e1 = _make_extra_persona( self._BASE, 1, palette )
        e4 = _make_extra_persona( self._BASE, 4, palette )
        self.assertEqual( e1[ "name" ], "extra 1" )
        self.assertEqual( e1[ "display_name" ], "Extra 1" )
        self.assertEqual( e1[ "color" ], "#111" )
        self.assertEqual( e4[ "color" ], "#111" )   # (4-1) % 3 == 0
        self.assertEqual( e1[ "voice_id" ], "v-arnold" )
        self.assertTrue( e1[ "overflow" ] )
        self.assertFalse( e1[ "borrowed" ] )

    def test_empty_palette_inherits_base_color( self ):
        e = _make_extra_persona( self._BASE, 1, None )
        self.assertEqual( e[ "color" ], "#FFD600" )


class TestBorrowedPersonaForSid( unittest.TestCase ):
    _POOL = [
        { "name": "nora",    "voice_id": "v1", "icon": "🌸", "color": "#E91E63", "profile": "" },
        { "name": "quentin", "voice_id": "v2", "icon": "🦉", "color": "#FFA000", "profile": "" },
    ]

    def test_empty_pool_returns_none( self ):
        self.assertIsNone( borrowed_persona_for_sid( [], "sid" ) )

    def test_empty_sid_returns_none( self ):
        self.assertIsNone( borrowed_persona_for_sid( self._POOL, "" ) )

    def test_deterministic_for_same_sid( self ):
        b1 = borrowed_persona_for_sid( self._POOL, "sid-x" )
        b2 = borrowed_persona_for_sid( self._POOL, "sid-x" )
        self.assertEqual( b1, b2 )
        self.assertTrue( b1[ "borrowed" ] )
        self.assertIn( b1[ "name" ], { "nora", "quentin" } )

    def test_display_name_fallback_when_absent( self ):
        # Pool entries here have no display_name → helper derives it
        b = borrowed_persona_for_sid( self._POOL, "sid-x" )
        self.assertEqual( b[ "display_name" ], display_name_for( b[ "name" ] ) )


class TestPickUnallocatedPersona( unittest.TestCase ):
    _POOL = [
        { "name": "nora",    "voice_id": "v1", "icon": "🌸", "color": "#E91E63", "profile": "" },
        { "name": "quentin", "voice_id": "v2", "icon": "🦉", "color": "#FFA000", "profile": "" },
        { "name": "rachel",  "voice_id": "v3", "icon": "🕊️", "color": "#4CAF50", "profile": "" },
    ]
    _ARNOLD = { "name": "arnold", "display_name": "Arnold", "voice_id": "v-arnold",
                "icon": "🪨", "color": "#FFD600", "profile": "gravelly", "overflow": True }

    def test_empty_pool_returns_none( self ):
        self.assertIsNone( pick_unallocated_persona( [], set(), "sid" ) )

    def test_free_pick_borrowed_false( self ):
        with patch( "cosa.rest.voice_persona_helpers.random.choice", side_effect=lambda seq: seq[ 0 ] ):
            p = pick_unallocated_persona( self._POOL, { "nora", "quentin" }, "sid" )
        self.assertEqual( p[ "name" ], "rachel" )
        self.assertFalse( p[ "borrowed" ] )
        self.assertEqual( p[ "display_name" ], "Rachel" )

    def test_exhausted_overflow_free_returns_arnold( self ):
        p = pick_unallocated_persona(
            self._POOL, { "nora", "quentin", "rachel" }, "sid",
            overflow_persona=self._ARNOLD, extra_colors=[ "#111" ]
        )
        self.assertEqual( p[ "name" ], "arnold" )
        self.assertTrue( p[ "overflow" ] )
        self.assertFalse( p[ "borrowed" ] )

    def test_exhausted_overflow_taken_returns_extra( self ):
        p = pick_unallocated_persona(
            self._POOL, { "nora", "quentin", "rachel", "arnold" }, "sid",
            overflow_persona=self._ARNOLD, extra_colors=[ "#111" ]
        )
        self.assertEqual( p[ "name" ], "extra 1" )
        self.assertEqual( p[ "voice_id" ], "v-arnold" )

    def test_exhausted_no_overflow_falls_back_to_borrow( self ):
        p = pick_unallocated_persona( self._POOL, { "nora", "quentin", "rachel" }, "sid-z" )
        self.assertTrue( p[ "borrowed" ] )
        self.assertIn( p[ "name" ], { "nora", "quentin", "rachel" } )

    def test_free_pick_uses_existing_display_name( self ):
        pool = [ { "name": "nora", "display_name": "NORA-CUSTOM", "voice_id": "v1",
                   "icon": "🌸", "color": "#E91E63", "profile": "" } ]
        with patch( "cosa.rest.voice_persona_helpers.random.choice", side_effect=lambda seq: seq[ 0 ] ):
            p = pick_unallocated_persona( pool, set(), "sid" )
        self.assertEqual( p[ "display_name" ], "NORA-CUSTOM" )


class TestAllocatePersonaForSession( unittest.TestCase ):
    def _cfg( self ):
        return _MockConfig( {
            "cc session voice persona pool"          : "nora",
            "cc session voice persona nora voice id" : "v-nora",
            "cc session voice persona overflow name" : "   ",   # disable overflow
            "cc session voice persona extra colors"  : "",
            "cc session voice persona stale threshold seconds": 43200,
        } )

    def test_empty_pool_returns_none( self ):
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):
            self.assertIsNone( allocate_persona_for_session( _MockConfig(), "sid" ) )

    def test_allocates_and_stamps_assigned_at( self ):
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):
            p = allocate_persona_for_session( self._cfg(), "sid" )
        self.assertEqual( p[ "name" ], "nora" )
        self.assertIn( "assigned_at", p )

    def test_occupied_set_built_from_active_bridges( self ):
        # An active bridge holds 'nora' → pool exhausted, no overflow → borrow path
        active = [ ( "/p", "other-sid", { "name": "nora" } ), ( "/p2", "x", "not-a-dict" ) ]
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=active ):
            p = allocate_persona_for_session( self._cfg(), "sid" )
        self.assertTrue( p[ "borrowed" ] )
        self.assertIn( "assigned_at", p )


class TestFindPersonaInPool( unittest.TestCase ):
    _POOL = [ { "name": "maria", "voice_id": "v1", "icon": "x", "color": "c", "profile": "" } ]

    def test_empty_name_returns_none( self ):
        self.assertIsNone( _find_persona_in_pool( self._POOL, "" ) )

    def test_whitespace_name_returns_none( self ):
        self.assertIsNone( _find_persona_in_pool( self._POOL, "   " ) )

    def test_match_by_key_form( self ):
        self.assertEqual( _find_persona_in_pool( self._POOL, "MARIA" )[ "name" ], "maria" )

    def test_match_by_display_name( self ):
        # display_name_for("maria") == "María" → case-insensitive match
        self.assertEqual( _find_persona_in_pool( self._POOL, "maría" )[ "name" ], "maria" )

    def test_no_match_returns_none( self ):
        self.assertIsNone( _find_persona_in_pool( self._POOL, "zelda" ) )


class TestPickRequestedPersona( unittest.TestCase ):
    _POOL = [
        { "name": "nora",   "voice_id": "v1", "icon": "🌸", "color": "#E91E63", "profile": "" },
        { "name": "rachel", "voice_id": "v3", "icon": "🕊️", "color": "#4CAF50", "profile": "" },
    ]

    def test_not_in_pool( self ):
        res = pick_requested_persona( self._POOL, {}, "zelda" )
        self.assertEqual( res[ "status" ], "not_in_pool" )
        self.assertIsNone( res[ "persona" ] )
        self.assertEqual( res[ "available" ], [ "nora", "rachel" ] )

    def test_occupied( self ):
        res = pick_requested_persona( self._POOL, { "nora": "sid-holder" }, "nora" )
        self.assertEqual( res[ "status" ], "occupied" )
        self.assertEqual( res[ "holding_session_id" ], "sid-holder" )
        self.assertEqual( res[ "holding_persona_name" ], "nora" )
        self.assertEqual( res[ "available" ], [ "rachel" ] )

    def test_ok( self ):
        res = pick_requested_persona( self._POOL, {}, "rachel" )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertEqual( res[ "persona" ][ "name" ], "rachel" )
        self.assertFalse( res[ "persona" ][ "borrowed" ] )

    def test_ok_uses_existing_display_name( self ):
        pool = [ { "name": "nora", "display_name": "NORA!", "voice_id": "v1", "icon": "🌸", "color": "#E91E63", "profile": "" } ]
        res = pick_requested_persona( pool, {}, "nora" )
        self.assertEqual( res[ "persona" ][ "display_name" ], "NORA!" )


class TestAllocateRequestedPersonaForSession( unittest.TestCase ):
    def _cfg( self ):
        return _MockConfig( {
            "cc session voice persona pool"          : "nora,rachel",
            "cc session voice persona nora voice id" : "v-nora",
            "cc session voice persona rachel voice id": "v-rachel",
            "cc session voice persona stale threshold seconds": 43200,
        } )

    def test_empty_pool_returns_none( self ):
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):
            self.assertIsNone( allocate_requested_persona_for_session( _MockConfig(), "sid", "nora" ) )

    def test_ok_stamps_assigned_at_and_excludes_self( self ):
        # The requesting session itself holds 'rachel'; a different session holds 'nora'.
        active = [
            ( "/p1", "sid-self",  { "name": "rachel" } ),   # excluded (self)
            ( "/p2", "sid-other", { "name": "nora" } ),     # counts as occupied
            ( "/p3", "sid-bad",   "not-a-dict" ),           # skipped
            ( "/p4", "sid-noname",{ } ),                    # skipped (no name)
        ]
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=active ):
            # Requesting 'rachel' (which only self holds → excluded → available)
            res = allocate_requested_persona_for_session( self._cfg(), "sid-self", "rachel" )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertIn( "assigned_at", res[ "persona" ] )

    def test_occupied_does_not_stamp( self ):
        active = [ ( "/p2", "sid-other", { "name": "nora" } ) ]
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=active ):
            res = allocate_requested_persona_for_session( self._cfg(), "sid-self", "nora" )
        self.assertEqual( res[ "status" ], "occupied" )
        self.assertIsNone( res[ "persona" ] )


class TestPickPreferredPersonaFromEnv( unittest.TestCase ):
    def test_none_project_returns_none( self ):
        self.assertIsNone( pick_preferred_persona_from_env( None ) )
        self.assertIsNone( pick_preferred_persona_from_env( "" ) )

    def test_whitespace_project_returns_none( self ):
        # non-empty whitespace passes the first guard but normalizes to ""
        self.assertIsNone( pick_preferred_persona_from_env( "   " ) )

    def test_env_unset_returns_none( self ):
        with patch.dict( "os.environ", {}, clear=True ):
            self.assertIsNone( pick_preferred_persona_from_env( "lupin" ) )

    def test_env_empty_returns_none( self ):
        with patch.dict( "os.environ", { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "   " }, clear=True ):
            self.assertIsNone( pick_preferred_persona_from_env( "lupin" ) )

    def test_env_set_returns_value_normalizing_project( self ):
        with patch.dict( "os.environ", { "COSA_VOICE_PREFERRED_PERSONA__COSA_VOICE": "Tiberius" }, clear=True ):
            self.assertEqual( pick_preferred_persona_from_env( "cosa-voice" ), "Tiberius" )


def isolated_unit_test():
    """
    Run the voice_persona_helpers unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} voice_persona_helpers tests in {secs:.3f}s — {msg}" )
