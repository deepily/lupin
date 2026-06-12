"""
Unit tests for voice persona allocation helpers (cosa.rest.voice_persona_helpers).

Covers display_name_for, load_persona_pool_from_config, load_overflow_persona_from_config,
_lowest_free_extra_n, _make_extra_persona, borrowed_persona_for_sid,
pick_unallocated_persona (free / Arnold-overflow / Extra-N / legacy-borrow / empty),
allocate_persona_for_session, _find_persona_in_pool, pick_requested_persona,
allocate_requested_persona_for_session, pick_persona_chain_from_env,
parse_persona_chain, resolve_session_start_persona_chain, and
allocate_persona_chain_for_session — to genuine 100% line + branch + function.

config_mgr is a dict-backed stand-in; session_bridge.find_active_voice_persona_sessions
and random.choice are patched. ZERO config-file / bridge-file / env mutation leaks.
"""

import unittest
from unittest.mock import patch, ANY

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
    pick_persona_chain_from_env,
    parse_persona_chain,
    resolve_session_start_persona_chain,
    allocate_persona_chain_for_session,
    PERSONA_CHAIN_WILDCARD,
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

    def test_declared_managers_excluded_from_random_draw( self ):
        # Reserve-from-random: nothing occupied, but nora + quentin are
        # declared managers → the only random candidate is rachel.
        for _ in range( 10 ):
            p = pick_unallocated_persona(
                self._POOL, set(), "sid", declared_manager_names={ "nora", "quentin" }
            )
            self.assertEqual( p[ "name" ], "rachel" )
            self.assertFalse( p[ "borrowed" ] )

    def test_exclusion_emptied_pool_takes_overflow_path( self ):
        # Nothing occupied, ALL pool names declared → free set empties via the
        # reservation alone → existing overflow semantics fire unchanged.
        p = pick_unallocated_persona(
            self._POOL, set(), "sid",
            overflow_persona=self._ARNOLD, extra_colors=[ "#111" ],
            declared_manager_names={ "nora", "quentin", "rachel" }
        )
        self.assertEqual( p[ "name" ], "arnold" )
        self.assertTrue( p[ "overflow" ] )

    def test_exclusion_emptied_pool_no_overflow_borrows( self ):
        p = pick_unallocated_persona(
            self._POOL, set(), "sid-z", declared_manager_names={ "nora", "quentin", "rachel" }
        )
        self.assertTrue( p[ "borrowed" ] )

    def test_exclusion_does_not_shadow_occupied_in_overflow_check( self ):
        # Declared names are NOT added to occupied: with the pool emptied by
        # reservation and arnold genuinely occupied, Extra-N fires (proving
        # the overflow check still reads occupied_names, not the reservation).
        p = pick_unallocated_persona(
            self._POOL, { "arnold" }, "sid",
            overflow_persona=self._ARNOLD, extra_colors=[ "#111" ],
            declared_manager_names={ "nora", "quentin", "rachel" }
        )
        self.assertEqual( p[ "name" ], "extra 1" )


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

    def _roster_cfg( self ):
        return _MockConfig( {
            "cc session voice persona pool"               : "mr radio, tiberius, nora",
            "cc session voice persona mr radio voice id"  : "v-radio",
            "cc session voice persona tiberius voice id"  : "v-tib",
            "cc session voice persona nora voice id"      : "v-nora",
            "cc session voice persona overflow name"      : "   ",
            "cc session voice persona extra colors"       : "",
            "cc session voice persona stale threshold seconds": 43200,
        } )

    def test_declared_managers_resolved_punct_tolerant_and_excluded( self ):
        # Roster forms "Mr. Radio" (display) / "TIBERIUS" (case) both resolve
        # via _find_persona_in_pool; "Ghost" resolves to nothing and
        # constrains nothing → the random draw can only yield nora.
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):
            for _ in range( 10 ):
                p = allocate_persona_for_session(
                    self._roster_cfg(), "sid",
                    declared_managers=[ "Mr. Radio", "TIBERIUS", "Ghost" ]
                )
                self.assertEqual( p[ "name" ], "nora" )
                self.assertFalse( p[ "borrowed" ] )

    def test_declared_managers_none_leaves_full_pool( self ):
        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ), \
             patch( "cosa.rest.voice_persona_helpers.random.choice", side_effect=lambda seq: seq[ 0 ] ):
            p = allocate_persona_for_session( self._roster_cfg(), "sid", declared_managers=None )
        self.assertEqual( p[ "name" ], "mr radio" )   # head of the UNRESERVED pool


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


