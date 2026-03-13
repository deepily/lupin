#!/usr/bin/env python3
"""
Unit tests for fuzzy file matching in podcast_generator router.

Tests the 3-tier validation logic in match_research_docs():
  Tier 1: Exact relative path match
  Tier 2: Bare filename exact match
  Tier 3: Fuzzy match via difflib.get_close_matches()

The fuzzy tier handles voice-transcribed input where the LLM returns
approximate filenames that don't exactly match docs_map entries.
"""

import os
import sys
import difflib
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================================
# Bootstrap PYTHONPATH
# ============================================================================

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )


# ============================================================================
# Test the 3-tier validation logic (extracted from match_research_docs)
# ============================================================================

def _validate_matches( matches, docs_map, debug=False ):
    """
    Extract of the 3-tier validation logic from match_research_docs().

    This replicates the exact validation code so we can test it in isolation
    without needing an LLM or filesystem.

    Args:
        matches: List of filename strings (from LLM response)
        docs_map: Dict of { relative_path: absolute_path }
        debug: Enable debug output

    Returns:
        List of dicts with 'filename' and 'relative_path' keys
    """
    valid_matches = []
    all_rel_paths = list( docs_map.keys() )
    all_basenames = [ os.path.basename( p ) for p in all_rel_paths ]

    for m in matches:
        # Tier 1: Direct relative path match
        if m in docs_map:
            valid_matches.append( { "filename": os.path.basename( m ), "relative_path": m } )
            continue

        # Tier 2: Bare filename exact match
        tier2_found = False
        for rel_path in all_rel_paths:
            if os.path.basename( rel_path ) == m:
                valid_matches.append( { "filename": m, "relative_path": rel_path } )
                tier2_found = True
                break
        if tier2_found:
            continue

        # Tier 3: Fuzzy match against both relative paths and bare filenames
        fuzzy_path_hits = difflib.get_close_matches( m, all_rel_paths, n=1, cutoff=0.6 )
        if fuzzy_path_hits:
            best = fuzzy_path_hits[ 0 ]
            if debug: print( f"[fuzzy] Path match: '{m}' → '{best}'" )
            valid_matches.append( { "filename": os.path.basename( best ), "relative_path": best } )
            continue

        fuzzy_name_hits = difflib.get_close_matches( m, all_basenames, n=1, cutoff=0.6 )
        if fuzzy_name_hits:
            best_name = fuzzy_name_hits[ 0 ]
            for rel_path in all_rel_paths:
                if os.path.basename( rel_path ) == best_name:
                    if debug: print( f"[fuzzy] Name match: '{m}' → '{best_name}'" )
                    valid_matches.append( { "filename": best_name, "relative_path": rel_path } )
                    break

    return valid_matches


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_docs_map():
    """Sample docs_map simulating a user's research directory."""
    return {
        "io/deep-research/user@test.com/2026.01.15-trust-proxy-overview.md"   : "/var/lupin/io/deep-research/user@test.com/2026.01.15-trust-proxy-overview.md",
        "io/deep-research/user@test.com/2026.02.10-ai-safety-analysis.md"     : "/var/lupin/io/deep-research/user@test.com/2026.02.10-ai-safety-analysis.md",
        "io/deep-research/user@test.com/2026.02.20-claude-code-workflows.md"  : "/var/lupin/io/deep-research/user@test.com/2026.02.20-claude-code-workflows.md",
        "src/rnd/2026.02.23-trust-proxy-preference-learning/overview.md"      : "/var/lupin/src/rnd/2026.02.23-trust-proxy-preference-learning/overview.md",
        "src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md"        : "/var/lupin/src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md",
    }


# ============================================================================
# Tier 1: Exact Relative Path Match
# ============================================================================

