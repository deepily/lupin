"""
Read the `REUSE-OUTCOME` lines of a review or plan document.

The line ties a lookup to what the diff did with it. It reads:

```text
REUSE-OUTCOME <receipt id> :: <search id> :: REUSED <symbol> | EXTENDED <symbol> | WROTE_NEW <difference> :: <plan path>#<step>
```
`REUSED` and `EXTENDED` take one symbol token and no free text after it. `WROTE_NEW` takes text with no " :: " in it.
This module reads the shape, and gives the two tokens `excluded` and `unindexed` their meaning.
Whether a real receipt and search are in the call log is a later step.
Nothing here reads the log, sends anything, or runs a model.
"""
import pathlib
import re

from cosa.repo.symindex.spec import SCRIPT_SUFFIXES, skipped, spec_for
from lupin_mcp.reuse_exit_gate import EXCLUDED_PREFIX, EXCLUDED_TOKEN

UNINDEXED_TOKEN  = "unindexed"                                      # the receipt and search token for a file outside the index

TEMPLATE_RECEIPT = "<receipt id>"                                   # the receipt slot of the skill's template line
TEMPLATE_SEARCH  = "<search id>"                                    # the search slot of the same line
STEP_PATTERN     = r"\d+(?:\.\d+)*-[A-Za-z0-9]+|diff"                # a section, a dash, then the step id such as 12.3-D1, or diff for a task row with no plan

OUTCOME_LEAD_RE = re.compile( r"^\s*REUSE-OUTCOME\b" )
TEMPLATE_RE     = re.compile( r"^\s*REUSE-OUTCOME\s+" + re.escape( TEMPLATE_RECEIPT ) + r"\s+::\s+" + re.escape( TEMPLATE_SEARCH ) + r"(?=\s)" )
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
        - returns, in document order, one { receipt, search, outcome, detail, plan, step, line } dict per line that matches OUTCOME_RE
        - outcome is `REUSED`, `EXTENDED` or `WROTE_NEW`; detail is the symbol token, or the difference text for `WROTE_NEW`
        - line is the stripped text, so a later check can name it
        - lines inside a code fence are read like any other line
        - a template line and every line that does not open with the keyword are ignored
    """
    out = []
    for line in text.splitlines():
        m = OUTCOME_RE.match( line )
        if m: out.append( { "receipt": m.group( "receipt" ), "search": m.group( "search" ), "outcome": m.group( "kind" ) or m.group( "new" ),
                            "detail": m.group( "symbol" ) or m.group( "difference" ), "plan": m.group( "plan" ), "step": m.group( "step" ), "line": line.strip() } )
    return out


def unparsed_outcome_lines( text ):
    """
    Find the lines that open as an outcome line and do not read as one.

    Requires:
        - text is a string
    Ensures:
        - returns the stripped text of every line that opens with the keyword, is not a template line, and that OUTCOME_RE does not match, in document order
        - a template line is one whose receipt slot and search slot are both the template text; a line with only one placeholder is refused and listed
        - a line that does not open with the keyword is never returned
    """
    return [ line.strip() for line in text.splitlines() if OUTCOME_LEAD_RE.match( line ) and not TEMPLATE_RE.match( line ) and not OUTCOME_RE.match( line ) ]


def is_indexed( path, root ):
    """
    Say whether the symbol index holds a file, by the indexer's own rule.

    Requires:
        - root is a repository root; path is a file path, relative to root or absolute
    Ensures:
        - returns True when the path lies under a Python root with a .py suffix, a script root with a script suffix, or a Dart root with a .dart suffix
        - and the indexer's skip rule (a skipped directory name or a skipped suffix) does not drop it
        - the roots, suffixes and skip rule are spec_for's and iter_files's own, so a file in a root that the index drops is not indexed
        - a path outside the tree is not indexed; the path need not exist
        - reads only the paths, not the tests scope, which the index builds separately
    """
    spec  = spec_for( root )
    where = ( spec.root / path ).resolve()
    if not where.is_relative_to( spec.root.resolve() ): return False
    if skipped( where.relative_to( spec.root.resolve() ).as_posix(), spec.skip_parts ): return False
    kinds = ( ( spec.py_roots, ( ".py", ) ), ( spec.js_roots, SCRIPT_SUFFIXES ), ( spec.dart_roots, ( ".dart", ) ) )
    return any( where.suffix in suffixes and where.is_relative_to( base.resolve() ) for bases, suffixes in kinds for base in bases )


def token_refusals( outcomes, exclusions, root ):
    """
    Refuse the `excluded` and `unindexed` lines that have no backing.

    Requires:
        - outcomes comes from parse_outcomes
        - exclusions is what reuse_exit_gate.exclusions_by_symbol returns for the call log
        - root is a repository root
    Ensures:
        - the key of a line is the first word of its detail text
        - an `excluded` receipt passes only when the log holds an `EXCLUDED_` refusal for exactly that key
        - an `unindexed` receipt passes only with `unindexed` in the search slot and a key the symbol index does not hold
        - an `unindexed` search beside any other receipt is refused
        - returns [ { line, reason } ] in document order; every other line is left alone
        - the reason for a missing refusal says to re-run the lookup and check the log folder, because a swallowed log write looks the same
    """
    out = []
    for o in outcomes:
        key = o[ "detail" ].split()[ 0 ]
        if o[ "receipt" ] == EXCLUDED_TOKEN:
            if key not in exclusions: out.append( { "line": o[ "line" ], "reason": f"{key} has no {EXCLUDED_PREFIX} refusal in the log; re-run the lookup and check the log folder, since a failed log write looks the same" } )
        elif o[ "receipt" ] == UNINDEXED_TOKEN:
            if o[ "search" ] != UNINDEXED_TOKEN: out.append( { "line": o[ "line" ], "reason": f"{UNINDEXED_TOKEN} goes in both id slots" } )
            elif is_indexed( key, root ): out.append( { "line": o[ "line" ], "reason": f"{key} is a file the symbol index holds, so look it up instead" } )
        elif o[ "search" ] == UNINDEXED_TOKEN: out.append( { "line": o[ "line" ], "reason": f"{UNINDEXED_TOKEN} in the search slot needs {UNINDEXED_TOKEN} in the receipt slot" } )
    return out
