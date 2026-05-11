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
    return None  # Phase 3 wires actual LLM call here


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
