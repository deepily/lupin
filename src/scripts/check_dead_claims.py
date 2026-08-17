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
import re
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
    "config change, not a code change"  : "the factory has no google-genai entry (added 3405f0b2, removed 1b6c0b1f)",
    "config only"                       : "the factory has no google-genai entry (added 3405f0b2, removed 1b6c0b1f)",
    "three INI lines"                   : "the factory has no google-genai entry (added 3405f0b2, removed 1b6c0b1f)",
    "smoke the API-key surface first"   : "there is no API-key surface to smoke",
    "Developer-API mode first"          : "there is no API-key surface to smoke",
    "GOOGLE_CLOUD_PROJECT"              : "assertable override; read LUPIN_GCP_PROJECT_ID instead",
    "no ADC"                            : "ADC were on disk all along; a live Vertex call answered OK",
    "cannot authenticate to Vertex"     : "it authenticated; smoked 2026-08-16",
    "us-central1"                       : "404s for this model — use location=global",
    # Finding 7: table families the checker did not enforce, added with the TABLE's exact
    # wording (row 6/7/11 canonical strings) so the human table and the checker agree.
    "the model id is Rick's half"       : "given: gemini-3.1-flash-lite (Rick, 2026-08-16)",
    "smoke the Developer API first"     : "there is no API-key surface to smoke",
    "which project is open/unconfirmed" : "Rick confirmed LUPIN_GCP_PROJECT_ID",
    "read the corpus"                   : "the live log grows ~5 rows/min and unpairs the arms; snapshot it (§1.2)",
}

WINDOW = 2   # lines either side to search for a marker — these documents are hard-wrapped

# The first backticked `phrase` OR the first "phrase" in a table cell — the canonical
# grep string a dead-claims table row declares. Backtick and double-quote only; a row
# lists several strings for one family and we pin the FIRST, not every substring, so an
# ordinary reword of the row's prose does not trip the sync guard (Rachel's ruling).
_QUOTED = re.compile( r"`([^`]+)`|\"([^\"]+)\"" )


def _first_quoted( text ):
    """
    Requires:
        - text is a single table cell's raw text
    Ensures:
        - returns the inner text of the FIRST backticked or double-quoted token, or
          None when the cell carries neither (a header/separator cell)
    """
    match = _QUOTED.search( text )
    if match is None:
        return None
    return match.group( 1 ) if match.group( 1 ) is not None else match.group( 2 )