class TestPickPersonaChainFromEnv( unittest.TestCase ):
    def test_none_project_returns_none( self ):
        self.assertIsNone( pick_persona_chain_from_env( None ) )
        self.assertIsNone( pick_persona_chain_from_env( "" ) )

    def test_whitespace_project_returns_none( self ):
        # non-empty whitespace passes the first guard but normalizes to ""
        self.assertIsNone( pick_persona_chain_from_env( "   " ) )

    def test_env_unset_returns_none( self ):
        with patch.dict( "os.environ", {}, clear=True ):
            self.assertIsNone( pick_persona_chain_from_env( "lupin" ) )

    def test_env_empty_returns_none( self ):
        with patch.dict( "os.environ", { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "   " }, clear=True ):
            self.assertIsNone( pick_persona_chain_from_env( "lupin" ) )

    def test_env_set_returns_value_normalizing_project( self ):
        with patch.dict( "os.environ", { "COSA_VOICE_PREFERRED_PERSONA__COSA_VOICE": "Tiberius" }, clear=True ):
            self.assertEqual( pick_persona_chain_from_env( "cosa-voice" ), "Tiberius" )

    def test_explicit_environ_dict_returns_chain_verbatim( self ):
        # environ= param bypasses os.environ entirely (testability seam)
        environ = { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "Mr. Radio,Tiberius,*" }
        self.assertEqual( pick_persona_chain_from_env( "lupin", environ=environ ), "Mr. Radio,Tiberius,*" )

    def test_explicit_environ_dict_unset_returns_none( self ):
        self.assertIsNone( pick_persona_chain_from_env( "lupin", environ={} ) )

    def test_explicit_environ_dict_whitespace_value_returns_none( self ):
        environ = { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "   " }
        self.assertIsNone( pick_persona_chain_from_env( "lupin", environ=environ ) )


class TestParsePersonaChain( unittest.TestCase ):
    def test_csv_string( self ):
        self.assertEqual( parse_persona_chain( "Rio,Krishna,*" ), [ "Rio", "Krishna", "*" ] )

    def test_csv_strips_whitespace_around_elements( self ):
        self.assertEqual( parse_persona_chain( " Rio , Krishna , * " ), [ "Rio", "Krishna", "*" ] )

    def test_list_input( self ):
        self.assertEqual( parse_persona_chain( [ "Rio", "Krishna" ] ), [ "Rio", "Krishna" ] )

    def test_multi_word_name_passes_verbatim( self ):
        # Commas are the ONLY delimiter — "Mr. Radio" stays one element
        self.assertEqual( parse_persona_chain( "Mr. Radio, Tiberius , *" ), [ "Mr. Radio", "Tiberius", "*" ] )

    def test_wildcard_is_an_ordinary_element( self ):
        self.assertEqual( parse_persona_chain( "*" ), [ PERSONA_CHAIN_WILDCARD ] )

    def test_case_insensitive_dedupe_first_wins( self ):
        self.assertEqual( parse_persona_chain( "rio,Rio,*" ),       [ "rio", "*" ] )
        self.assertEqual( parse_persona_chain( "Rio,RIO,rio,Rio" ), [ "Rio" ] )

    def test_non_string_items_in_list_skipped( self ):
        self.assertEqual( parse_persona_chain( [ "Rio", 42, None, "*" ] ), [ "Rio", "*" ] )

    def test_none_returns_empty( self ):
        self.assertEqual( parse_persona_chain( None ), [] )

    def test_empty_string_returns_empty( self ):
        self.assertEqual( parse_persona_chain( "" ), [] )

    def test_commas_only_returns_empty( self ):
        self.assertEqual( parse_persona_chain( ",,," ), [] )

    def test_int_returns_empty( self ):
        self.assertEqual( parse_persona_chain( 42 ), [] )


