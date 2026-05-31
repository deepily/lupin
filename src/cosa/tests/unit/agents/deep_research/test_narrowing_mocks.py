"""
Unit tests for cosa.agents.deep_research.narrowing_mocks.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). Pure-logic module: canned theme-clustering dicts, the `get_mock_theme_response`
variant/size router, `get_mock_subqueries`, and `MockResearchAPIClient` (a deterministic
stand-in for the real AsyncAnthropic-backed client — no network). All branches are
covered by driving each variant + subquery-count boundary.

Coverage note: line 275's `[2] if num_subqueries > 2 else []` else-arm is unreachable
(reaching line 263 requires num_subqueries > 3, so it is always > 2 here). coverage.py
does NOT arc-track ternary expressions, so this surfaces no partial branch — no pragma
needed. Documented here for the reviewer.
"""

import unittest

import cosa.agents.deep_research.narrowing_mocks as nm


class TestGetMockThemeResponse( unittest.TestCase ):
    """Variant + count routing through every `if`/`for` arm."""

    def test_empty_variant_returns_empty_themes( self ):
        # line 234 true arm
        self.assertEqual( nm.get_mock_theme_response( 5, "empty" )[ "themes" ], [ ] )

    def test_minimal_variant_returns_single_theme( self ):
        # line 237 true via variant == "minimal" (count would otherwise be balanced)
        resp = nm.get_mock_theme_response( 5, "minimal" )
        self.assertEqual( len( resp[ "themes" ] ), 1 )
        self.assertIs( resp, nm.MOCK_THEMES_1 )

    def test_small_count_returns_single_theme( self ):
        # line 237 true via num_subqueries <= 3 with default variant
        resp = nm.get_mock_theme_response( 2 )
        self.assertIs( resp, nm.MOCK_THEMES_1 )

    def test_maximal_variant_with_empty_trailing_theme( self ):
        # line 240 true via variant == "maximal"; num=5 → indices_per_theme=1, the
        # i==5 trailing theme gets range(5,5)==[] exercising the `if indices:` FALSE arm.
        resp = nm.get_mock_theme_response( 5, "maximal" )
        themes = resp[ "themes" ]
        # 5 non-empty themes (i=0..4); the 6th (i==5) is dropped as empty.
        self.assertEqual( len( themes ), 5 )
        all_indices = [ idx for t in themes for idx in t[ "subquery_indices" ] ]
        self.assertEqual( sorted( all_indices ), [ 0, 1, 2, 3, 4 ] )

    def test_large_count_routes_to_maximal_with_remainder( self ):
        # line 240 true via num_subqueries >= 8 (balanced variant); i==5 gets the
        # remaining indices [5,6,7] — `if i == 5` true arm with non-empty `if indices:`.
        resp = nm.get_mock_theme_response( 8 )
        themes = resp[ "themes" ]
        self.assertEqual( len( themes ), 6 )
        all_indices = [ idx for t in themes for idx in t[ "subquery_indices" ] ]
        self.assertEqual( sorted( all_indices ), [ 0, 1, 2, 3, 4, 5, 6, 7 ] )

    def test_balanced_small_uses_three_themes( self ):
        # line 263 true arm: 4 <= 5 → bespoke 3-theme distribution (num>2 → [2] populated)
        resp = nm.get_mock_theme_response( 4 )
        self.assertEqual( len( resp[ "themes" ] ), 3 )
        self.assertEqual( resp[ "themes" ][ 0 ][ "subquery_indices" ], [ 0, 1 ] )
        self.assertEqual( resp[ "themes" ][ 1 ][ "subquery_indices" ], [ 2 ] )
        self.assertEqual( resp[ "themes" ][ 2 ][ "subquery_indices" ], [ 3 ] )

    def test_balanced_medium_uses_four_themes( self ):
        # line 263 false arm: 6 > 5 and < 8 → MOCK_THEMES_4
        resp = nm.get_mock_theme_response( 6 )
        self.assertIs( resp, nm.MOCK_THEMES_4 )


class TestGetMockSubqueries( unittest.TestCase ):

    def test_count_eight_returns_full_eight_set( self ):
        # line 299 true arm
        self.assertEqual( len( nm.get_mock_subqueries( 8 ) ), 8 )
        self.assertIs( nm.get_mock_subqueries( 8 ), nm.SAMPLE_SUBQUERIES_8 )

    def test_count_below_eight_slices_five_set( self ):
        # line 299 false arm
        self.assertEqual( len( nm.get_mock_subqueries( 3 ) ), 3 )
        self.assertEqual( nm.get_mock_subqueries( 3 ), nm.SAMPLE_SUBQUERIES_5[ :3 ] )

    def test_default_count_is_five( self ):
        self.assertEqual( len( nm.get_mock_subqueries() ), 5 )


class TestMockResearchAPIClient( unittest.IsolatedAsyncioTestCase ):

    def test_init_defaults( self ):
        client = nm.MockResearchAPIClient()
        self.assertFalse( client.debug )
        self.assertEqual( client.theme_variant, "balanced" )
        self.assertEqual( client.call_count, 0 )

    def test_init_custom( self ):
        client = nm.MockResearchAPIClient( debug=True, theme_variant="maximal" )
        self.assertTrue( client.debug )
        self.assertEqual( client.theme_variant, "maximal" )

    async def test_call_with_debug_parses_count_from_message( self ):
        # debug=True covers both `if self.debug:` true arms; regex matches "7 research topics".
        client = nm.MockResearchAPIClient( debug=True, theme_variant="balanced" )
        resp = await client.call_with_json_output(
            system_prompt="ignored",
            user_message="Cluster these 7 research topics into themes",
            call_type="theme_clustering",
        )
        self.assertIn( "themes", resp )
        self.assertEqual( client.call_count, 1 )
        # 7 → balanced → MOCK_THEMES_4
        self.assertIs( resp, nm.MOCK_THEMES_4 )

    async def test_call_without_debug_and_no_regex_match_defaults_to_five( self ):
        # debug=False covers both `if self.debug:` false arms; no "N research topics"
        # substring → regex miss → `else 5` arm → balanced 5 → 3-theme distribution.
        client = nm.MockResearchAPIClient( debug=False )
        resp = await client.call_with_json_output(
            system_prompt="ignored",
            user_message="please cluster the topics",
        )
        self.assertIn( "themes", resp )
        self.assertEqual( client.call_count, 1 )
        self.assertEqual( len( resp[ "themes" ] ), 3 )


if __name__ == "__main__":
    unittest.main()