def extract_table_claims( text, table_after="DEAD CLAIMS" ):
    """
    Extract the canonical phrase from each row of a document's dead-claims table.

    Requires:
        - text is the document's full text
        - table_after is a substring identifying the heading line the table follows
    Ensures:
        - returns the canonical phrases (first quoted token in column one) of the
          first contiguous markdown table after that heading, in table order
        - returns [] when the heading is absent
        - header and separator rows carry no quoted token in column one, so they
          contribute nothing
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate( lines ):
        if table_after in line:
            start = i
            break
    if start is None:
        return []

    claims   = []
    in_table = False
    for line in lines[ start + 1 : ]:
        stripped = line.strip()
        if stripped.startswith( "|" ):
            in_table = True
            phrase   = _first_quoted( stripped.split( "|" )[ 1 ] )
            if phrase is not None:
                claims.append( phrase )
        elif in_table:
            break   # first non-table line after the table started ends it
    return claims


def unenforced_table_claims( text, claims, table_after="DEAD CLAIMS" ):
    """
    The canonical table phrases the checker does NOT enforce — the drift between the
    human dead-claims table and the claims the checker actually greps for.

    Requires:
        - text is the document's full text
        - claims maps a phrase to the reason it is dead (the enforced set)
    Ensures:
        - returns the table's canonical phrases absent from `claims` as an exact key,
          in table order — a new table row with no matching claim is reported here
    """
    enforced = set( claims )
    return [ phrase for phrase in extract_table_claims( text, table_after=table_after )
             if phrase not in enforced ]


# A per-line, REASONED exemption: this exact line legitimately carries a dead phrase
# live, and the reason is stated inline so the exemption can be audited and refuted.
# The reason is REQUIRED — `<!-- claim-exempt: -->` with no reason does not match, so a
# blank suppress cannot slip through. The keyword is deliberately free of every MARKERS
# token, so an exemption is the explicit mechanism, never the fuzzy window heuristic.
_EXEMPTION = re.compile( r"<!--\s*claim-exempt:\s*(.+?)\s*-->" )


def _exemption_reason( line ):
    """
    Requires:
        - line is a single line of the document
    Ensures:
        - returns the stated reason (trimmed) of a reasoned `claim-exempt` marker on
          this line, or None when the line carries no such marker OR its reason is
          blank/whitespace-only — a reason is REQUIRED, a blank suppress cannot slip in
    """
    match = _EXEMPTION.search( line )
    if match is None:
        return None
    reason = match.group( 1 ).strip()
    return reason if reason else None


def find_exemptions( text, claims ):
    """
    List every per-line dead-claim exemption in the document, so they can be audited
    and never accumulate unnoticed.

    Requires:
        - text is the document's full text
        - claims maps a phrase to the reason it is dead
    Ensures:
        - returns ( lineno, reason, stale, line ) for each line carrying a reasoned
          `claim-exempt` marker, in document order
        - stale is True when NO dead phrase appears on that line — the exemption now
          guards nothing and should be removed
    """
    out = []
    for i, line in enumerate( text.splitlines() ):
        reason = _exemption_reason( line )
        if reason is None:
            continue
        stale = not any( phrase in line for phrase in claims )
        out.append( ( i + 1, reason, stale, line.strip()[ :100 ] ) )
    return out


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
        - a line carrying a reasoned `claim-exempt` marker is not reported — an explicit,
          per-line, auditable exemption distinct from the fuzzy +/- WINDOW marker heuristic
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
        exempt = _exemption_reason( lines[ i ] ) is not None
        window = "\n".join( lines[ max( 0, i - WINDOW ) : i + WINDOW + 1 ] )
        for phrase, reason in claims.items():
            if phrase in lines[ i ] and not any( m in window for m in MARKERS ):
                if exempt:
                    continue   # explicit per-line reasoned exemption suppresses this hit
                found.append( ( i + 1, phrase, reason, lines[ i ].strip()[ :100 ] ) )
    return found


def main( argv=None ):
    """
    Requires:
        - argv is a list of arguments or None

    Ensures:
        - prints one line per live dead claim, and a clean/failed summary
        - exit 1 when anything is live, so this can gate a publish step
        - with --check-table-sync, also reports table claims the checker does not
          enforce, exit 3 when the table and the checker have drifted
    """
    parser = argparse.ArgumentParser( description="Find dead claims still asserted in a design doc." )
    parser.add_argument( "doc" )
    parser.add_argument( "--claims", default=None, help="JSON file mapping phrase -> reason" )
    parser.add_argument( "--skip-until", default="## 0. ",
                         help="ignore everything before this line prefix (the doc's own dead-claims table)" )
    parser.add_argument( "--check-table-sync", action="store_true",
                         help="also fail when the doc's dead-claims TABLE lists a claim the checker does not enforce" )
    parser.add_argument( "--list-exemptions", action="store_true",
                         help="list every per-line claim-exempt marker with its reason (audit), then exit" )
    args = parser.parse_args( argv )

    doc = Path( args.doc )
    if not doc.exists():
        print( f"ERROR: no such document: {doc}", file=sys.stderr )
        return 2

    claims = DEFAULT_CLAIMS
    if args.claims:
        claims = json.loads( Path( args.claims ).read_text( encoding="utf-8" ) )

    content = doc.read_text( encoding="utf-8" )

    if args.list_exemptions:
        exemptions = find_exemptions( content, claims )
        for lineno, reason, stale, line in exemptions:
            tag = " STALE" if stale else ""
            print( f"EXEMPT{tag}  {doc}:{lineno}  \"{reason}\"\n        {line}" )
        note = " Some guard nothing (STALE) — remove them." if any( e[ 2 ] for e in exemptions ) else ""
        print( f"\n{len( exemptions )} active exemption(s).{note}" )
        return 0

    live = find_live_claims( content, claims, skip_until=args.skip_until )

    for lineno, phrase, reason, line in live:
        print( f"LIVE  {doc}:{lineno}  \"{phrase}\"  — {reason}\n        {line}" )

    unenforced = []
    if args.check_table_sync:
        unenforced = unenforced_table_claims( content, claims )
        for phrase in unenforced:
            print( f"UNENFORCED  \"{phrase}\"  — in the dead-claims table but not in the checker's claim set" )

    if live:
        print( f"\n{len( live )} dead claim(s) read as LIVE. A revision is not done until this is clean." )
        return 1

    if unenforced:
        print( f"\n{len( unenforced )} table claim(s) the checker does not enforce. The table and the checker have drifted." )
        return 3

    summary = f"clean — {len( claims )} dead claim(s) checked, none reads as live"
    if args.check_table_sync:
        summary += "; table and checker in sync"
    print( summary )
    return 0


if __name__ == "__main__":   # pragma: no cover - CLI entry, exercised via main( argv )
    sys.exit( main() )
