"""
Persona name matcher for inter-session commons broadcasts.

Matches user-input persona references against the active personas list,
case-insensitive and tolerant of punctuation/whitespace variants. When
mechanical matching fails, falls back to an LLM disambiguator. The server
lifespan installs a CommonsLlmDisambiguator when commons is enabled; until one is
installed the fallback returns None.

Per AC8 in src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md.
"""

from typing import List, Optional


# Phase 3 wiring (Q5): set by `configure_llm_disambiguator()` from main.py lifespan.
# Defaults to None — `disambiguate_via_llm()` returns None when unset, preserving
# the Phase 1 stub contract for callers that don't wire the singleton.
_disambiguator_singleton = None


def configure_llm_disambiguator( disambiguator ) -> None:
    """
    Install the LLM disambiguator singleton.

    Requires:
        - `disambiguator` is a `CommonsLlmDisambiguator` exposing
          `.disambiguate(active_personas, ambiguous_reference, context=None)`
          OR None (clears the singleton, so the fallback returns None again).

    Called from the `main.py` lifespan when commons is enabled. Tests reset between cases
    via `configure_llm_disambiguator(None)`.
    """
    global _disambiguator_singleton
    _disambiguator_singleton = disambiguator


# Persona match-normalization moved to the centralized home lupin_mcp.persona_normalization
# (2026-06-19). `_normalize_for_match` is kept as a back-compat alias for the many call
# sites that import it; it now shares the ONE canonical root and gains accent-stripping,
# FIXING the prior "María" -> "maría" divergence from the store key (the old re.UNICODE
# form kept accents, so an accented reference never matched the store's "maria").
from lupin_mcp.persona_normalization import normalize_for_match as _normalize_for_match


def disambiguate_via_llm( input_str: str, candidate_personas: List[ str ] ) -> Optional[ str ]:
    """
    LLM-fallback hook for persona disambiguation.

    Delegates to the installed CommonsLlmDisambiguator (see
    `configure_llm_disambiguator`). With none installed it makes no LLM call and
    returns None, which is the default for any caller that never wires one.

    Stable signature per AC8 + Q8 LLM-fallback ratification.

    Requires:
        - input_str is a non-empty string
        - candidate_personas is a non-empty list of display-name strings

    Ensures:
        - Returns None when no disambiguator is installed or candidate_personas is empty
        - Otherwise returns the disambiguator's pick, a persona display name from
          candidate_personas, or None
    """
    # Route through the configured LLM disambiguator when present. When the singleton
    # is None (unwired startup), return None for backward-compat callers.
    if _disambiguator_singleton is None or not candidate_personas:
        return None
    # Convert display-name list to PersonaInfo with placeholder icon.
    # Broadcast-handler call sites don't have icons at the matcher boundary;
    # the disambiguator's whitelist only checks `.name`, so the placeholder
    # icon ("💬") is dispatched but never compared.
    from lupin_mcp.commons_xml_models import PersonaInfo
    personas = [ PersonaInfo( name=name, icon="💬" ) for name in candidate_personas ]
    return _disambiguator_singleton.disambiguate( personas, input_str )


def match_persona( input_str: str, candidate_personas: List[ str ] ) -> Optional[ str ]:
    """
    Match a user-input persona reference to a canonical persona from candidate_personas.

    Case-insensitive, punctuation/space-tolerant mechanical matching first;
    falls back to `disambiguate_via_llm` on miss.

    Per AC8 in 02-phase1-file-commons-design.md.

    Requires:
        - input_str is a string (may be empty — returns None)
        - candidate_personas is a list of display-name strings (may be empty — returns None)

    Ensures:
        - Returns the canonical display name from candidate_personas on mechanical match
        - Returns None when mechanical match misses AND the LLM fallback returns None
          (including when no disambiguator is installed)
        - "Mr. Radio" / "mr radio" / "mrradio" / "MR.RADIO" all match candidate "Mr. Radio"
        - Empty input or empty candidate list → returns None
    """
    if not input_str or not candidate_personas:
        return None

    normalized_input = _normalize_for_match( input_str )
    if not normalized_input:
        return None  # Input was all-punctuation (e.g., "..." or "   ")

    for candidate in candidate_personas:
        if _normalize_for_match( candidate ) == normalized_input:
            return candidate

    return disambiguate_via_llm( input_str, candidate_personas )
