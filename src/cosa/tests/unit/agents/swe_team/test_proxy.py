"""
Unit tests for the swe_team engineering-proxy subpackage:
  - proxy/__init__.py               : package re-export surface (__all__)
  - proxy/config.py                 : SWE sender/cap defaults + swe_proxy_config_from_config_mgr
  - proxy/engineering_categories.py : ENGINEERING_CATEGORIES + get_category_names + get_category_cap_level
  - proxy/engineering_classifier.py : EngineeringClassifier.classify (sender-hint + keyword scoring)

All pure logic — no LLM/SDK/network/INI. config_mgr is mocked at the boundary.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, support tier).
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import cosa.agents.swe_team.proxy as proxy_pkg
import cosa.agents.swe_team.proxy.config as proxy_config
import cosa.agents.swe_team.proxy.engineering_categories as ecats
from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier


# ============================================================================
# proxy/__init__.py — re-export surface
# ============================================================================

class TestProxyPackageSurface( unittest.TestCase ):

    def test_all_names_are_exported_and_resolvable( self ):
        for name in (
            "ENGINEERING_CATEGORIES", "get_category_names", "get_category_cap_level",
            "EngineeringClassifier", "EngineeringStrategy",
            "DEFAULT_ACCEPTED_SENDERS", "DEFAULT_DEPLOYMENT_CAP_LEVEL",
            "DEFAULT_DESTRUCTIVE_CAP_LEVEL", "DEFAULT_ARCHITECTURE_CAP_LEVEL",
        ):
            self.assertIn( name, proxy_pkg.__all__ )
            self.assertTrue( hasattr( proxy_pkg, name ) )

    def test_reexports_are_the_same_objects( self ):
        self.assertIs( proxy_pkg.ENGINEERING_CATEGORIES, ecats.ENGINEERING_CATEGORIES )
        self.assertIs( proxy_pkg.get_category_names,     ecats.get_category_names )
        self.assertIs( proxy_pkg.EngineeringClassifier,  EngineeringClassifier )


# ============================================================================
# proxy/config.py — defaults + factory
# ============================================================================

class TestProxyConfigDefaults( unittest.TestCase ):

    def test_high_risk_categories_capped_at_l3( self ):
        self.assertEqual( proxy_config.DEFAULT_DEPLOYMENT_CAP_LEVEL,   3 )
        self.assertEqual( proxy_config.DEFAULT_DESTRUCTIVE_CAP_LEVEL,  3 )
        self.assertEqual( proxy_config.DEFAULT_ARCHITECTURE_CAP_LEVEL, 3 )

    def test_low_risk_categories_reach_l5( self ):
        self.assertEqual( proxy_config.DEFAULT_TESTING_CAP_LEVEL, 5 )
        self.assertEqual( proxy_config.DEFAULT_DEPS_CAP_LEVEL,    5 )
        self.assertEqual( proxy_config.DEFAULT_GENERAL_CAP_LEVEL, 5 )

    def test_default_accepted_senders_present( self ):
        self.assertIn( "swe.lead@lupin.deepily.ai", proxy_config.DEFAULT_ACCEPTED_SENDERS )
        self.assertEqual( len( proxy_config.DEFAULT_ACCEPTED_SENDERS ), 3 )


class TestProxyConfigFactory( unittest.TestCase ):

    def test_falls_back_to_module_defaults( self ):
        # config_mgr.get returns the supplied default for every key.
        cfg_mgr = MagicMock()
        cfg_mgr.get.side_effect = lambda key, default=None, return_type=None: default

        result = proxy_config.swe_proxy_config_from_config_mgr( cfg_mgr )

        self.assertEqual( result[ "accepted_senders" ], proxy_config.DEFAULT_ACCEPTED_SENDERS )
        self.assertEqual( result[ "deployment_cap_level" ],   3 )
        self.assertEqual( result[ "destructive_cap_level" ],  3 )
        self.assertEqual( result[ "architecture_cap_level" ], 3 )

    def test_parses_csv_senders_and_strips_empties( self ):
        # Senders string with whitespace + a trailing empty entry exercises BOTH
        # arms of the `if s.strip()` comprehension filter.
        cfg_mgr = MagicMock()

        def _get( key, default=None, return_type=None ):
            if key == "swe engineering proxy accepted senders":
                return "  a@x.ai , b@x.ai ,, "
            return default
        cfg_mgr.get.side_effect = _get

        result = proxy_config.swe_proxy_config_from_config_mgr( cfg_mgr )
        self.assertEqual( result[ "accepted_senders" ], [ "a@x.ai", "b@x.ai" ] )

    def test_reads_int_cap_levels_from_ini( self ):
        cfg_mgr = MagicMock()

        def _get( key, default=None, return_type=None ):
            overrides = {
                "swe engineering proxy deployment cap level"   : 2,
                "swe engineering proxy destructive cap level"  : 1,
                "swe engineering proxy architecture cap level" : 4,
            }
            return overrides.get( key, default )
        cfg_mgr.get.side_effect = _get

        result = proxy_config.swe_proxy_config_from_config_mgr( cfg_mgr )
        self.assertEqual( result[ "deployment_cap_level" ],   2 )
        self.assertEqual( result[ "destructive_cap_level" ],  1 )
        self.assertEqual( result[ "architecture_cap_level" ], 4 )


# ============================================================================
# proxy/engineering_categories.py
# ============================================================================

class TestEngineeringCategories( unittest.TestCase ):

    def test_six_categories_present( self ):
        self.assertEqual(
            set( ecats.get_category_names() ),
            { "deployment", "testing", "deps", "architecture", "destructive", "general" },
        )

    def test_general_is_catch_all_with_no_keywords( self ):
        self.assertEqual( ecats.ENGINEERING_CATEGORIES[ "general" ][ "keywords" ], [] )

    def test_get_cap_level_known_category( self ):
        self.assertEqual( ecats.get_category_cap_level( "deployment" ), 3 )
        self.assertEqual( ecats.get_category_cap_level( "testing" ),    5 )

    def test_get_cap_level_unknown_category_defaults_to_5( self ):
        # The `cat is None` guard arm.
        self.assertEqual( ecats.get_category_cap_level( "does-not-exist" ), 5 )


# ============================================================================
# proxy/engineering_classifier.py
# ============================================================================

class TestEngineeringClassifier( unittest.TestCase ):

    def setUp( self ):
        self.clf = EngineeringClassifier( debug=False )

    def test_get_categories_returns_canonical_dict( self ):
        self.assertIs( self.clf.get_categories(), ecats.ENGINEERING_CATEGORIES )

    # --- keyword scoring -----------------------------------------------------

    def test_single_keyword_match_classifies( self ):
        cat, conf = self.clf.classify( "Please deploy to production now" )
        self.assertEqual( cat, "deployment" )
        self.assertGreater( conf, 0.5 )

    def test_multiple_keyword_matches_raise_confidence_capped( self ):
        # Many destructive keywords → base_confidence climbs but stays <= 0.95.
        q = "delete remove drop truncate destroy purge wipe nuke overwrite irreversible"
        cat, conf = self.clf.classify( q )
        self.assertEqual( cat, "destructive" )
        self.assertLessEqual( conf, 0.95 )

    def test_sender_hint_boosts_matching_category( self ):
        # swe.tester hints "testing"; the question also has testing keywords,
        # so the +0.15 sender boost arm fires.
        cat, conf = self.clf.classify(
            "run the pytest test suite for coverage",
            sender_id="swe.tester@lupin.deepily.ai",
        )
        self.assertEqual( cat, "testing" )
        self.assertGreater( conf, 0.6 )

    # --- no-keyword-match fallbacks -----------------------------------------

    def test_no_keywords_uses_sender_hint( self ):
        # Question with zero category keywords, but tester sender → testing@0.45.
        cat, conf = self.clf.classify( "hello there friend", sender_id="swe.tester@x.ai" )
        self.assertEqual( cat, "testing" )
        self.assertEqual( conf, 0.45 )

    def test_no_keywords_sender_hint_debug_prints( self ):
        clf = EngineeringClassifier( debug=True )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            clf.classify( "hello there friend", sender_id="swe.tester@x.ai" )
        self.assertIn( "using sender hint", buf.getvalue() )

    def test_no_keywords_no_hint_falls_back_to_general( self ):
        cat, conf = self.clf.classify( "hello there friend" )
        self.assertEqual( cat, "general" )
        self.assertEqual( conf, 0.3 )

    def test_no_keywords_no_hint_debug_prints( self ):
        clf = EngineeringClassifier( debug=True )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            clf.classify( "hello there friend" )
        self.assertIn( "No match", buf.getvalue() )

    def test_keyword_match_debug_prints_best_category( self ):
        clf = EngineeringClassifier( debug=True )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            clf.classify( "deploy to production" )
        self.assertIn( "deployment", buf.getvalue() )

    # --- _get_sender_hint edge arcs -----------------------------------------

    def test_sender_hint_empty_sender_returns_none( self ):
        self.assertIsNone( self.clf._get_sender_hint( "" ) )

    def test_sender_hint_no_at_sign_uses_full_string( self ):
        # No '@' → prefix == full sender_id.
        self.assertEqual( self.clf._get_sender_hint( "swe.tester" ), "testing" )

    def test_sender_hint_coder_maps_to_none( self ):
        self.assertIsNone( self.clf._get_sender_hint( "swe.coder@x.ai" ) )

    def test_sender_hint_unknown_prefix_returns_none( self ):
        self.assertIsNone( self.clf._get_sender_hint( "random.user@x.ai" ) )


if __name__ == "__main__":
    unittest.main()