class TestResolveSessionStartPersonaChain( unittest.TestCase ):
    def test_spawn_chain_wins_over_everything( self ):
        environ = {
            "COSA_VOICE_PERSONA_CHAIN"            : "Rio,Krishna,*",
            "COSA_VOICE_HEADLESS"                 : "1",
            "COSA_VOICE_PREFERRED_PERSONA__LUPIN" : "Tiberius",
        }
        self.assertEqual( resolve_session_start_persona_chain( "lupin", environ ), "Rio,Krishna,*" )

    def test_headless_without_chain_returns_none_even_with_repo_var( self ):
        # A preference-less worker must NOT inherit the user's manager chain
        environ = {
            "COSA_VOICE_HEADLESS"                 : "1",
            "COSA_VOICE_PREFERRED_PERSONA__LUPIN" : "Mr. Radio,Tiberius,*",
        }
        self.assertIsNone( resolve_session_start_persona_chain( "lupin", environ ) )

    def test_non_headless_falls_to_per_repo_var( self ):
        environ = { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "Mr. Radio,Tiberius,*" }
        self.assertEqual( resolve_session_start_persona_chain( "lupin", environ ), "Mr. Radio,Tiberius,*" )

    def test_nothing_set_returns_none( self ):
        self.assertIsNone( resolve_session_start_persona_chain( "lupin", {} ) )

    def test_project_none_returns_none( self ):
        self.assertIsNone( resolve_session_start_persona_chain( None, {} ) )

    def test_whitespace_spawn_chain_falls_through( self ):
        environ = {
            "COSA_VOICE_PERSONA_CHAIN"            : "   ",
            "COSA_VOICE_PREFERRED_PERSONA__LUPIN" : "Tiberius",
        }
        self.assertEqual( resolve_session_start_persona_chain( "lupin", environ ), "Tiberius" )


