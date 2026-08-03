#!/usr/bin/env python3
"""
Unit tests for the shared fuzzy-file keyword pre-filter.

Target: cosa.agents.io_models.utils.fuzzy_file_prefilter.prefilter_docs_map_by_keywords

This is the single narrowing step used by BOTH the podcast-generator router
(match_research_docs) and the runtime-argument expeditor
(_handle_fuzzy_file_match). Without it, all markdown under the search paths is
sent to phi-4's 8k context and the request fails HTTP 400. These tests pin
every branch of that behaviour so the two callers cannot drift.
"""

import os
import sys

import pytest

# ============================================================================
# Bootstrap PYTHONPATH
# ============================================================================
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.agents.io_models.utils.fuzzy_file_prefilter import (
    prefilter_docs_map_by_keywords,
    STOP_WORDS,
    MAX_CANDIDATES,
)


# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def large_map():
    """A map larger than MAX_CANDIDATES with one obviously-matching target."""
    m = { f"src/rnd/2026.01.0{i%9+1}-unrelated-topic-{i}.md": f"/abs/{i}.md"
          for i in range( MAX_CANDIDATES + 70 ) }
    m[ "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" ] = "/abs/kiss.md"
    return m


@pytest.fixture
def small_map():
    """A map at or below MAX_CANDIDATES."""
    return { f"src/rnd/doc-{i}.md": f"/abs/{i}.md" for i in range( 3 ) }


# ============================================================================
# Narrowing branch
# ============================================================================
class TestNarrowing:

    def test_narrows_large_map_to_at_most_max_candidates( self, large_map ):
        out = prefilter_docs_map_by_keywords( large_map, "the kiss brevity protocol", debug=True )
        assert len( out ) <= MAX_CANDIDATES
        assert out is not large_map                              # a NEW dict when narrowing
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out

    def test_narrowed_keys_are_a_subset( self, large_map ):
        out = prefilter_docs_map_by_keywords( large_map, "unrelated topic", debug=False )
        assert set( out.keys() ).issubset( set( large_map.keys() ) )
        # values are preserved verbatim for the surviving keys
        for k in out:
            assert out[ k ] == large_map[ k ]

    def test_higher_overlap_survives_over_lower( self, large_map ):
        # "kiss protocol brevity" overlaps the target on 3 tokens; decoys on 0.
        out = prefilter_docs_map_by_keywords( large_map, "kiss protocol brevity", debug=False )
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out


# ============================================================================
# Pass-through branches — a map already within budget is returned UNCHANGED
# ============================================================================
class TestPassThrough:

    def test_small_map_returned_unchanged( self, small_map ):
        assert prefilter_docs_map_by_keywords( small_map, "doc", debug=False ) is small_map

    def test_map_exactly_at_max_returned_unchanged( self ):
        exact = { f"src/a-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES ) }
        assert len( exact ) == MAX_CANDIDATES
        assert prefilter_docs_map_by_keywords( exact, "src", debug=False ) is exact

    def test_empty_map_returned_unchanged( self ):
        empty = {}
        assert prefilter_docs_map_by_keywords( empty, "anything at all", debug=False ) is empty


# ============================================================================
# HARD CAP — a large map NEVER exceeds MAX_CANDIDATES, whatever the description.
# This is the f5a1ca0d fix: no scoring signal must still cap, not fall back to
# the full map (the original context-overflow).
# ============================================================================
class TestHardCap:

    def test_no_usable_keywords_is_capped_not_full( self, large_map ):
        # All tokens are stopwords or <= 2 chars → no keywords → must STILL cap.
        out = prefilter_docs_map_by_keywords( large_map, "the a of it is on", debug=True )
        assert len( out ) == MAX_CANDIDATES
        assert out is not large_map
        assert set( out.keys() ).issubset( set( large_map.keys() ) )

    def test_zero_overlap_large_map_is_capped_not_full( self, large_map ):
        # Real keywords, none appear in any path → zero overlap → must STILL cap.
        out = prefilter_docs_map_by_keywords( large_map, "quantum chromodynamics entanglement", debug=True )
        assert len( out ) == MAX_CANDIDATES
        assert out is not large_map
        assert set( out.keys() ).issubset( set( large_map.keys() ) )

    def test_fallback_slice_is_deterministic( self, large_map ):
        # No-signal fallback must be stable across calls (sorted slice), so the
        # candidate set is reproducible rather than dict-order-dependent.
        a = prefilter_docs_map_by_keywords( large_map, "zzz nomatch qqq", debug=False )
        b = prefilter_docs_map_by_keywords( large_map, "zzz nomatch qqq", debug=False )
        assert list( a.keys() ) == list( b.keys() )
        assert list( a.keys() ) == sorted( large_map.keys() )[ :MAX_CANDIDATES ]

    def test_narrowing_also_respects_the_cap( self, large_map ):
        # The signal path is bounded by the same cap.
        out = prefilter_docs_map_by_keywords( large_map, "unrelated topic", debug=False )
        assert len( out ) <= MAX_CANDIDATES


# ============================================================================
# Input hygiene
# ============================================================================
class TestInputHygiene:

    def test_input_map_not_mutated( self, large_map ):
        before = dict( large_map )
        prefilter_docs_map_by_keywords( large_map, "kiss protocol brevity", debug=False )
        assert large_map == before

    def test_stopwords_and_short_tokens_dropped( self, large_map ):
        # "kiss" is the only usable token ("the","is" stopwords; "of" short) →
        # still narrows on it, proving the noise did not block extraction.
        out = prefilter_docs_map_by_keywords( large_map, "the kiss is of", debug=False )
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out

    def test_stop_words_is_a_nonempty_set( self ):
        assert isinstance( STOP_WORDS, set ) and len( STOP_WORDS ) > 0


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
