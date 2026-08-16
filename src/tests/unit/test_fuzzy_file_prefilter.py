#!/usr/bin/env python3
"""
Unit tests for the shared fuzzy-file keyword pre-filter.

Target: cosa.agents.io_models.utils.fuzzy_file_prefilter.prefilter_docs_map_by_keywords

This is the single narrowing step used by BOTH the podcast-generator router
(match_research_docs) and the runtime-argument expeditor
(_handle_fuzzy_file_match). Without it, all markdown under the search paths is
sent to phi-4's 8k context and the request fails HTTP 400.

The function returns ( result_map, arbitrary ):
  - result_map never exceeds MAX_CANDIDATES (no-overflow invariant)
  - arbitrary is True ONLY when a LARGE map was capped with NO scoring signal —
    the caller must then ask for an exact path rather than treat the slice as a
    shortlist. A within-budget map is complete, returned unchanged, never
    arbitrary, never bails.
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
# Narrowing branch — keyword signal present (arbitrary is False)
# ============================================================================
class TestNarrowing:

    def test_narrows_large_map_to_at_most_max_candidates( self, large_map ):
        out, arbitrary = prefilter_docs_map_by_keywords( large_map, "the kiss brevity protocol", debug=True )
        assert len( out ) <= MAX_CANDIDATES
        assert out is not large_map                              # a NEW dict when narrowing
        assert arbitrary is False
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out

    def test_narrowed_keys_are_a_subset( self, large_map ):
        out, arbitrary = prefilter_docs_map_by_keywords( large_map, "unrelated topic", debug=False )
        # "unrelated topic" matches ALL 120 fixture docs (score 2 each), so the
        # scored list exceeds MAX_CANDIDATES and the narrowing TRUNCATES — a real
        # match may sit past the cut, so the shortlist is lossy and arbitrary is
        # True (row c143fd84 / commit e10ba803). The load-bearing invariant here is
        # that the kept keys are a value-preserving subset, which holds regardless.
        assert arbitrary is True
        assert set( out.keys() ).issubset( set( large_map.keys() ) )
        for k in out:
            assert out[ k ] == large_map[ k ]

    def test_higher_overlap_survives_over_lower( self, large_map ):
        out, arbitrary = prefilter_docs_map_by_keywords( large_map, "kiss protocol brevity", debug=False )
        assert arbitrary is False
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out


# ============================================================================
# Pass-through — a map already within budget is returned UNCHANGED, never bails
# ============================================================================
class TestPassThrough:

    def test_small_map_returned_unchanged( self, small_map ):
        out, arbitrary = prefilter_docs_map_by_keywords( small_map, "doc", debug=False )
        assert out is small_map
        assert arbitrary is False

    def test_small_map_zero_overlap_still_resolves_not_arbitrary( self, small_map ):
        # Mr Radio's edge: a small map with a NON-overlapping description must
        # be returned whole and must NOT bail — it is complete, not a guess.
        # (Rick's 8-doc folder must keep working today.)
        out, arbitrary = prefilter_docs_map_by_keywords( small_map, "quantum chromodynamics zzz", debug=True )
        assert out is small_map
        assert arbitrary is False

    def test_map_exactly_at_max_returned_unchanged( self ):
        exact = { f"src/a-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES ) }
        assert len( exact ) == MAX_CANDIDATES
        out, arbitrary = prefilter_docs_map_by_keywords( exact, "src", debug=False )
        assert out is exact
        assert arbitrary is False

    def test_empty_map_returned_unchanged( self ):
        empty = {}
        out, arbitrary = prefilter_docs_map_by_keywords( empty, "anything at all", debug=False )
        assert out is empty
        assert arbitrary is False


# ============================================================================
# HARD CAP + ARBITRARY FLAG — a LARGE map with no scoring signal is capped AND
# flagged so the caller asks for an exact path (f5a1ca0d + Rachel's follow-up).
# ============================================================================
class TestHardCapAndArbitrary:

    def test_no_usable_keywords_is_capped_and_arbitrary( self, large_map ):
        out, arbitrary = prefilter_docs_map_by_keywords( large_map, "the a of it is on", debug=True )
        assert len( out ) == MAX_CANDIDATES
        assert arbitrary is True
        assert set( out.keys() ).issubset( set( large_map.keys() ) )

    def test_zero_overlap_large_map_is_capped_and_arbitrary( self, large_map ):
        out, arbitrary = prefilter_docs_map_by_keywords( large_map, "quantum chromodynamics entanglement", debug=True )
        assert len( out ) == MAX_CANDIDATES
        assert arbitrary is True

    def test_arbitrary_slice_is_deterministic( self, large_map ):
        a, arb_a = prefilter_docs_map_by_keywords( large_map, "zzz nomatch qqq", debug=False )
        b, arb_b = prefilter_docs_map_by_keywords( large_map, "zzz nomatch qqq", debug=False )
        assert arb_a is True and arb_b is True
        assert list( a.keys() ) == list( b.keys() )
        assert list( a.keys() ) == sorted( large_map.keys() )[ :MAX_CANDIDATES ]


# ============================================================================
# PARTIAL-SIGNAL THIN SCORE — row 888711f0 (found by Rachel). A target sharing
# NO keyword token with the description is silently cut when a decoy scores above
# zero. On a large map the zero-overlap target never enters `scored`, so a
# shortlist built from a single incidental hit (top score 1) is trusted while the
# true target is gone. A thin top score must flag arbitrary (option 3: ask when
# the top score is weak in absolute terms). A genuine multi-token match stays
# trustworthy (c143fd84 preserved).
# ============================================================================
class TestPartialSignalThinScore:

    def test_thin_single_hit_flags_arbitrary_and_drops_zero_overlap_target( self ):
        big = { f"io/x/unrelated-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES + 10 ) }
        big[ "io/x/widget-summary.md" ] = "/abs/widget.md"   # scores 1 on "widget"
        target = "io/x/nova-briefing.md"                      # zero overlap with "widget"
        big[ target ] = "/abs/nova.md"
        out, arbitrary = prefilter_docs_map_by_keywords( big, "widget", debug=True )
        # The silent drop: the zero-overlap target is gone from the shortlist.
        assert target not in out
        # The fix: a thin best-of-one narrowing is disclosed, not trusted (888711f0).
        assert arbitrary is True

    def test_genuine_multi_token_match_stays_trustworthy( self ):
        # A two-token match is a real narrowing → still trusted (c143fd84 kept).
        big = { f"io/x/unrelated-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES + 10 ) }
        big[ "io/x/widget-gadget-report.md" ] = "/abs/wg.md"  # scores 2 on "widget gadget"
        out, arbitrary = prefilter_docs_map_by_keywords( big, "widget gadget", debug=False )
        assert arbitrary is False
        assert "io/x/widget-gadget-report.md" in out


# ============================================================================
# Input hygiene
# ============================================================================
class TestInputHygiene:

    def test_input_map_not_mutated( self, large_map ):
        before = dict( large_map )
        prefilter_docs_map_by_keywords( large_map, "kiss protocol brevity", debug=False )
        assert large_map == before

    def test_stopwords_and_short_tokens_dropped( self, large_map ):
        # "kiss" is the only usable token → still narrows on it (the KISS doc is
        # the kept candidate). But a lone incidental hit (top score 1) is a
        # best-of-list guess a zero-overlap target could beat, so it is now
        # flagged arbitrary — ask, don't trust silently (row 888711f0).
        out, arbitrary = prefilter_docs_map_by_keywords( large_map, "the kiss is of", debug=False )
        assert arbitrary is True
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out

    def test_stop_words_is_a_nonempty_set( self ):
        assert isinstance( STOP_WORDS, set ) and len( STOP_WORDS ) > 0


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
