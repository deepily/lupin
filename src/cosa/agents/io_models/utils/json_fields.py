#!/usr/bin/env python3
"""
JSON readers for the string fields of the XML models.

A model field holds what the LLM wrote. A JSON array or object arrives as text that may be blank,
malformed or the wrong kind of value. One reader serves every model that holds such a field.
"""
import json


def json_or_empty( text, kind ):
    """
    Read a JSON list or object out of a string field.

    Requires:
        - text is any value; a model field holds a string, but None and junk are expected
        - kind is list or dict

    Ensures:
        - returns the parsed value when text is JSON of that kind
        - returns an empty list or dict, as kind says, for None, a blank string, malformed JSON or JSON of another kind
        - never raises
    """
    try:
        parsed = json.loads( text )
    except ( json.JSONDecodeError, TypeError ):
        return kind()
    return parsed if isinstance( parsed, kind ) else kind()
