"""
Persona name matcher for inter-session commons broadcasts.

Matches user-input persona references against the active personas list,
case-insensitive and tolerant of punctuation/whitespace variants. When
mechanical matching fails, falls back to a stubbed local-LLM disambiguator
(Phase 1 stub returns None; Phase 3 wires the actual LLM call).

Per AC8 in src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md.
"""

import re
from typing import List, Optional


# Phase 3 wiring (Q5): set by `configure_llm_disambiguator()` from main.py lifespan.
# Defaults to None — `disambiguate_via_llm()` returns None when unset, preserving
# the Phase 1 stub contract for callers that don't wire the singleton.
_disambiguator_singleton = None


def configure_llm_disambiguator( disambiguator ) -> None:
    """
    Phase 3 setter: install the LLM disambiguator singleton.

    Requires:
        - `disambiguator` is a `CommonsLlmDisambiguator` exposing
          `.disambiguate(active_personas, ambiguous_reference, context=None)`
          OR None (clears the singleton, restoring Phase 1 stub behavior).

    Called from `main.py` lifespan during Phase 3. Tests reset between cases
    via `configure_llm_disambiguator(None)`.
    """
    global _disambiguator_singleton
    _disambiguator_singleton = disambiguator


def _normalize_for_match( s: str ) -> str:
    """
    Strip non-alphanumerics and lowercase.

    Requires:
        - s is a string (may be empty)

    Ensures:
        - Returns "" for empty input
        - Returns lowercase alphanumeric-only string
        - "Mr. Radio" / "mr radio" / "mrradio" / "MR.RADIO" all → "mrradio"
        - Unicode letters preserved via re.UNICODE
    """
    if not s: return ""
    return re.sub( r"[^\w]", "", s, flags=re.UNICODE ).lower()


def disambiguate_via_llm( input_str: str, candidate_personas: List[ str ] ) -> Optional[ str ]:
    """
    LLM-fallback hook for persona disambiguation.

    Phase 1: returns None (no LLM call).
    Phase 3: replace body with actual local-LLM call (voice-routing-classifier-style).

    Stable signature per AC8 + Q8 LLM-fallback ratification — Phase 3 upgrade
    replaces only the body, no caller refactor needed.

    Requires:
        - input_str is a non-empty string
        - candidate_personas is a non-empty list of display-name strings

    Ensures:
        - Phase 1: always returns None
        - Phase 3: returns a matched persona display name from candidate_personas, or None
    """
    # Phase 3 wiring: route through the configured LLM disambiguator when present.
    # When the singleton is None (Phase 1 default / unwired startup), preserve
    # the stub's "always None" contract for backward-compat callers.
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
    falls back to `disambiguate_via_llm` stub on miss.

    Per AC8 in 02-phase1-file-commons-design.md.

    Requires:
        - input_str is a string (may be empty — returns None)
        - candidate_personas is a list of display-name strings (may be empty — returns None)

    Ensures:
        - Returns the canonical display name from candidate_personas on mechanical match
        - Returns None when mechanical match misses AND LLM-fallback returns None
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
