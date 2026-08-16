#!/usr/bin/env python3
"""
Grep a design document for claims that have been killed but may still be asserted somewhere in it.

WHY THIS EXISTS. The Phi-4 vs Flash-Lite comparison design had SIX stale claims found by reviewers,
one at a time, over an afternoon. Every one was the same failure: a section was revised and a
neighbour kept asserting what it replaced. Fixing them individually did not work — it cost six
rounds of reviewer time — because the rule "when a claim dies, grep the document" is a thing a
person has to remember, and the author kept not remembering it inside the very fix for it.

WHAT COUNTS AS MARKED. A dead phrase is fine when it appears inside a strike-through, a withdrawal,
or a banner naming it dead — that is a document correctly recording its own history. It is a defect
only when it reads as a live instruction. Because these documents are hard-wrapped, the marker often
lands on a NEIGHBOURING line, so the check reads a small window around each hit rather than the one
line it matched. A checker that flags every historical mention trains its reader to ignore it, which
is the same false-positive failure the fleet already watches for on the arbiter.

Usage:
    python3 src/scripts/check_dead_claims.py <doc.md> [--claims <claims.json>]

Exit codes:
    0  no live dead-claim found
    1  at least one dead claim reads as live
    2  the document or claims file could not be read
"""

import argparse
import json
import sys
from pathlib import Path

# Markers that mean "this mention is recording history, not instructing the reader".
#
# The first version of this list was too narrow and flagged NINE historical mentions — banners
# explaining why a claim died, and the post-mortem section describing how it was caught. That is
# the false-positive failure this file's own docstring warns about, shipped inside the fix for it.
# The vocabulary below is what those banners actually use, harvested from the document rather than
# guessed: past tense, review rows, and the words a correction is written with.
MARKERS = (
    # explicit revision banners
    "~~", "WITHDRAWN", "RULED OUT", "SUPERSEDED", "RETIRED", "CORRECTED", "REWRITTEN", "REPLACED",
    "DEAD", "dead", "DO NOT", "do not", "must not", "is not to be used", "no longer", "not inert",
    # the language of a post-mortem: something happened TO this claim
    "killed", "broke", "was wrong", "was stale", "stale", "False", "false", "retracted",
    "The claim was", "Correction", "correction", "found that", "proved", "superseded",
    # a review row id next to a phrase means the phrase is being discussed, not asserted
    "7f361ccf", "3405f0b2", "63339562", "e515a5c5", "row `",
    # the reconciling table names the wrong variable in order to warn about it
    "instead", "rather than", "CODE, not", "grep for", "never set", "never `",
)

# The default list is the one the comparison design accumulated. A caller can supply its own.
DEFAULT_CLAIMS = {
    "google-gla"                        : "dead vendor — two env-var names, the INI one loses (7f361ccf)",
    "GOOGLE_API_KEY"                    : "the dead vendor's variable (7f361ccf)",
    "get_api_key"                       : "Rick ruled the API key out entirely, 2026-08-16",
    "keys/gemini"                       : "Rick ruled the API key out entirely, 2026-08-16",
    "config change, not a code change"  : "the factory has no google-genai entry (3405f0b2)",
    "config only"                       : "the factory has no google-genai entry (3405f0b2)",
    "three INI lines"                   : "the factory has no google-genai entry (3405f0b2)",
    "smoke the API-key surface first"   : "there is no API-key surface to smoke",
    "Developer-API mode first"          : "there is no API-key surface to smoke",
    "GOOGLE_CLOUD_PROJECT"              : "assertable override; read LUPIN_GCP_PROJECT_ID instead",
}

WINDOW = 2   # lines either side to search for a marker — these documents are hard-wrapped


def find_live_claims( text, claims, skip_until=None ):
    """
    Find dead claims that read as live.

    Requires:
        - text is the document's full text
        - claims maps a phrase to the reason it is dead
        - skip_until is a line prefix that ends the checker's own exempt region, or None

    Ensures:
        - returns a list of ( lineno, phrase, reason, line ) for UNMARKED occurrences only
        - a phrase inside or adjacent to a marker is not reported — the window is +/- WINDOW lines,
          because a hard-wrapped banner puts its marker on a neighbouring line
        - everything before skip_until is ignored, so a document's own dead-claims TABLE does not
          report itself
    """
    lines = text.splitlines()
    start = 0

    if skip_until is not None:
        for i, line in enumerate( lines ):
            if line.startswith( skip_until ):
                start = i
                break

    found = []
    for i in range( start, len( lines ) ):
        window = "\n".join( lines[ max( 0, i - WINDOW ) : i + WINDOW + 1 ] )
        for phrase, reason in claims.items():
            if phrase in lines[ i ] and not any( m in window for m in MARKERS ):
                found.append( ( i + 1, phrase, reason, lines[ i ].strip()[ :100 ] ) )
    return found


def main( argv=None ):
    """
    Requires:
        - argv is a list of arguments or None

    Ensures:
        - prints one line per live dead claim, and a clean/failed summary
        - exit 1 when anything is live, so this can gate a publish step
    """
    parser = argparse.ArgumentParser( description="Find dead claims still asserted in a design doc." )
    parser.add_argument( "doc" )
    parser.add_argument( "--claims", default=None, help="JSON file mapping phrase -> reason" )
    parser.add_argument( "--skip-until", default="## 0. ",
                         help="ignore everything before this line prefix (the doc's own dead-claims table)" )
    args = parser.parse_args( argv )

    doc = Path( args.doc )
    if not doc.exists():
        print( f"ERROR: no such document: {doc}", file=sys.stderr )
        return 2

    claims = DEFAULT_CLAIMS
    if args.claims:
        claims = json.loads( Path( args.claims ).read_text( encoding="utf-8" ) )

    live = find_live_claims( doc.read_text( encoding="utf-8" ), claims, skip_until=args.skip_until )

    for lineno, phrase, reason, line in live:
        print( f"LIVE  {doc}:{lineno}  \"{phrase}\"  — {reason}\n        {line}" )

    if live:
        print( f"\n{len( live )} dead claim(s) read as LIVE. A revision is not done until this is clean." )
        return 1

    print( f"clean — {len( claims )} dead claim(s) checked, none reads as live" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
