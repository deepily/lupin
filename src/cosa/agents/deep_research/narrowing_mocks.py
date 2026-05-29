#!/usr/bin/env python3
"""
Mock Responses for Progressive Narrowing Test Harness.

Provides canned theme clustering responses for testing the progressive
narrowing phase without making API calls.

Usage:
    from .narrowing_mocks import MOCK_THEMES_3, get_mock_theme_response

    # Get a specific mock response
    themes = MOCK_THEMES_3

    # Get mock response for a given number of subqueries
    response = get_mock_theme_response( len( subqueries ) )
"""

from typing import Optional


# =============================================================================
# Canned Theme Clustering Responses
# =============================================================================

MOCK_THEMES_3 = {
    "themes": [
        {
            "name"             : "Core Concepts",
            "description"      : "Fundamental architecture and design philosophy",
            "subquery_indices" : [ 0, 1 ]
        },
        {
            "name"             : "Performance",
            "description"      : "Benchmarks and optimization characteristics",
            "subquery_indices" : [ 2 ]
        },
        {
            "name"             : "Ecosystem",
            "description"      : "Community, tooling, and learning resources",
            "subquery_indices" : [ 3, 4 ]
        }
    ]
}

MOCK_THEMES_4 = {
    "themes": [
        {
            "name"             : "Architecture",
            "description"      : "Core design patterns and structure",
            "subquery_indices" : [ 0, 1 ]
        },
        {
            "name"             : "Technical Metrics",
            "description"      : "Performance and scalability benchmarks",
            "subquery_indices" : [ 2, 3 ]
        },
        {
            "name"             : "Developer Experience",
            "description"      : "Learning curve and documentation",
            "subquery_indices" : [ 4, 5 ]
        },
        {
            "name"             : "Adoption Factors",
            "description"      : "Community size and job market",
            "subquery_indices" : [ 6, 7 ]
        }
    ]
}

MOCK_THEMES_6 = {
    "themes": [
        {
            "name"             : "Architecture",
            "description"      : "Core design and patterns",
            "subquery_indices" : [ 0 ]
        },
        {
            "name"             : "Performance",
            "description"      : "Speed and optimization",
            "subquery_indices" : [ 1 ]
        },
        {
            "name"             : "Scalability",
            "description"      : "Growth and enterprise readiness",
            "subquery_indices" : [ 2 ]
        },
        {
            "name"             : "Developer Tools",
            "description"      : "IDE support and debugging",
            "subquery_indices" : [ 3 ]
        },
        {
            "name"             : "Community",
            "description"      : "Support and resources",
            "subquery_indices" : [ 4 ]
        },
        {
            "name"             : "Future Outlook",
            "description"      : "Roadmap and trends",
            "subquery_indices" : [ 5 ]
        }
    ]
}

# Minimal response - forces single theme auto-select path
MOCK_THEMES_1 = {
    "themes": [
        {
            "name"             : "All Topics",
            "description"      : "All research topics grouped together",
            "subquery_indices" : [ 0, 1, 2, 3, 4 ]
        }
    ]
}

# Empty response - triggers fallback path
MOCK_THEMES_EMPTY = {
    "themes": []
}


# =============================================================================
# Sample Subquery Sets for Testing
# =============================================================================

SAMPLE_SUBQUERIES_5 = [
    {
        "topic"         : "React core concepts",
        "objective"     : "Summarize React's key features and virtual DOM architecture",
        "output_format" : "structured summary",
        "priority"      : 1
    },
    {
        "topic"         : "Vue core concepts",
        "objective"     : "Summarize Vue's reactivity system and component model",
        "output_format" : "structured summary",
        "priority"      : 1
    },
    {
        "topic"         : "Performance benchmarks",
        "objective"     : "Compare recent performance metrics between React and Vue",
        "output_format" : "comparison table",
        "priority"      : 2
    },
    {
        "topic"         : "Community and ecosystem",
        "objective"     : "Analyze community size, package ecosystem, and job market",
        "output_format" : "comparison summary",
        "priority"      : 2
    },
    {
        "topic"         : "Learning curve",
        "objective"     : "Compare documentation quality and time to proficiency",
        "output_format" : "analysis with recommendations",
        "priority"      : 3
    }
]

