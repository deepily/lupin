"""
Read the `REUSE-OUTCOME` lines of a review or plan document.

The line ties a lookup to what the diff did with it. It reads:

```text
REUSE-OUTCOME <receipt id> :: <search id> :: REUSED <symbol> | EXTENDED <symbol> | WROTE_NEW <difference> :: <plan path>#<step>
```
`REUSED` and `EXTENDED` take one symbol token and no free text after it. `WROTE_NEW` takes text with no " :: " in it.
This module reads the shape only. Whether the receipt and the search are in the call log is a later step.
Nothing here reads the log, sends anything, or runs a model.
"""
import re

TEMPLATE_RECEIPT = "<receipt id>"                                   # the receipt slot of the skill's template line
STEP_PATTERN     = r"\d+(?:\.\d+)*-[A-Za-z0-9]+|diff"                # a section, a dash, then the step id such as 12.3-D1, or diff for a task row with no plan

OUTCOME_LEAD_RE = re.compile( r"^\s*REUSE-OUTCOME\b" )
TEMPLATE_RE     = re.compile( r"^\s*REUSE-OUTCOME\s+" + re.escape( TEMPLATE_RECEIPT ) + r"(?=\s)" )
OUTCOME_RE      = re.compile(
    r"^\s*REUSE-OUTCOME\s+(?P<receipt>[0-9a-f]{16}|excluded|unindexed)\s+::\s+(?P<search>rs-[0-9a-f]{10}|unindexed)\s+::\s+"
    r"(?:(?P<kind>REUSED|EXTENDED)\s+(?P<symbol>(?!::\s)\S+)|(?P<new>WROTE_NEW)\s+(?P<difference>\S(?:(?!\s::\s).)*?))"
    r"\s+::\s+(?P<plan>[^\s#]+)#(?P<step>" + STEP_PATTERN + r")\s*$" )


def parse_outcomes( text ):
    """
    Read the outcome lines of a document.

    Requires:
        - text is a string
    Ensures:
        - returns, in document order, one { receipt, search, outcome, detail, plan, step } dict per line that matches OUTCOME_RE
        - outcome is `REUSED`, `EXTENDED` or `WROTE_NEW`; detail is the symbol token, or the difference text for `WROTE_NEW`
        - lines inside a code fence are read like any other line
        - a template line and every line that does not open with the keyword are ignored
    """
    out = []
    for line in text.splitlines():
        m = OUTCOME_RE.match( line )
        if m: out.append( { "receipt": m.group( "receipt" ), "search": m.group( "search" ), "outcome": m.group( "kind" ) or m.group( "new" ),
                            "detail": m.group( "symbol" ) or m.group( "difference" ), "plan": m.group( "plan" ), "step": m.group( "step" ) } )
    return out


def unparsed_outcome_lines( text ):
    """
    Find the lines that open as an outcome line and do not read as one.

    Requires:
        - text is a string
    Ensures:
        - returns the stripped text of every line that opens with the keyword, is not a template line, and that OUTCOME_RE does not match, in document order
        - a template line is one whose receipt slot is the template text alone; nothing else is skipped
        - a line that does not open with the keyword is never returned
    """
    return [ line.strip() for line in text.splitlines() if OUTCOME_LEAD_RE.match( line ) and not TEMPLATE_RE.match( line ) and not OUTCOME_RE.match( line ) ]
