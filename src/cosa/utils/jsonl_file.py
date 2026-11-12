"""
Read a JSON Lines file whole, one record per non-blank line.

The doc-lint tools, the reuse need-set and the duplicate-check filer each read a spool or
ledger file this way. The reader lives here once, so they agree on blank lines, on a missing
file and on a line that is not JSON.
"""

import json


def read_jsonl( path, missing_ok=False ):
    """
    Return the records of a JSON Lines file, skipping blank lines.

    Requires:
        - path is a str or path-like naming the file
        - missing_ok is a bool

    Ensures:
        - returns the parsed value of every non-blank line, in file order
        - returns [] for a missing file when missing_ok is True
        - splits lines on the newline character only, so a raw U+2028 inside a string stays in its record

    Raises:
        - FileNotFoundError for a missing file when missing_ok is False
        - json.JSONDecodeError for a non-blank line that is not JSON
    """
    try:
        with open( path, encoding="utf-8" ) as f:
            return [ json.loads( line ) for line in f if line.strip() ]
    except FileNotFoundError:
        if missing_ok: return []
        raise
