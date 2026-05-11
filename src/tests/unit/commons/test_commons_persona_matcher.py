"""
Unit tests for commons_persona_matcher.

Per AC10 minimum scope: 6+ tests covering exact, case-insensitive,
punctuation-tolerant, space-tolerant, unknown-persona (returns None),
stub-LLM-fallback invoked-on-miss.

Coverage target: 100% lines/branches/functions (AC10 commons-only mandate).
"""

from unittest.mock import patch

from lupin_mcp.commons_persona_matcher import (
    _normalize_for_match,
    disambiguate_via_llm,
    match_persona,
)

CANDIDATES = [ "Mr. Radio", "Tiberius", "María" ]


def test_exact_match():
    """Exact display-form input matches the canonical display name."""
    assert match_persona( "Mr. Radio", CANDIDATES ) == "Mr. Radio"
    assert match_persona( "Tiberius", CANDIDATES ) == "Tiberius"


def test_case_insensitive_match():
    """Case variants match canonical form."""
    assert match_persona( "MR. RADIO", CANDIDATES ) == "Mr. Radio"
    assert match_persona( "mr. radio", CANDIDATES ) == "Mr. Radio"
    assert match_persona( "tiberius", CANDIDATES ) == "Tiberius"


def test_punctuation_tolerant_match():
    """Punctuation differences don't break the match."""
    assert match_persona( "Mr Radio", CANDIDATES ) == "Mr. Radio"
    assert match_persona( "MrRadio", CANDIDATES ) == "Mr. Radio"


def test_space_tolerant_match():
    """Whitespace variants match."""
    assert match_persona( "Mr  Radio", CANDIDATES ) == "Mr. Radio"
    assert match_persona( "mrradio", CANDIDATES ) == "Mr. Radio"
    assert match_persona( "  Mr. Radio  ", CANDIDATES ) == "Mr. Radio"


def test_unicode_match():
    """Unicode characters preserved in normalization."""
    assert match_persona( "María", CANDIDATES ) == "María"
    assert match_persona( "maría", CANDIDATES ) == "María"


def test_unknown_persona_returns_none():
    """Names not in candidate list return None (mechanical miss + Phase 1 LLM stub returns None)."""
    assert match_persona( "the radio guy", CANDIDATES ) is None
    assert match_persona( "Stranger", CANDIDATES ) is None


def test_llm_fallback_called_on_mechanical_miss():
    """When mechanical match fails, disambiguate_via_llm IS called."""
    with patch( "lupin_mcp.commons_persona_matcher.disambiguate_via_llm", return_value=None ) as mock:
        result = match_persona( "the radio guy", CANDIDATES )
        assert result is None
        mock.assert_called_once_with( "the radio guy", CANDIDATES )


def test_llm_fallback_can_return_match_phase_3_sim():
    """If LLM stub returns a match (simulating Phase 3), match_persona returns it."""
    with patch( "lupin_mcp.commons_persona_matcher.disambiguate_via_llm", return_value="Mr. Radio" ):
        assert match_persona( "the radio guy", CANDIDATES ) == "Mr. Radio"


def test_empty_input_returns_none():
    """Empty / whitespace / punctuation-only input → None."""
    assert match_persona( "", CANDIDATES ) is None
    assert match_persona( "   ", CANDIDATES ) is None
    assert match_persona( "...", CANDIDATES ) is None


def test_empty_candidates_returns_none():
    """Empty candidate list → None (no normalization or LLM call)."""
    assert match_persona( "Mr. Radio", [] ) is None


def test_normalize_for_match_helper():
    """_normalize_for_match strips non-alphanumeric and lowercases."""
    assert _normalize_for_match( "Mr. Radio" ) == "mrradio"
    assert _normalize_for_match( "MR.RADIO" ) == "mrradio"
    assert _normalize_for_match( "" ) == ""
    assert _normalize_for_match( "..." ) == ""
    assert _normalize_for_match( "María" ) == "maría"


def test_disambiguate_via_llm_phase_1_stub_returns_none():
    """Phase 1 LLM stub always returns None (regression: signature stable for Phase 3 swap)."""
    assert disambiguate_via_llm( "anything", CANDIDATES ) is None
    assert disambiguate_via_llm( "", [] ) is None