class TestTier1ExactPathMatch:
    """Tests for exact relative path matching (Tier 1)."""

    def test_exact_path_match( self, sample_docs_map ):
        """LLM returns the exact relative path."""
        matches = [ "io/deep-research/user@test.com/2026.01.15-trust-proxy-overview.md" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert result[ 0 ][ "relative_path" ] == "io/deep-research/user@test.com/2026.01.15-trust-proxy-overview.md"
        assert result[ 0 ][ "filename" ] == "2026.01.15-trust-proxy-overview.md"

    def test_multiple_exact_matches( self, sample_docs_map ):
        """LLM returns multiple exact relative paths."""
        matches = [
            "io/deep-research/user@test.com/2026.01.15-trust-proxy-overview.md",
            "io/deep-research/user@test.com/2026.02.10-ai-safety-analysis.md",
        ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 2


# ============================================================================
# Tier 2: Bare Filename Match
# ============================================================================

class TestTier2BareFilenameMatch:
    """Tests for bare filename matching (Tier 2)."""

    def test_bare_filename_match( self, sample_docs_map ):
        """LLM returns just the filename without directory path."""
        matches = [ "2026.01.15-trust-proxy-overview.md" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert result[ 0 ][ "filename" ] == "2026.01.15-trust-proxy-overview.md"
        assert "io/deep-research" in result[ 0 ][ "relative_path" ]

    def test_bare_filename_from_rnd( self, sample_docs_map ):
        """LLM returns just the filename from src/rnd directory."""
        matches = [ "overview.md" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert "trust-proxy-preference-learning" in result[ 0 ][ "relative_path" ]


# ============================================================================
# Tier 3: Fuzzy Match (NEW — fixes Bug #1)
# ============================================================================

class TestTier3FuzzyMatch:
    """Tests for fuzzy matching via difflib (Tier 3)."""

    def test_fuzzy_match_slight_typo( self, sample_docs_map ):
        """LLM returns filename with slight typo — fuzzy matches."""
        matches = [ "2026.01.15-trust-proxy-overvew.md" ]  # 'overvew' instead of 'overview'
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert "trust-proxy-overview" in result[ 0 ][ "relative_path" ]

    def test_fuzzy_match_missing_date_prefix( self, sample_docs_map ):
        """LLM returns filename without date prefix — fuzzy matches."""
        matches = [ "trust-proxy-overview.md" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert "trust-proxy-overview" in result[ 0 ][ "relative_path" ]

    def test_fuzzy_match_partial_path( self, sample_docs_map ):
        """LLM returns partial path — fuzzy matches against full relative paths."""
        matches = [ "deep-research/user@test.com/2026.02.10-ai-safety-analysis.md" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert "ai-safety-analysis" in result[ 0 ][ "relative_path" ]

    def test_fuzzy_match_voice_paraphrase( self, sample_docs_map ):
        """Voice input produces approximate filename — fuzzy matches."""
        matches = [ "2026.02.20-claude-code-workflow.md" ]  # Missing 's' at end
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 1
        assert "claude-code-workflows" in result[ 0 ][ "relative_path" ]

    def test_fuzzy_match_too_distant_returns_nothing( self, sample_docs_map ):
        """Completely unrelated string should NOT match (cutoff=0.6)."""
        matches = [ "completely-unrelated-topic.md" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 0

    def test_fuzzy_match_description_not_filename( self, sample_docs_map ):
        """LLM returns a description instead of filename — should not match."""
        matches = [ "the trust proxy research document" ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 0

    def test_mixed_tiers( self, sample_docs_map ):
        """Mix of exact, bare filename, and fuzzy matches."""
        matches = [
            "io/deep-research/user@test.com/2026.01.15-trust-proxy-overview.md",  # Tier 1
            "2026.02.10-ai-safety-analysis.md",                                    # Tier 2
            "2026.02.20-claude-code-workflow.md",                                   # Tier 3 (fuzzy)
        ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 3


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case tests for the validation logic."""

    def test_empty_matches_list( self, sample_docs_map ):
        """Empty matches list returns empty result."""
        result = _validate_matches( [], sample_docs_map )
        assert result == []

    def test_empty_docs_map( self ):
        """Empty docs_map returns empty result."""
        result = _validate_matches( [ "some-file.md" ], {} )
        assert result == []

    def test_duplicate_matches_preserved( self, sample_docs_map ):
        """If LLM returns same file twice, both entries are kept."""
        matches = [
            "2026.01.15-trust-proxy-overview.md",
            "2026.01.15-trust-proxy-overview.md",
        ]
        result = _validate_matches( matches, sample_docs_map )
        assert len( result ) == 2


# ============================================================================
# Test 5: Keyword pre-filter logic (mirrors podcast_generator.py pre-filter)
# ============================================================================

class TestKeywordPreFilter:
    """Verify keyword pre-filtering narrows candidate list correctly."""

    STOP_WORDS = {
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
        "my", "your", "that", "this", "it", "is", "was", "be", "can", "do",
        "no", "not", "if", "see", "find", "look", "get", "you", "me", "i",
        "about", "from", "with", "up", "out", "so", "just", "like", "also",
        "document", "file", "directory", "folder", "please", "could", "would",
    }

    def _extract_keywords( self, description ):
        return set(
            w for w in description.lower().replace( "-", " " ).replace( "/", " " ).replace( ".", " " ).replace( "&", "" ).split()
            if w not in self.STOP_WORDS and len( w ) > 2
        )

    def _score_path( self, rel_path, keywords ):
        path_lower = rel_path.lower().replace( "-", " " ).replace( "/", " " ).replace( "_", " " ).replace( ".", " " )
        path_words = set( path_lower.split() )
        return len( keywords & path_words )

    def test_voice_transcription_extracts_useful_keywords( self ):
        """Voice noise like 'no no no' is filtered; content words survive."""
        desc = "See if you can find that document in my end-to-end trust proxy overview in my R&D or the COSA No no no Lupine R&D directory"
        keywords = self._extract_keywords( desc )
        # Content words survive
        assert "trust" in keywords
        assert "proxy" in keywords
        assert "overview" in keywords
        assert "end" in keywords
        # Noise/stopwords removed
        assert "no" not in keywords
        assert "see" not in keywords
        assert "find" not in keywords
        assert "my" not in keywords
        assert "document" not in keywords

    def test_target_file_scores_highest( self ):
        """The intended file scores higher than unrelated files."""
        desc = "end-to-end trust proxy overview in R&D"
        keywords = self._extract_keywords( desc )

        target = "src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.27-end-to-end-trust-proxy-overview.md"
        decoy1 = "src/cosa/agents/podcast_generator/orchestrator.py"
        decoy2 = "src/rnd/2026.01.10-some-unrelated-topic.md"
        decoy3 = "src/docs/websocket-architecture.md"

        target_score = self._score_path( target, keywords )
        decoy1_score = self._score_path( decoy1, keywords )
        decoy2_score = self._score_path( decoy2, keywords )
        decoy3_score = self._score_path( decoy3, keywords )

        assert target_score >= 4  # trust, proxy, overview, end, rnd
        assert target_score > decoy1_score
        assert target_score > decoy2_score
        assert target_score > decoy3_score

    def test_zero_score_files_excluded( self ):
        """Files with zero keyword overlap are excluded from candidates."""
        keywords = { "trust", "proxy", "overview" }
        assert self._score_path( "src/cosa/utils/util.py", keywords ) == 0
        assert self._score_path( "src/rnd/2026.02.27-end-to-end-trust-proxy-overview.md", keywords ) >= 2


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
