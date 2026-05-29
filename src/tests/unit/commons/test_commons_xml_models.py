"""
Unit tests for `lupin_mcp.commons_xml_models` (Phase 3 step 4).

Per §8 PHI-4 prompt envelope of
`src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`.

Coverage targets: 100% lines + branches + functions on the model module.
"""

import pytest
from pydantic import ValidationError

from lupin_mcp.commons_xml_models import (
    PersonaDisambiguationRequest,
    PersonaDisambiguationResponse,
    PersonaInfo,
    _t2_sanitize,
    _xml_escape,
)


# ─── _xml_escape ────────────────────────────────────────────────────────────


def test_xml_escape_orders_ampersand_first():
    """Ampersand replaced before `<`/`>` so `&lt;` doesn't become `&amp;lt;`."""
    assert _xml_escape( "a & b" )         == "a &amp; b"
    assert _xml_escape( "a < b" )         == "a &lt; b"
    assert _xml_escape( "a > b" )         == "a &gt; b"
    assert _xml_escape( "<tag>" )         == "&lt;tag&gt;"
    assert _xml_escape( "a & <b> & >c<" ) == "a &amp; &lt;b&gt; &amp; &gt;c&lt;"


def test_xml_escape_passthrough_alphanumeric():
    """Plain alphanumeric strings are unchanged."""
    assert _xml_escape( "hello world" )  == "hello world"
    assert _xml_escape( "" )             == ""
    assert _xml_escape( "Maria 🌸" )     == "Maria 🌸"


# ─── _t2_sanitize ───────────────────────────────────────────────────────────


def test_t2_sanitize_passes_none_through():
    """None input → None output (Optional fields)."""
    assert _t2_sanitize( None ) is None


def test_t2_sanitize_escapes_xml_chars():
    """Valid input is XML-escaped."""
    assert _t2_sanitize( "a < b & c > d" ) == "a &lt; b &amp; c &gt; d"


def test_t2_sanitize_allows_newline_and_tab():
    """Newline + tab are NOT considered control chars."""
    assert _t2_sanitize( "line1\nline2" )  == "line1\nline2"
    assert _t2_sanitize( "col1\tcol2" )    == "col1\tcol2"


def test_t2_sanitize_rejects_control_chars():
    """Control chars (other than \\n, \\t) raise ValueError."""
    with pytest.raises( ValueError, match="control characters" ):
        _t2_sanitize( "bad\x00null" )
    with pytest.raises( ValueError, match="control characters" ):
        _t2_sanitize( "bell\x07char" )
    with pytest.raises( ValueError, match="control characters" ):
        _t2_sanitize( "escape\x1bseq" )


# ─── PersonaInfo ────────────────────────────────────────────────────────────


def test_persona_info_happy_path():
    """name + icon stored verbatim within bounds."""
    p = PersonaInfo( name="Maria", icon="🌸" )
    assert p.name == "Maria"
    assert p.icon == "🌸"


def test_persona_info_rejects_empty_name():
    """name must be at least 1 char."""
    with pytest.raises( ValidationError ):
        PersonaInfo( name="", icon="🌸" )


def test_persona_info_rejects_oversize_name():
    """name must be ≤ 64 chars."""
    with pytest.raises( ValidationError ):
        PersonaInfo( name="a" * 65, icon="🌸" )


def test_persona_info_rejects_empty_icon():
    """icon must be at least 1 char."""
    with pytest.raises( ValidationError ):
        PersonaInfo( name="Maria", icon="" )


def test_persona_info_rejects_oversize_icon():
    """icon must be ≤ 8 chars (multi-char emoji ZWJ tolerance)."""
    with pytest.raises( ValidationError ):
        PersonaInfo( name="Maria", icon="X" * 9 )


# ─── PersonaDisambiguationRequest — validation ──────────────────────────────


@pytest.fixture
def sample_personas():
    return [
        PersonaInfo( name="Rachel",   icon="🎸" ),
        PersonaInfo( name="Tiberius", icon="🌑" ),
        PersonaInfo( name="Rio",      icon="⚡" ),
        PersonaInfo( name="Maria",    icon="🌸" ),
    ]


def test_request_happy_path( sample_personas ):
    """All fields populated; T2 escape applied to ambiguous_reference."""
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "the M session",
        context             = "user asked about scheduling",
    )
    assert req.ambiguous_reference == "the M session"
    assert req.context             == "user asked about scheduling"
    assert len( req.active_personas ) == 4


def test_request_context_defaults_to_none( sample_personas ):
    """context is optional; defaults to None."""
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "hello",
    )
    assert req.context is None