SAMPLE_SUBQUERIES_8 = [
    {
        "topic"         : "Python architecture",
        "objective"     : "Core language design and philosophy",
        "output_format" : "summary",
        "priority"      : 1
    },
    {
        "topic"         : "Rust architecture",
        "objective"     : "Memory safety model and ownership",
        "output_format" : "summary",
        "priority"      : 1
    },
    {
        "topic"         : "Python performance",
        "objective"     : "Benchmark data and optimization techniques",
        "output_format" : "metrics",
        "priority"      : 2
    },
    {
        "topic"         : "Rust performance",
        "objective"     : "Zero-cost abstractions and compile-time optimizations",
        "output_format" : "metrics",
        "priority"      : 2
    },
    {
        "topic"         : "Python tooling",
        "objective"     : "IDE support, debuggers, and package management",
        "output_format" : "comparison",
        "priority"      : 3
    },
    {
        "topic"         : "Rust tooling",
        "objective"     : "Cargo, rust-analyzer, and debugging tools",
        "output_format" : "comparison",
        "priority"      : 3
    },
    {
        "topic"         : "Python adoption",
        "objective"     : "Industry usage, job market, and community",
        "output_format" : "statistics",
        "priority"      : 4
    },
    {
        "topic"         : "Rust adoption",
        "objective"     : "Growth trends, major users, and community",
        "output_format" : "statistics",
        "priority"      : 4
    }
]


# =============================================================================
# Mock Response Functions
# =============================================================================

