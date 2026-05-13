"""
Unit tests for `lupin_mcp.commons_llm_disambiguator` (Phase 3 step 5).

Coverage targets: 100% lines + branches + functions on the disambiguator
module. All LLM calls mocked via `LlmClientFactory` patching.

Per AC6 + AC7 + T2 + T7 of
`src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`.
"""

from unittest.mock import MagicMock, patch

import pytest

from lupin_mcp.commons_llm_disambiguator import (
    _DEFAULT_CONFIDENCE_FLOOR,
    _DEFAULT_TIMEOUT_SECONDS,
    _SYSTEM_PROMPT,
    CommonsLlmDisambiguator,
)
from lupin_mcp.commons_xml_models import PersonaInfo


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _make_config_mgr( overrides=None ):
    """Build a stub config_mgr exposing `.get(key, default=None)`."""
    overrides = overrides or { }
    defaults = {
        "llm spec key for commons persona disambiguator"  : "kaitchup/phi_4_14b",
        "commons llm disambiguator fallback model name"   : "claude-haiku-4-5",
        "commons llm disambiguator timeout seconds"       : 5,
        "commons llm disambiguator confidence floor"      : 0.7,
        "commons llm disambiguator log decisions"         : False,
    }
    defaults.update( overrides )

    mgr = MagicMock()
    def _get( key, default=None ):
        return defaults.get( key, default )
    mgr.get = _get
    return mgr


@pytest.fixture
def config_mgr():
    return _make_config_mgr()


@pytest.fixture
def sample_personas():
    return [
        PersonaInfo( name="Rachel",   icon="🎸" ),
        PersonaInfo( name="Tiberius", icon="🌑" ),
        PersonaInfo( name="Rio",      icon="⚡" ),
        PersonaInfo( name="Maria",    icon="🌸" ),
    ]


def _mock_response_xml( matched_persona: str = None, confidence: float = 0.0 ) -> str:
    """Build a valid <persona_disambiguation_response> XML payload."""
    tag = (
        f"<matched_persona>{matched_persona}</matched_persona>"
        if matched_persona is not None
        else "<matched_persona/>"
    )
    return (
        f"<persona_disambiguation_response>{tag}"
        f"<confidence>{confidence}</confidence>"
        f"</persona_disambiguation_response>"
    )


def _patch_factory( client_mock: MagicMock ):
    """
    Patch `LlmClientFactory` so its `get_client(...)` returns `client_mock`.
    Yields the patcher context.
    """
    fake_factory = MagicMock()
    fake_factory.get_client = MagicMock( return_value=client_mock )
    return patch(
        "lupin_mcp.commons_llm_disambiguator.LlmClientFactory",
        return_value=fake_factory,
    )


# ─── Construction ───────────────────────────────────────────────────────────


def test_construction_reads_ini_keys( config_mgr ):
    """Constructor reads spec key + thresholds + audit toggle from config_mgr."""
    d = CommonsLlmDisambiguator( config_mgr )
    assert d.llm_spec_key      == "kaitchup/phi_4_14b"
    assert d.confidence_floor  == 0.7
    assert d.timeout_seconds   == 5.0
    assert d.log_decisions     is False
    assert d.debug             is False
    assert d.verbose           is False


def test_construction_uses_defaults_when_missing():
    """Missing optional INI keys → built-in defaults (floor 0.7, timeout 5.0)."""
    mgr = MagicMock()
    mgr.get = lambda key, default=None: default if key != "llm spec key for commons persona disambiguator" else "spec-key"
    d = CommonsLlmDisambiguator( mgr )
    assert d.confidence_floor == _DEFAULT_CONFIDENCE_FLOOR
    assert d.timeout_seconds  == _DEFAULT_TIMEOUT_SECONDS
    assert d.log_decisions    is False


def test_construction_honors_debug_verbose( config_mgr ):
    """debug + verbose flags propagated."""
    d = CommonsLlmDisambiguator( config_mgr, debug=True, verbose=True )
    assert d.debug   is True
    assert d.verbose is True


# ─── Lazy client construction ───────────────────────────────────────────────


def test_lazy_client_constructed_on_first_use( config_mgr, sample_personas ):
    """`_get_client()` lazily creates + caches the LLM client."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.9 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d._client is None  # not yet constructed
        result = d.disambiguate( sample_personas, "Rachel" )
        assert d._client is client      # constructed + cached
        # Calling again does NOT re-build the client
        d.disambiguate( sample_personas, "Rachel" )
        assert d._client is client


# ─── Successful matching ────────────────────────────────────────────────────


def test_high_confidence_match_returns_canonical_name( config_mgr, sample_personas ):
    """High-confidence match → returns the canonical persona name."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.92 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        result = d.disambiguate( sample_personas, "the Rachel session" )
        assert result == "Rachel"


def test_prompt_contains_system_directive_and_request_xml( config_mgr, sample_personas ):
    """The LLM prompt is system-prompt + the request XML envelope."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Maria", 0.85 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        d.disambiguate( sample_personas, "the M session" )

    sent_prompt = client.run.call_args[ 0 ][ 0 ]
    assert _SYSTEM_PROMPT in sent_prompt
    assert "<commons_persona_disambiguation>"  in sent_prompt
    assert "<ambiguous_reference>the M session</ambiguous_reference>" in sent_prompt


def test_context_included_in_prompt_when_provided( config_mgr, sample_personas ):
    """Optional context block is included in the request XML when provided."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Tiberius", 0.8 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        d.disambiguate( sample_personas, "the T session", context="user asked about scheduling" )

    sent = client.run.call_args[ 0 ][ 0 ]
    assert "<context>user asked about scheduling</context>" in sent


