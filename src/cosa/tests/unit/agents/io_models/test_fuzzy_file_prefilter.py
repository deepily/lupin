"""
Unit tests for fuzzy_file_prefilter — the shared keyword narrowing used by both
the podcast-generator router and the runtime-argument-expeditor.

Covers the refactor into shared helpers (_extract_keywords /
_score_docs_by_keyword_overlap) and the new deterministic dominant-match check
(dominant_keyword_match, row 8e70a34d): when exactly one candidate holds a
strictly-unique top keyword-overlap score, resolve it WITHOUT the phi-4 LLM; a
top-score tie is ambiguous and yields None so the LLM decides.

No LLM, no network, no filesystem — pure functions over in-memory dicts.

Created 2026-08-13 by Clayton 😎 (Mr Radio crew).
"""

import unittest

from cosa.agents.io_models.utils.fuzzy_file_prefilter import (
    _extract_keywords,
    _score_docs_by_keyword_overlap,
    dominant_keyword_match,
    prefilter_docs_map_by_keywords,
    MAX_CANDIDATES,
)


class TestExtractKeywords( unittest.TestCase ):

    def test_drops_stopwords_and_short_tokens( self ):
        # "the"/"a"/"of" are stopwords; "it" is <= 2 chars → all dropped.
        self.assertEqual( _extract_keywords( "the kiss of it" ), { "kiss" } )

    def test_splits_on_path_punctuation( self ):
        # hyphen / slash / dot become word boundaries.
        self.assertEqual(
            _extract_keywords( "kiss-protocol/brevity.mandate" ),
            { "kiss", "protocol", "brevity", "mandate" },
        )

    def test_ampersand_is_stripped_not_split( self ):
        # '&' is removed (not turned into a boundary): "seek&destroy" → one token.
        self.assertEqual( _extract_keywords( "seek&destroy" ), { "seekdestroy" } )

    def test_empty_description_yields_empty_set( self ):
        self.assertEqual( _extract_keywords( "" ), set() )


class TestScoreDocsByKeywordOverlap( unittest.TestCase ):

    DOCS = {
        "io/deep-research/u/kiss-protocol.md" : "/abs/kiss.md",
        "io/deep-research/u/quantum-notes.md" : "/abs/quantum.md",
    }

    def test_scores_and_sorts_descending( self ):
        scored = _score_docs_by_keyword_overlap( self.DOCS, { "kiss", "protocol", "quantum" } )
        # kiss-protocol scores 2 (kiss+protocol), quantum scores 1 → sorted desc.
        self.assertEqual( scored[ 0 ], ( 2, "io/deep-research/u/kiss-protocol.md" ) )
        self.assertEqual( scored[ 1 ], ( 1, "io/deep-research/u/quantum-notes.md" ) )

    def test_empty_keywords_returns_empty( self ):
        self.assertEqual( _score_docs_by_keyword_overlap( self.DOCS, set() ), [] )

    def test_zero_overlap_returns_empty( self ):
        self.assertEqual( _score_docs_by_keyword_overlap( self.DOCS, { "zzz", "nomatch" } ), [] )


