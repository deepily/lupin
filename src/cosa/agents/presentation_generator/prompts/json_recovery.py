#!/usr/bin/env python3
"""
JSON recovery for the Presentation Generator (bounded-CC D6-STRICT).

The content phase was migrated to in-process Claude Agent SDK (`sdk_query`),
whose completions can be chattier than the old `messages.create` path (leading
prose, trailing remarks, stray fences). `recover_json_object` recovers the JSON
object best-effort; the CALL SITES enforce the D6-STRICT policy (fail-loud on
unrecoverable / missing / empty content — Presentation's structured output is
consumed downstream by pptx rendering, so an empty deck is a real defect).

Single source of truth for the agent (one-name rule): imported by api_client.py
and the prompts/{narrative,outline,elaboration}.py parsers.
"""

import json
from typing import Optional, Any


def extract_json_object( text: str ) -> Optional[ str ]:
    """
    Extract the last balanced JSON object from text by matching braces.

    Recovers a JSON object embedded in surrounding prose (e.g. "Here's the
    outline: { ... }"). Ports the BFE/TFE/Podcast forensic-parser approach.

    Requires:
        - text is a string

    Ensures:
        - returns the substring of the last balanced {...} object, or None
    """
    close_idx = text.rfind( "}" )
    if close_idx == -1:
        return None

    depth = 0
    for i in range( close_idx, -1, -1 ):
        if text[ i ] == "}":
            depth += 1
        elif text[ i ] == "{":
            depth -= 1
            if depth == 0:
                return text[ i : close_idx + 1 ]

    return None


def recover_json_object( response_content: str ) -> Optional[ Any ]:
    """
    Best-effort recovery of a JSON value from a (possibly chatty) completion.

    Strategy:
        1. Strip leading/trailing markdown code fences.
        2. Try a direct `json.loads`.
        3. On failure, extract the last balanced {...} object from the prose
           and retry.

    The STRICT failure posture (raise on None) is the CALLER's responsibility —
    this helper only recovers; it never raises and never substitutes a default.

    Requires:
        - response_content is a string

    Ensures:
        - returns the parsed JSON value, or None if nothing can be recovered
    """
    content = response_content.strip()

    # Strip markdown code fences
    if content.startswith( "```json" ):
        content = content[ 7: ]
    elif content.startswith( "```" ):
        content = content[ 3: ]
    if content.endswith( "```" ):
        content = content[ :-3 ]
    content = content.strip()

    try:
        return json.loads( content )
    except json.JSONDecodeError:
        pass

    extracted = extract_json_object( content )
    if extracted is None:
        return None

    try:
        return json.loads( extracted )
    except json.JSONDecodeError:
        return None
