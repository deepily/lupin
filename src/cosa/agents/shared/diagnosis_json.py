"""
Read the diagnosis JSON object out of a Lead agent's reply.

The bug fix and test fix expediters each asked the Lead for one JSON diagnosis and held a
copy of the same reader. It strips a markdown fence, finds the last balanced `{...}` with
`json_object_recovery.extract_json_object`, and parses it. Each expediter then builds its own
result type and its own fallback.
"""

import json

from cosa.agents.io_models.utils.json_object_recovery import extract_json_object


def parse_diagnosis_json( raw_response: str ) -> tuple:
    """
    Parse the diagnosis JSON object from the Lead agent's raw reply.

    Handles clean JSON, JSON in a markdown fence and JSON embedded in prose.

    Requires:
        - raw_response is a string

    Ensures:
        - returns ( data, None ) where data is the parsed object, when one was found and parsed
        - returns ( None, "no JSON object found" ) when the reply holds no balanced object
        - returns ( None, "invalid JSON: <error>" ) when the object does not parse
        - never raises
        - does not check the object's fields; the caller builds its own result type
    """
    text = raw_response.strip()

    # Strip markdown code fences if present
    if "```json" in text:
        text = text.split( "```json" )[ -1 ]
    if "```" in text:
        text = text.split( "```" )[ 0 ]

    json_str = extract_json_object( text )
    if json_str is None:
        return None, "no JSON object found"

    try:
        return json.loads( json_str ), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