# ─── Confidence floor (F5-fit) ──────────────────────────────────────────────


def test_below_floor_returns_none( config_mgr, sample_personas ):
    """confidence < floor (default 0.7) → returns None."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.5 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "the R session" ) is None


def test_custom_floor_via_ini( sample_personas ):
    """floor INI key override is honored."""
    mgr = _make_config_mgr( { "commons llm disambiguator confidence floor": 0.95 } )
    client = MagicMock()
    # 0.90 < 0.95 → below floor → None
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.90 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( mgr )
        assert d.disambiguate( sample_personas, "the R session" ) is None


def test_at_floor_accepts( config_mgr, sample_personas ):
    """confidence == floor passes (strict `<` rejection)."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.7 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "the R session" ) == "Rachel"


# ─── T2 whitelist ───────────────────────────────────────────────────────────


def test_t2_whitelist_rejects_non_canonical( config_mgr, sample_personas ):
    """matched_persona not in active_personas → returns None (T2)."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Cleopatra", 0.95 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "the C session" ) is None


def test_explicit_no_match( config_mgr, sample_personas ):
    """Empty <matched_persona/> → None even if confidence is high."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( None, 0.9 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        # confidence 0.9 >= floor 0.7 → falls through to return matched (which is None)
        assert d.disambiguate( sample_personas, "the unknown session" ) is None


# ─── Input ValidationError ──────────────────────────────────────────────────


def test_input_validation_error_returns_none( config_mgr, sample_personas ):
    """
    Invalid input (e.g. control char in ambiguous_reference) → caught,
    debug-logged, returns None. LLM is NOT called.
    """
    client = MagicMock()

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr, debug=True )
        result = d.disambiguate( sample_personas, "bad\x00inject" )
    assert result is None
    client.run.assert_not_called()


def test_input_validation_error_oversize( config_mgr, sample_personas ):
    """ambiguous_reference > 256 chars → returns None without LLM call."""
    client = MagicMock()

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "x" * 257 ) is None
    client.run.assert_not_called()


# ─── LLM error paths → Haiku fallback (stubbed) → None ──────────────────────


def test_phi4_timeout_routes_to_haiku_fallback_returns_none( config_mgr, sample_personas ):
    """PHI-4 raises TimeoutError → routed to Haiku stub → caught → None."""
    client = MagicMock()
    client.run = MagicMock( side_effect=TimeoutError( "PHI-4 timeout" ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr, debug=True )
        assert d.disambiguate( sample_personas, "the R session" ) is None


def test_phi4_parse_error_routes_to_haiku_fallback( config_mgr, sample_personas ):
    """PHI-4 returns garbage → XMLParsingError → Haiku stub → None."""
    client = MagicMock()
    client.run = MagicMock( return_value="this is not XML at all" )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "the R session" ) is None


def test_phi4_validation_error_routes_to_haiku( config_mgr, sample_personas ):
    """PHI-4 returns XML with out-of-range confidence → ValidationError → None."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 1.5 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "the R session" ) is None


def test_phi4_value_error_routes_to_haiku( config_mgr, sample_personas ):
    """PHI-4 raises generic ValueError → routes to Haiku → None."""
    client = MagicMock()
    client.run = MagicMock( side_effect=ValueError( "bad response shape" ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        assert d.disambiguate( sample_personas, "the R session" ) is None


def test_haiku_fallback_raises_not_implemented( config_mgr, sample_personas ):
    """The stubbed fallback raises NotImplementedError when called directly."""
    with _patch_factory( MagicMock() ):
        d = CommonsLlmDisambiguator( config_mgr )
        with pytest.raises( NotImplementedError, match="Haiku fallback stubbed" ):
            d._fallback_via_haiku( sample_personas, "the R session" )


# ─── T7 decision audit log ──────────────────────────────────────────────────


def test_t7_log_emits_on_accepted_match( sample_personas, capsys ):
    """When log_decisions=True, accepted matches emit a decision record."""
    mgr = _make_config_mgr( { "commons llm disambiguator log decisions": True } )
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.95 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( mgr )
        d.disambiguate( sample_personas, "the R session" )

    out = capsys.readouterr().out
    assert "decision outcome=accepted" in out
    assert "matched='Rachel'"          in out
    assert "confidence=0.950"          in out


def test_t7_log_emits_on_below_floor( sample_personas, capsys ):
    """When log_decisions=True, below-floor decisions emit a record."""
    mgr = _make_config_mgr( { "commons llm disambiguator log decisions": True } )
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.5 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( mgr )
        d.disambiguate( sample_personas, "the R session" )

    out = capsys.readouterr().out
    assert "decision outcome=below-floor" in out


def test_t7_log_emits_on_whitelist_miss( sample_personas, capsys ):
    """When log_decisions=True, whitelist-miss emits a record."""
    mgr = _make_config_mgr( { "commons llm disambiguator log decisions": True } )
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Cleopatra", 0.95 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( mgr )
        d.disambiguate( sample_personas, "the C session" )

    out = capsys.readouterr().out
    assert "decision outcome=whitelist-miss" in out


def test_t7_log_silent_by_default( config_mgr, sample_personas, capsys ):
    """When log_decisions=False (default), no audit record is emitted."""
    client = MagicMock()
    client.run = MagicMock( return_value=_mock_response_xml( "Rachel", 0.95 ) )

    with _patch_factory( client ):
        d = CommonsLlmDisambiguator( config_mgr )
        d.disambiguate( sample_personas, "the R session" )

    out = capsys.readouterr().out
    assert "decision outcome" not in out
