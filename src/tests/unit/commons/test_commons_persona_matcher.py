"""
Unit tests for commons_persona_matcher.

Per AC10 minimum scope: 6+ tests covering exact, case-insensitive,
punctuation-tolerant, space-tolerant, unknown-persona (returns None),
stub-LLM-fallback invoked-on-miss.

Coverage target: 100% lines/branches/functions (AC10 commons-only mandate).
"""

from unittest.mock import MagicMock, patch

import pytest

from lupin_mcp.commons_persona_matcher import (
    _normalize_for_match,
    configure_llm_disambiguator,
    disambiguate_via_llm,
    match_persona,
)


@pytest.fixture( autouse=True )
def _reset_disambiguator_singleton():
    """Ensure each test starts with no LLM disambiguator wired (Phase 1 default)."""
    configure_llm_disambiguator( None )
    yield
    configure_llm_disambiguator( None )

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
    """_normalize_for_match strips non-alphanumeric, lowercases, and (since the
    2026-06-19 centralization onto canonical_persona_key) ALSO strips accents, so
    an accented reference matches the store's accent-free key. Previously this
    returned "maría" — the divergence that let accented personas miss the store."""
    assert _normalize_for_match( "Mr. Radio" ) == "mrradio"
    assert _normalize_for_match( "MR.RADIO" ) == "mrradio"
    assert _normalize_for_match( "" ) == ""
    assert _normalize_for_match( "..." ) == ""
    assert _normalize_for_match( "María" ) == "maria"


def test_disambiguate_via_llm_phase_1_stub_returns_none():
    """When LLM disambiguator is unset (Phase 1 default), returns None."""
    assert disambiguate_via_llm( "anything", CANDIDATES ) is None
    assert disambiguate_via_llm( "", [] ) is None


# ─── Phase 3 wiring ─────────────────────────────────────────────────────────


def test_configure_llm_disambiguator_sets_singleton():
    """`configure_llm_disambiguator(d)` installs `d` as the active disambiguator."""
    fake = MagicMock()
    fake.disambiguate = MagicMock( return_value="Mr. Radio" )
    configure_llm_disambiguator( fake )
    assert disambiguate_via_llm( "the radio guy", CANDIDATES ) == "Mr. Radio"


def test_configure_llm_disambiguator_none_restores_phase_1():
    """`configure_llm_disambiguator(None)` clears the singleton — Phase 1 stub behavior returns."""
    configure_llm_disambiguator( MagicMock( disambiguate=MagicMock( return_value="anything" ) ) )
    configure_llm_disambiguator( None )
    assert disambiguate_via_llm( "anything", CANDIDATES ) is None


def test_disambiguate_via_llm_skips_empty_candidates():
    """Even with the singleton set, empty candidate list short-circuits to None."""
    configure_llm_disambiguator( MagicMock( disambiguate=MagicMock( return_value="should not be called" ) ) )
    assert disambiguate_via_llm( "anything", [ ] ) is None


def test_disambiguate_via_llm_converts_names_to_persona_info():
    """The bridge converts candidate string list to PersonaInfo list before dispatch."""
    from lupin_mcp.commons_xml_models import PersonaInfo
    fake = MagicMock()
    fake.disambiguate = MagicMock( return_value="Mr. Radio" )
    configure_llm_disambiguator( fake )
    disambiguate_via_llm( "the radio guy", [ "Mr. Radio", "Tiberius" ] )

    # Inspect the call args — should be a list of PersonaInfo
    call_args, _ = fake.disambiguate.call_args
    personas, ambiguous_ref = call_args
    assert all( isinstance( p, PersonaInfo ) for p in personas )
    assert [ p.name for p in personas ] == [ "Mr. Radio", "Tiberius" ]
    assert ambiguous_ref == "the radio guy"