class TestDominantKeywordMatch( unittest.TestCase ):

    DOCS = {
        "io/deep-research/u/kiss-protocol.md" : "/abs/kiss.md",
        "io/deep-research/u/quantum-notes.md" : "/abs/quantum.md",
    }

    def test_unique_top_scorer_wins( self ):
        # "kiss protocol" → kiss-protocol scores 2, quantum 0 → unique winner.
        self.assertEqual(
            dominant_keyword_match( self.DOCS, "kiss protocol" ),
            "io/deep-research/u/kiss-protocol.md",
        )

    def test_unique_single_keyword_winner( self ):
        # A lone matching keyword still dominates when no other candidate has it.
        self.assertEqual(
            dominant_keyword_match( self.DOCS, "quantum" ),
            "io/deep-research/u/quantum-notes.md",
        )

    def test_top_score_tie_returns_none( self ):
        # "deep research" scores 2 on BOTH paths → tie → ambiguous → None.
        self.assertIsNone( dominant_keyword_match( self.DOCS, "deep research" ) )

    def test_no_keyword_signal_returns_none( self ):
        self.assertIsNone( dominant_keyword_match( self.DOCS, "the a of it" ) )

    def test_zero_overlap_returns_none( self ):
        self.assertIsNone( dominant_keyword_match( self.DOCS, "chromodynamics entanglement" ) )

    def test_dominates_within_a_large_map( self ):
        # > MAX_CANDIDATES candidates, one clearly named → still deterministic.
        big = { f"io/x/topic-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES + 40 ) }
        big[ "io/x/kiss-protocol-brevity.md" ] = "/abs/kiss.md"
        self.assertEqual(
            dominant_keyword_match( big, "kiss protocol brevity" ),
            "io/x/kiss-protocol-brevity.md",
        )


class TestPrefilterRegression( unittest.TestCase ):
    """Guard the refactor: the prefilter's public contract is unchanged."""

    def test_small_map_returned_unchanged_never_arbitrary( self ):
        small = { "io/a.md": "/abs/a.md", "io/b.md": "/abs/b.md" }
        out, arbitrary = prefilter_docs_map_by_keywords( small, "zzz nomatch" )
        self.assertIs( out, small )
        self.assertFalse( arbitrary )

    def test_large_map_narrows_on_keyword_signal( self ):
        big = { f"io/x/topic-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES + 40 ) }
        big[ "io/x/kiss-protocol.md" ] = "/abs/kiss.md"
        out, arbitrary = prefilter_docs_map_by_keywords( big, "kiss protocol", debug=True )
        self.assertLessEqual( len( out ), MAX_CANDIDATES )
        self.assertFalse( arbitrary )
        self.assertIn( "io/x/kiss-protocol.md", out )

    def test_large_map_no_signal_caps_and_flags_arbitrary( self ):
        big = { f"io/x/topic-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES + 40 ) }
        out, arbitrary = prefilter_docs_map_by_keywords( big, "the a of it", debug=True )
        self.assertEqual( len( out ), MAX_CANDIDATES )
        self.assertTrue( arbitrary )


class TestPrefilterTruncationDisclosure( unittest.TestCase ):
    """
    Row c143fd84 (found by Rio ⚡): a keyword-scored narrowing that TRUNCATES —
    len( scored ) > MAX_CANDIDATES, so a genuinely-scored target ranked past the
    50th is silently dropped — still returns arbitrary=False, telling callers the
    shortlist is a trustworthy, complete narrowing. The model then picks
    confidently from a set that CANNOT contain the answer. A truncated shortlist
    that drops a scored target MUST disclose incompleteness (arbitrary=True),
    exactly as the zero-overlap path already does.
    """

    def test_target_ranked_past_cut_is_disclosed_not_silently_trusted( self ):
        # 60 decoys each match TWO description keywords (score 2); the target
        # matches only ONE (score 1). Sorted desc, the 60 score-2 decoys fill the
        # top-50 and the target lands at rank 61 — outside scored[:MAX_CANDIDATES].
        # 60 > 50 is a deliberate margin: the target CANNOT sneak into the slice.
        docs_map = { f"io/decoy/alpha-bravo-{i}.md": f"/abs/decoy-{i}.md"
                     for i in range( MAX_CANDIDATES + 10 ) }
        target   = "io/target/charlie-notes.md"
        docs_map[ target ] = "/abs/charlie.md"

        out, arbitrary = prefilter_docs_map_by_keywords(
            docs_map, "alpha bravo charlie", debug=True
        )

        # Precondition: the target really was dropped by the top-50 truncation.
        self.assertNotIn( target, out, "target must be excluded by the cut for this case" )
        self.assertEqual( len( out ), MAX_CANDIDATES, "narrowing must truncate to the cap" )
        # The defect: it drops a scored target yet still flags the list trustworthy.
        self.assertTrue(
            arbitrary,
            "a truncated shortlist that drops a scored target must disclose "
            "incompleteness (arbitrary=True), not claim a complete narrowing",
        )


if __name__ == "__main__":
    unittest.main()
