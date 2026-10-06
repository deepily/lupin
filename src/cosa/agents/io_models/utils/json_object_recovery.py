#!/usr/bin/env python3
"""
Shared JSON-object recovery for bounded-CC / SDK completions.

One implementation, imported by both the Podcast generator and the Presentation generator.
The Podcast generator (`prompts/script_generation.py`) is lenient: its parser raises on unrecoverable.
The Presentation generator (`prompts/json_recovery.py`) is strict: the caller owns the raise.

Notes:
    - The two generators' bodies were byte-identical, so merging them changes no behavior.
      This follows the shared-helper precedent of fuzzy_file_prefilter.
    - Deep Research keeps its own copy for now. It already raises instead of
      returning None, and folding it in would change a third component's contract.
    - Fence preference: recovery drops everything at or after the closing code fence.
      Explanatory prose appended after a ```json block (for example
      "### Explanation: each segment is a {speaker, role, text} object")
      therefore cannot defeat last-brace extraction.
    - Without that cut, the trailing brace became the "last balanced object",
      `json.loads` failed on the fragment, and recovery returned None.
      That silently produced an empty (0-segment) podcast.
"""

import json
import logging
from typing import Optional, Any

logger = logging.getLogger( __name__ )

# Cap for the loud raw-body log on an unrecoverable response: keep head+tail so a
# multi-thousand-token completion cannot flood the log, while still capturing the
# trailing prose that usually defeats recovery (P0 4317efd1).
_RAW_BODY_LOG_CAP = 4000

# Control chars that strict json.loads rejects inside string values but which are
# benign whitespace. The recovery gate below relaxes ONLY these — never structure,
# never any other control char — so a completion that is well-formed apart from an
# unescaped newline in a string is recovered, while genuinely-corrupt output still
# fails loudly (bug e0bb5a94 defect A: the script model emitted a literal newline
# inside a "text" dialogue value, and the whole script read as unrecoverable).
_BENIGN_WHITESPACE_CTRLS = frozenset( "\n\r\t" )


def _loads_whitespace_tolerant( text: str ) -> Any:
    """
    json.loads(text) with a narrow recovery gate.

    Strict parsing first. If it fails only because of unescaped benign whitespace
    control chars (\\n \\r \\t) inside string values, retry with strict=False.

    Requires:
        - text is a string

    Ensures:
        - returns the parsed JSON value on success
        - raises json.JSONDecodeError if strict fails for any reason other than
          benign-whitespace control chars, or if strict=False still fails

    Notes:
        - The retry logs at warning level which chars were repaired, so a path carrying
          real volume is countable, not a whisper.
        - Any other control char, or any structural error, still raises.
        - Widening what a check accepts would trade a loud failure for a silent wrong answer.
    """
    try:
        return json.loads( text )
    except json.JSONDecodeError:
        offending = { c for c in text if ord( c ) < 0x20 and c not in _BENIGN_WHITESPACE_CTRLS }
        if offending:
            raise                                     # a non-whitespace control char → stay loud
        value    = json.loads( text, strict=False )   # may still raise on a structural error
        repaired = sorted( c for c in set( text ) if c in _BENIGN_WHITESPACE_CTRLS )
        logger.warning(
            "[json-recovery] recovered a completion whose ONLY control-char defect was "
            "unescaped whitespace %s inside string values (strict=False gate, bug "
            "e0bb5a94 defect A); a path carrying real volume here is now countable.",
            [ repr( c ) for c in repaired ],
        )
        return value


def extract_json_object( text: str ) -> Optional[ str ]:
    """
    Extract the last balanced JSON object from text by matching braces.

    Recovers a JSON object embedded in surrounding prose (e.g. "Here's the
    outline: { ... }"). Ports the BFE/TFE forensic-parser approach.

    Requires:
        - text is a string

    Ensures:
        - returns the substring of the last balanced {...} object, or None

    Notes:
        - Last-brace selection is intentional: the strict Presentation callers depend on it.
        - Trailing prose is cut by the fence handling in `recover_json_object`,
          before this function is reached.
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

    Requires:
        - response_content is a string

    Ensures:
        - returns the parsed JSON value, or None if nothing can be recovered
        - never raises and never substitutes a default

    Notes:
        - Strategy: (1) strip a leading markdown code fence (``` or ```json) and drop
          everything at or after the matching closing fence; (2) try a direct `json.loads`;
          (3) on failure, extract the last balanced {...} object from the prose and retry.
        - Trailing prose after the code block would otherwise defeat last-brace recovery.
        - The failure posture belongs to the caller: Podcast's `parse_script_response`
          raises on None, and so do Presentation's four call sites.
        - On an unrecoverable response this logs the full raw body at error level.
        - That log changes no return value, so the malformed completion is captured
          permanently without a staged harness.
    """
    content = response_content.strip()

    # Strip a leading code fence and drop trailing prose after the closing fence.
    if content.startswith( "```" ):
        newline = content.find( "\n" )
        content = content[ newline + 1 : ] if newline != -1 else content[ 3: ]
        closing = content.rfind( "```" )
        if closing != -1:
            content = content[ :closing ]
    content = content.strip()

    try:
        return _loads_whitespace_tolerant( content )
    except json.JSONDecodeError:
        pass

    extracted = extract_json_object( content )
    if extracted is not None:
        try:
            return _loads_whitespace_tolerant( extracted )
        except json.JSONDecodeError:
            pass

    # Unrecoverable: log the raw body LOUDLY so it is captured permanently. Bound
    # it head+tail (the trailing prose after a code fence is the usual culprit, so
    # the TAIL must survive) to keep a multi-thousand-token completion from
    # flooding the log on every failure.
    body = response_content
    cap  = _RAW_BODY_LOG_CAP
    if len( body ) > cap:
        half = cap // 2
        body = (
            f"{body[ :half ]}\n...[{len( response_content ) - cap} chars omitted]...\n{body[ -half: ]}"
        )
    logger.error(
        "[json-recovery] unrecoverable JSON from model response (%d chars); bounded raw body follows:\n%s",
        len( response_content ), body,
    )
    return None