class TestAllocatePersonaChainForSession( unittest.TestCase ):
    """
    Chain-walk tests with the two underlying allocators boundary-mocked —
    allocate_requested_persona_for_session (named elements) and
    allocate_persona_for_session (wildcard) — so each branch of the walk is
    driven deterministically with zero bridge/config I/O.
    """

    _OCCUPIED_RIO = {
        "status"               : "occupied",
        "persona"              : None,
        "holding_session_id"   : "sid-holder",
        "holding_persona_name" : "rio",
        "available"            : [ "krishna", "nora" ]
    }

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_first_element_ok( self, mock_named, mock_wild ):
        mock_named.return_value = { "status": "ok", "persona": { "name": "rio", "assigned_at": "t" }, "available": [] }
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "Rio,Krishna,*" )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertEqual( res[ "satisfied_by" ], "Rio" )
        self.assertFalse( res[ "wildcard_used" ] )
        self.assertEqual( res[ "outcomes" ], [] )
        self.assertEqual( res[ "persona" ][ "name" ], "rio" )
        mock_named.assert_called_once_with( ANY, "sid", "Rio" )
        mock_wild.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_occupied_then_ok_records_outcome( self, mock_named, mock_wild ):
        mock_named.side_effect = [
            dict( self._OCCUPIED_RIO ),
            { "status": "ok", "persona": { "name": "krishna", "assigned_at": "t" }, "available": [] },
        ]
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "Rio,Krishna" )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertEqual( res[ "satisfied_by" ], "Krishna" )
        self.assertFalse( res[ "wildcard_used" ] )
        self.assertEqual( res[ "outcomes" ], [ {
            "name"                 : "Rio",
            "status"               : "occupied",
            "holding_session_id"   : "sid-holder",
            "holding_persona_name" : "rio"
        } ] )
        mock_wild.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_not_in_pool_skipped( self, mock_named, mock_wild ):
        mock_named.side_effect = [
            { "status": "not_in_pool", "persona": None, "available": [ "nora" ] },
            { "status": "ok", "persona": { "name": "nora", "assigned_at": "t" }, "available": [] },
        ]
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "Ghost,Nora" )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertEqual( res[ "satisfied_by" ], "Nora" )
        # not_in_pool outcome carries NO holding info
        self.assertEqual( res[ "outcomes" ], [ { "name": "Ghost", "status": "not_in_pool" } ] )
        mock_wild.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_wildcard_fires_with_outcomes_carried( self, mock_named, mock_wild ):
        mock_named.return_value = dict( self._OCCUPIED_RIO )
        mock_wild.return_value  = { "name": "nora", "assigned_at": "t" }
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "Rio,*" )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertEqual( res[ "satisfied_by" ], PERSONA_CHAIN_WILDCARD )
        self.assertTrue( res[ "wildcard_used" ] )
        self.assertEqual( len( res[ "outcomes" ] ), 1 )
        self.assertEqual( res[ "outcomes" ][ 0 ][ "name" ], "Rio" )
        self.assertEqual( res[ "persona" ][ "name" ], "nora" )
        mock_wild.assert_called_once_with( ANY, "sid", declared_managers=None )

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_wildcard_threads_declared_managers( self, mock_named, mock_wild ):
        # Reserve-from-random: the roster reaches the `*` random draw...
        mock_wild.return_value = { "name": "nora", "assigned_at": "t" }
        res = allocate_persona_chain_for_session(
            _MockConfig(), "sid", "*", declared_managers=[ "Mr. Radio", "Tiberius" ]
        )
        self.assertEqual( res[ "status" ], "ok" )
        mock_wild.assert_called_once_with( ANY, "sid", declared_managers=[ "Mr. Radio", "Tiberius" ] )
        mock_named.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_named_element_ignores_declared_managers( self, mock_named, mock_wild ):
        # ...but a NAMED element claims through the strict path untouched —
        # that is how a manager gets its name.
        mock_named.return_value = { "status": "ok", "persona": { "name": "mr radio", "assigned_at": "t" }, "available": [] }
        res = allocate_persona_chain_for_session(
            _MockConfig(), "sid", "Mr. Radio,*", declared_managers=[ "Mr. Radio" ]
        )
        self.assertEqual( res[ "status" ], "ok" )
        self.assertEqual( res[ "satisfied_by" ], "Mr. Radio" )
        mock_named.assert_called_once_with( ANY, "sid", "Mr. Radio" )
        mock_wild.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_wildcard_pool_none_returns_pool_error( self, mock_named, mock_wild ):
        mock_wild.return_value = None
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "*" )
        self.assertEqual( res[ "status" ], "pool_error" )
        self.assertIsNone( res[ "persona" ] )
        self.assertEqual( res[ "outcomes" ], [] )
        self.assertEqual( res[ "available" ], [] )
        mock_named.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_named_pool_none_returns_pool_error( self, mock_named, mock_wild ):
        mock_named.return_value = None
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "Rio,*" )
        self.assertEqual( res[ "status" ], "pool_error" )
        self.assertIsNone( res[ "persona" ] )
        mock_wild.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_exhausted_records_outcomes_and_available( self, mock_named, mock_wild ):
        mock_named.side_effect = [
            dict( self._OCCUPIED_RIO ),
            { "status": "not_in_pool", "persona": None, "available": [ "krishna" ] },
        ]
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", "Rio,Ghost" )
        self.assertEqual( res[ "status" ], "exhausted" )
        self.assertIsNone( res[ "persona" ] )
        self.assertEqual( [ o[ "name" ] for o in res[ "outcomes" ] ], [ "Rio", "Ghost" ] )
        self.assertEqual( [ o[ "status" ] for o in res[ "outcomes" ] ], [ "occupied", "not_in_pool" ] )
        self.assertEqual( res[ "available" ], [ "krishna" ] )   # from the LAST walk result
        mock_wild.assert_not_called()

    @patch( "cosa.rest.voice_persona_helpers.allocate_persona_for_session" )
    @patch( "cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session" )
    def test_empty_chain_short_circuits( self, mock_named, mock_wild ):
        res = allocate_persona_chain_for_session( _MockConfig(), "sid", ",,," )
        self.assertEqual( res, { "status": "empty_chain", "persona": None, "outcomes": [], "available": [] } )
        mock_named.assert_not_called()
        mock_wild.assert_not_called()


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