def test_request_t2_escapes_xml_chars( sample_personas ):
    """Validator escapes `<` `>` `&` in ambiguous_reference + context."""
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "the <Rachel> & friends",
        context             = "Q1 > Q2 & cond",
    )
    assert req.ambiguous_reference == "the &lt;Rachel&gt; &amp; friends"
    assert req.context             == "Q1 &gt; Q2 &amp; cond"


def test_request_t2_rejects_control_chars( sample_personas ):
    """Control chars in ambiguous_reference / context raise ValidationError."""
    with pytest.raises( ValidationError, match="control characters" ):
        PersonaDisambiguationRequest(
            active_personas     = sample_personas,
            ambiguous_reference = "bad\x00inject",
        )
    with pytest.raises( ValidationError, match="control characters" ):
        PersonaDisambiguationRequest(
            active_personas     = sample_personas,
            ambiguous_reference = "ok",
            context             = "bad\x07bell",
        )


def test_request_rejects_empty_ambiguous_reference( sample_personas ):
    """ambiguous_reference must be ≥ 1 char."""
    with pytest.raises( ValidationError ):
        PersonaDisambiguationRequest(
            active_personas     = sample_personas,
            ambiguous_reference = "",
        )


def test_request_rejects_oversize_ambiguous_reference( sample_personas ):
    """ambiguous_reference must be ≤ 256 chars."""
    with pytest.raises( ValidationError ):
        PersonaDisambiguationRequest(
            active_personas     = sample_personas,
            ambiguous_reference = "a" * 257,
        )


def test_request_rejects_oversize_context( sample_personas ):
    """context must be ≤ 2048 chars."""
    with pytest.raises( ValidationError ):
        PersonaDisambiguationRequest(
            active_personas     = sample_personas,
            ambiguous_reference = "ok",
            context             = "a" * 2049,
        )


# ─── PersonaDisambiguationRequest — to_xml ──────────────────────────────────


def test_to_xml_produces_phi4_envelope_shape( sample_personas ):
    """
    `to_xml()` produces the nested-persona shape expected by PHI-4 with
    a `<persona>` wrapper per entry inside `<active_personas>`.
    """
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "the M session",
    )
    xml = req.to_xml()
    assert "<commons_persona_disambiguation>"  in xml
    assert "</commons_persona_disambiguation>" in xml
    assert "<active_personas>"                 in xml
    assert "</active_personas>"                in xml
    # One <persona> block per entry
    assert xml.count( "<persona>" )            == 4
    assert "<name>Rachel</name>"               in xml
    assert "<icon>🎸</icon>"                    in xml
    assert "<ambiguous_reference>the M session</ambiguous_reference>" in xml


def test_to_xml_omits_context_when_none( sample_personas ):
    """When context is None, no `<context>` block is emitted."""
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "hello",
    )
    xml = req.to_xml()
    assert "<context>"  not in xml
    assert "</context>" not in xml


def test_to_xml_includes_context_when_provided( sample_personas ):
    """When context is set, the `<context>` block is emitted."""
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "hello",
        context             = "surrounding text",
    )
    xml = req.to_xml()
    assert "<context>surrounding text</context>" in xml


def test_to_xml_escaping_is_not_double_applied( sample_personas ):
    """
    ambiguous_reference is already T2-escaped on the model; `to_xml()` must
    NOT re-escape (which would produce `&amp;lt;` instead of `&lt;`).
    """
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "<Rachel>",
    )
    xml = req.to_xml()
    # T2 already produced `&lt;Rachel&gt;` — DO NOT re-escape
    assert "&lt;Rachel&gt;"      in xml
    assert "&amp;lt;Rachel&amp;" not in xml


def test_to_xml_custom_root_tag( sample_personas ):
    """root_tag override is honored."""
    req = PersonaDisambiguationRequest(
        active_personas     = sample_personas,
        ambiguous_reference = "hello",
    )
    xml = req.to_xml( root_tag="custom_envelope" )
    assert xml.startswith( "<custom_envelope>" )
    assert xml.endswith( "</custom_envelope>" )


# ─── PersonaDisambiguationResponse — direct construction ────────────────────


def test_response_happy_path():
    """matched_persona + confidence stored verbatim."""
    r = PersonaDisambiguationResponse( matched_persona="Rachel", confidence=0.87 )
    assert r.matched_persona == "Rachel"
    assert r.confidence      == 0.87


def test_response_no_match_explicit_none():
    """matched_persona defaults to None → explicit no-match."""
    r = PersonaDisambiguationResponse( confidence=0.0 )
    assert r.matched_persona is None
    assert r.confidence      == 0.0


def test_response_rejects_confidence_below_floor():
    """confidence < 0.0 raises ValidationError."""
    with pytest.raises( ValidationError ):
        PersonaDisambiguationResponse( matched_persona="Rachel", confidence=-0.01 )


