"""
The same-line waiver marker of the documentation standard.

A finding is waived by ending its own source line with "doc-lint: waive <rule> -- <reason>".
The commit gate and the finding counter both read it here, so the two cannot disagree on
what a waiver is.
"""

import re

REASON_WORD  = re.compile( r"[A-Za-z]{3,}" )
WAIVER_REGEX = re.compile( r"doc-lint: waive (\S+)(?: -- (.*))?" )


def waiver_state( finding, source_line ):
    """
    Read the waiver marker on the finding's own source line.

    Requires:
        - finding is a Finding
        - source_line is the text of the file line the finding sits on

    Ensures:
        - returns "honoured" when a marker names finding.rule and its reason holds a word of three letters or more
        - returns "no-reason" when a marker names the rule and its reason holds no such word
        - returns "none" otherwise, including a marker that names a different rule

    Raises:
        - nothing
    """
    state = "none"
    for m in WAIVER_REGEX.finditer( source_line ):
        if m.group( 1 ).strip( "\"'" ) != finding.rule: continue
        if REASON_WORD.search( m.group( 2 ) or "" ): return "honoured"
        state = "no-reason"
    return state