def get_mock_theme_response( num_subqueries: int, variant: str = "balanced" ) -> dict:
    """
    Get an appropriate mock theme response for the given number of subqueries.

    Requires:
        - num_subqueries is a positive integer
        - variant is one of: "balanced", "minimal", "maximal", "empty"

    Ensures:
        - Returns a dict with "themes" key containing themed subquery groupings
        - Subquery indices in the response are valid for the given count

    Args:
        num_subqueries: Number of subqueries to theme
        variant: Which mock variant to return

    Returns:
        dict: Mock theme clustering response
    """
    if variant == "empty":
        return MOCK_THEMES_EMPTY

    if variant == "minimal" or num_subqueries <= 3:
        return MOCK_THEMES_1

    if variant == "maximal" or num_subqueries >= 8:
        # Adjust MOCK_THEMES_6 indices to fit actual subquery count
        themes = []
        indices_per_theme = max( 1, num_subqueries // 6 )
        current_idx = 0

        for i, theme in enumerate( MOCK_THEMES_6[ "themes" ] ):
            if i == 5:  # Last theme gets remaining indices
                indices = list( range( current_idx, num_subqueries ) )
            else:
                indices = list( range( current_idx, min( current_idx + indices_per_theme, num_subqueries ) ) )
                current_idx += indices_per_theme

            if indices:  # Only add themes that have indices
                themes.append( {
                    "name"             : theme[ "name" ],
                    "description"      : theme[ "description" ],
                    "subquery_indices" : indices
                } )

        return { "themes": themes }

    # Default balanced distribution
    if num_subqueries <= 5:
        # Use 3 themes
        return {
            "themes": [
                {
                    "name"             : "Core Concepts",
                    "description"      : "Fundamental architecture and design",
                    "subquery_indices" : list( range( min( 2, num_subqueries ) ) )
                },
                {
                    "name"             : "Technical Comparison",
                    "description"      : "Performance and metrics",
                    "subquery_indices" : [ 2 ] if num_subqueries > 2 else []
                },
                {
                    "name"             : "Ecosystem",
                    "description"      : "Community and tooling",
                    "subquery_indices" : list( range( 3, num_subqueries ) )
                }
            ]
        }
    else:
        # Use 4 themes for 6-7 subqueries
        return MOCK_THEMES_4


def get_mock_subqueries( count: int = 5 ) -> list:
    """
    Get sample subqueries for testing.

    Args:
        count: Number of subqueries to return (5 or 8)

    Returns:
        list: Sample subquery dicts
    """
    if count >= 8:
        return SAMPLE_SUBQUERIES_8
    return SAMPLE_SUBQUERIES_5[ :count ]


# =============================================================================
# Mock API Client for Testing
# =============================================================================

class MockResearchAPIClient:
    """
    Mock API client for testing narrowing harness without real API calls.

    Implements only the methods needed for narrowing:
    - call_with_json_output: Returns mock theme clustering

    Usage:
        mock_client = MockResearchAPIClient()
        harness = NarrowingHarness( api_client=mock_client, mock_mode=True )
    """

    def __init__( self, debug: bool = False, theme_variant: str = "balanced" ):
        """
        Initialize mock API client.

        Args:
            debug: Enable debug output
            theme_variant: Which mock variant to use (balanced/minimal/maximal/empty)
        """
        self.debug         = debug
        self.theme_variant = theme_variant
        self.call_count    = 0

    async def call_with_json_output(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[ str ] = None,
        call_type: str = "structured",
        max_tokens: int = 4096
    ) -> dict:
        """
        Mock API call that returns canned theme clustering response.

        Args:
            system_prompt: Ignored in mock
            user_message: Parsed to determine subquery count
            model: Ignored in mock
            call_type: Used to determine response type
            max_tokens: Ignored in mock

        Returns:
            dict: Mock theme clustering response
        """
        self.call_count += 1

        if self.debug:
            print( f"[MockAPIClient] Call #{self.call_count} type={call_type}" )

        # Parse subquery count from user message if possible
        # Format: "Cluster these N research topics..."
        import re
        match = re.search( r"(\d+) research topics", user_message )
        num_subqueries = int( match.group( 1 ) ) if match else 5

        if self.debug:
            print( f"[MockAPIClient] Detected {num_subqueries} subqueries, variant={self.theme_variant}" )

        return get_mock_theme_response( num_subqueries, self.theme_variant )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for narrowing mocks."""
    import cosa.utils.util as cu

    cu.print_banner( "Narrowing Mocks Smoke Test", prepend_nl=True )

    try:
        # Test 1: Mock theme responses exist
        print( "Testing mock theme responses..." )
        assert len( MOCK_THEMES_3[ "themes" ] ) == 3
        assert len( MOCK_THEMES_4[ "themes" ] ) == 4
        assert len( MOCK_THEMES_6[ "themes" ] ) == 6
        assert len( MOCK_THEMES_1[ "themes" ] ) == 1
        assert len( MOCK_THEMES_EMPTY[ "themes" ] ) == 0
        print( "✓ All mock theme responses defined" )

        # Test 2: Sample subqueries
        print( "Testing sample subqueries..." )
        assert len( SAMPLE_SUBQUERIES_5 ) == 5
        assert len( SAMPLE_SUBQUERIES_8 ) == 8
        assert all( "topic" in sq for sq in SAMPLE_SUBQUERIES_5 )
        print( "✓ Sample subqueries available" )

        # Test 3: get_mock_theme_response function
        print( "Testing get_mock_theme_response..." )
        response_3 = get_mock_theme_response( 3 )
        assert "themes" in response_3
        print( f"  - 3 subqueries: {len( response_3[ 'themes' ] )} themes" )

        response_5 = get_mock_theme_response( 5 )
        assert "themes" in response_5
        print( f"  - 5 subqueries: {len( response_5[ 'themes' ] )} themes" )

        response_8 = get_mock_theme_response( 8 )
        assert "themes" in response_8
        print( f"  - 8 subqueries: {len( response_8[ 'themes' ] )} themes" )
        print( "✓ get_mock_theme_response works" )

        # Test 4: Variant responses
        print( "Testing variant responses..." )
        empty = get_mock_theme_response( 5, "empty" )
        assert empty[ "themes" ] == []

        minimal = get_mock_theme_response( 5, "minimal" )
        assert len( minimal[ "themes" ] ) == 1
        print( "✓ Variants work correctly" )

        # Test 5: MockResearchAPIClient
        print( "Testing MockResearchAPIClient..." )
        import asyncio

        async def test_mock_client():
            client = MockResearchAPIClient( debug=True )
            response = await client.call_with_json_output(
                system_prompt = "test",
                user_message  = "Cluster these 5 research topics...",
                call_type     = "theme_clustering"
            )
            return response

        response = asyncio.run( test_mock_client() )
        assert "themes" in response
        print( "✓ MockResearchAPIClient works" )

        # Test 6: get_mock_subqueries
        print( "Testing get_mock_subqueries..." )
        subqueries_5 = get_mock_subqueries( 5 )
        assert len( subqueries_5 ) == 5
        subqueries_8 = get_mock_subqueries( 8 )
        assert len( subqueries_8 ) == 8
        print( "✓ get_mock_subqueries works" )

        print( "\n✓ Narrowing mocks smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