def test_response_rejects_confidence_above_ceiling():
    """confidence > 1.0 raises ValidationError."""
    with pytest.raises( ValidationError ):
        PersonaDisambiguationResponse( matched_persona="Rachel", confidence=1.01 )


def test_response_rejects_oversize_matched_persona():
    """matched_persona must be ≤ 64 chars."""
    with pytest.raises( ValidationError ):
        PersonaDisambiguationResponse( matched_persona="a" * 65, confidence=0.5 )


# ─── PersonaDisambiguationResponse — empty-tag coercion ─────────────────────


def test_response_coerces_none_matched_persona():
    """`<matched_persona/>` → None (validator coerces None → None)."""
    r = PersonaDisambiguationResponse( matched_persona=None, confidence=0.0 )
    assert r.matched_persona is None


def test_response_coerces_empty_string_matched_persona():
    """`<matched_persona></matched_persona>` (empty string) → None."""
    r = PersonaDisambiguationResponse( matched_persona="", confidence=0.0 )
    assert r.matched_persona is None


def test_response_coerces_whitespace_matched_persona():
    """Whitespace-only matched_persona → None."""
    r = PersonaDisambiguationResponse( matched_persona="   ", confidence=0.0 )
    assert r.matched_persona is None


# ─── PersonaDisambiguationResponse — from_xml ───────────────────────────────


def test_response_from_xml_happy_path():
    """Standard PHI-4 response parses cleanly."""
    xml = (
        "<persona_disambiguation_response>"
        "<matched_persona>Rachel</matched_persona>"
        "<confidence>0.87</confidence>"
        "</persona_disambiguation_response>"
    )
    r = PersonaDisambiguationResponse.from_xml( xml )
    assert r.matched_persona == "Rachel"
    assert r.confidence      == 0.87


def test_response_from_xml_no_match_self_closing():
    """`<matched_persona/>` parses as None (explicit no-match)."""
    xml = (
        "<persona_disambiguation_response>"
        "<matched_persona/>"
        "<confidence>0.0</confidence>"
        "</persona_disambiguation_response>"
    )
    r = PersonaDisambiguationResponse.from_xml( xml )
    assert r.matched_persona is None
    assert r.confidence      == 0.0


def test_response_from_xml_no_match_empty_tag():
    """`<matched_persona></matched_persona>` parses as None."""
    xml = (
        "<persona_disambiguation_response>"
        "<matched_persona></matched_persona>"
        "<confidence>0.0</confidence>"
        "</persona_disambiguation_response>"
    )
    r = PersonaDisambiguationResponse.from_xml( xml )
    assert r.matched_persona is None


def test_response_from_xml_out_of_range_confidence_raises():
    """confidence > 1.0 in inbound XML raises (XMLParsingError wraps ValidationError)."""
    from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
    xml = (
        "<persona_disambiguation_response>"
        "<matched_persona>Rachel</matched_persona>"
        "<confidence>1.5</confidence>"
        "</persona_disambiguation_response>"
    )
    with pytest.raises( XMLParsingError ):
        PersonaDisambiguationResponse.from_xml( xml )


# ─── quick_smoke_test ───────────────────────────────────────────────────────


def quick_smoke_test() -> bool:
    """Stand-alone sanity check: build a request, serialize, parse a response."""
    print( "─" * 80 )
    print( "commons_xml_models quick_smoke_test" )
    print( "─" * 80 )
    try:
        personas = [
            PersonaInfo( name="Rachel", icon="🎸" ),
            PersonaInfo( name="Maria",  icon="🌸" ),
        ]
        req = PersonaDisambiguationRequest(
            active_personas     = personas,
            ambiguous_reference = "the M session",
            context             = "test",
        )
        req_xml = req.to_xml()
        assert "<persona>" in req_xml and "<ambiguous_reference>" in req_xml
        print( f"✓ Request XML built: {len( req_xml )} chars" )

        resp_xml = (
            "<persona_disambiguation_response>"
            "<matched_persona>Maria</matched_persona>"
            "<confidence>0.92</confidence>"
            "</persona_disambiguation_response>"
        )
        resp = PersonaDisambiguationResponse.from_xml( resp_xml )
        assert resp.matched_persona == "Maria" and abs( resp.confidence - 0.92 ) < 1e-9
        print( f"✓ Response parsed: persona={resp.matched_persona!r} confidence={resp.confidence}" )
        print( "✓ SMOKE PASSED" )
        return True
    except Exception as e:
        print( f"✗ SMOKE FAILED: {e!r}" )
        return False


if __name__ == "__main__":
    ok = quick_smoke_test()
    raise SystemExit( 0 if ok else 1 )
