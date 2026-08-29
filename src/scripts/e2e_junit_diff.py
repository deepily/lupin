"""
Compare two pytest/Playwright junit XML runs BY TEST ID and return a gate verdict.

WHY THIS EXISTS
    Row 19a417fa carries an E2E run — ts-a5b8ad03, 2026-08-21 02:18 — that came
    back red with 18 non-passing cases and NO clean-HEAD comparison. The first
    E2E run of the brain-integration build IS that comparison, and a comparison
    read by eye across ~700 cases is a comparison nobody can check.

WHAT IT ANSWERS
    · REGRESSIONS  — passing in the baseline, non-passing now. The only bucket
                     that blocks a merge.
    · PRE-EXISTING — non-passing in BOTH runs. Not this build's doing.
    · FIXED        — non-passing in the baseline, passing now.
    · SKIPPED      — reported SEPARATELY and never folded into "passed". A test
                     that is skipped where it must run is RED, not green (the
                     two integration cases held behind step 10 are exactly this
                     shape), so a summary line reading "0 failed" over a skip is
                     the false green this tool exists to make impossible.

🔴 A COUNTING TRAP, found while building this and pinned by a test
    `e2e-junit-20260821-021831.xml` carries `<testsuite tests="697">` but holds
    only 692 `<testcase>` elements — 672 clean + 13 failure + 5 error + 2
    skipped. The gap is exactly the error count. Headline totals and per-case
    tallies therefore never reconcile, and a reader mixing the two thinks five
    cases vanished. THIS TOOL COUNTS ELEMENTS, NEVER THE ATTRIBUTE.

USAGE
    python src/scripts/e2e_junit_diff.py <baseline.xml> <new.xml>
    exit 0 — no regressions · exit 1 — regressions · exit 2 — bad invocation
"""

import sys
import xml.etree.ElementTree as ET
from typing import Dict, List

NON_PASSING = ( "failure", "error" )
OUTCOME_TAGS = ( "failure", "error", "skipped" )


def load( path: str ) -> Dict[ str, str ]:
    """
    Map every test case in a junit XML to its outcome.

    Requires:
        - path names a readable junit XML file

    Ensures:
        - returns { "<classname>::<name>" : "passed"|"failure"|"error"|"skipped" }
        - counts <testcase> ELEMENTS, never the <testsuite tests="..."> attribute

    Raises:
        - ET.ParseError if the file is not well-formed XML
    """
    outcomes = {}
    for case in ET.parse( path ).getroot().iter( "testcase" ):
        key     = f"{case.get( 'classname', '' )}::{case.get( 'name', '' )}"
        outcome = "passed"
        for child in case:
            if child.tag in OUTCOME_TAGS:
                outcome = child.tag
                break
        outcomes[ key ] = outcome
    return outcomes


def classify( baseline: Dict[ str, str ], new: Dict[ str, str ] ) -> Dict[ str, List[ str ] ]:
    """
    Split two outcome maps into the buckets a gate verdict needs.

    Requires:
        - baseline and new are outcome maps as returned by load()

    Ensures:
        - returns sorted lists under keys: regressions, pre_existing, fixed,
          skipped_now, only_in_baseline, only_in_new
        - a case absent from the baseline is treated as having PASSED there, so
          a brand-new failing test counts as a regression rather than vanishing
    """
    bad = lambda outcome: outcome in NON_PASSING
    return {
        "regressions"      : sorted( k for k in new if bad( new[ k ] ) and not bad( baseline.get( k, "passed" ) ) ),
        "pre_existing"     : sorted( k for k in new if bad( new[ k ] ) and bad( baseline.get( k, "passed" ) ) ),
        "fixed"            : sorted( k for k in new if not bad( new[ k ] ) and bad( baseline.get( k, "passed" ) ) ),
        "skipped_now"      : sorted( k for k in new if new[ k ] == "skipped" ),
        "only_in_baseline" : sorted( k for k in baseline if k not in new ),
        "only_in_new"      : sorted( k for k in new if k not in baseline ),
    }


def render( baseline_path: str, new_path: str, baseline: Dict[ str, str ],
            new: Dict[ str, str ], buckets: Dict[ str, List[ str ] ] ) -> str:
    """
    Render the verdict as a human-readable report.

    Requires:
        - buckets is the mapping returned by classify()

    Ensures:
        - returns a report naming every case in every non-empty bucket
        - states element counts, so the 697-vs-692 attribute trap cannot recur
    """
    lines = [
        f"baseline : {baseline_path}  ({len( baseline )} testcase elements)",
        f"new      : {new_path}  ({len( new )} testcase elements)",
        "",
        f"REGRESSIONS (block this merge) : {len( buckets[ 'regressions' ] )}",
    ]
    lines += [ f"   RED  {k}  [{new[ k ]}]" for k in buckets[ "regressions" ] ]
    lines += [ "", f"PRE-EXISTING (not this build)  : {len( buckets[ 'pre_existing' ] )}" ]
    lines += [ f"   ==   {k}  [{new[ k ]}]" for k in buckets[ "pre_existing" ] ]
    lines += [ "", f"FIXED by this build            : {len( buckets[ 'fixed' ] )}" ]
    lines += [ f"   GRN  {k}" for k in buckets[ "fixed" ] ]
    lines += [ "", f"SKIPPED in the new run         : {len( buckets[ 'skipped_now' ] )}"
                   "   <-- a skip where a run is REQUIRED is RED, not green" ]
    lines += [ f"   SKIP {k}" for k in buckets[ "skipped_now" ] ]
    lines += [ "",
               f"only in baseline: {len( buckets[ 'only_in_baseline' ] )}   "
               f"only in new: {len( buckets[ 'only_in_new' ] )}" ]
    lines += [ f"   GONE {k}" for k in buckets[ "only_in_baseline" ] ]
    lines += [ f"   NEW  {k}" for k in buckets[ "only_in_new" ] ]
    return "\n".join( lines )


def main( argv: List[ str ] ) -> int:
    """
    Entry point.

    Requires:
        - argv is the full argv list; argv[1:] are the two XML paths

    Ensures:
        - prints the report and returns 1 when any regression exists, else 0
        - returns 2 without reading any file when the invocation is wrong
    """
    if len( argv ) != 3:
        print( __doc__ )
        return 2
    baseline_path, new_path = argv[ 1 ], argv[ 2 ]
    baseline = load( baseline_path )
    new      = load( new_path )
    buckets  = classify( baseline, new )
    print( render( baseline_path, new_path, baseline, new, buckets ) )
    return 1 if buckets[ "regressions" ] else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry, exercised via main() in tests
    sys.exit( main( sys.argv ) )
