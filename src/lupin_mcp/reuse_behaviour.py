"""
Count lookups, outcome lines by kind and refusals by reason.

The counts come from two files: the call log (what lookups were made) and refusals.jsonl (what each outcome line was and why it was refused).
The tables are drawn by report_rollup.counts_table in its plain form. Nothing here sends anything or runs a model.
Audits are counted elsewhere: the random-audit tally keeps its own file, so this report has no audit row.
"""
import argparse
import json
import pathlib
import re
import sys

from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_outcome as ro
from lupin_mcp import reuse_refusals as rr
from lupin_mcp.reuse_needset.report_rollup import counts_table

OUTCOME_KINDS  = ( "REUSED", "EXTENDED", "WROTE_NEW" )
UNPARSED       = "unparsed"
OTHER_REASON   = "other (not in this list)"
REASON_LABELS  = (                                                  # ( pattern, label ), in the order the report lists them
    ( r"does not match the REUSE-OUTCOME shape",       "line does not match the shape" ),
    ( r"^receipt \S+ is not in the log",              "receipt not in the log" ),
    ( r"^search \S+ is not in the log for receipt",   "search not in the log for the receipt" ),
    ( r"has no EXCLUDED_ refusal in the log",         "excluded with no logged refusal" ),
    ( r"goes in both id slots",                       "unindexed in only one id slot" ),
    ( r"in the search slot needs unindexed",          "unindexed search beside a real receipt" ),
    ( r"is a file the symbol index holds",            "unindexed file the index holds" ),
    ( r"has an outcome line and no ruling line",      "outcome line with no ruling line" ),
    ( r"^the outcome is \w+ but the ruling",          "outcome and ruling kinds disagree" ),
)


def read_refusals( data_dir ):
    """
    Read the records of refusals.jsonl.

    Requires:
        - data_dir is a directory
    Ensures:
        - returns the records in file order, one dict per line that is a JSON object
        - a missing file gives an empty list; a line that is not a JSON object is skipped, as the writer skips it
    """
    path = pathlib.Path( data_dir ) / rr.REFUSALS_NAME
    if not path.exists(): return []
    out = []
    for raw in path.read_text( encoding="utf-8" ).splitlines():
        try: row = json.loads( raw )
        except ValueError: continue
        if isinstance( row, dict ): out.append( row )
    return out


def reason_label( reason ):
    """Ensures: returns the label of the first pattern the reason matches, or OTHER_REASON."""
    return next( ( label for pattern, label in REASON_LABELS if re.search( pattern, reason ) ), OTHER_REASON )


def count_lookups( records ):
    """
    Count the lookup calls in the call log.

    Requires:
        - records is what merge_call_logs returns
    Ensures:
        - returns { name: count } in a fixed order: one entry per lookup tool for calls that logged no error, then the lookups that failed
        - every call counts, so the same need looked up twice is two lookups
    """
    calls = [ r for r in records if r.get( "tool" ) in eg.RECEIPT_TOOLS ]
    out   = { tool: sum( 1 for r in calls if r[ "tool" ] == tool and not r.get( "error" ) ) for tool in eg.RECEIPT_TOOLS }
    out[ "failed (any lookup tool)" ] = sum( 1 for r in calls if r.get( "error" ) )
    return out


def count_outcomes( rows ):
    """
    Count the scanned outcome lines by kind.

    Requires:
        - rows is what read_refusals returns
    Ensures:
        - returns { kind: count } for `REUSED`, `EXTENDED` and `WROTE_NEW` in that order, then `unparsed` for a line off the shape
        - each record counts once
    """
    out = { kind: 0 for kind in OUTCOME_KINDS } | { UNPARSED: 0 }
    for row in rows:
        parsed = ro.parse_outcomes( row.get( "line", "" ) )
        out[ parsed[ 0 ][ "outcome" ] if parsed else UNPARSED ] += 1
    return out


def count_refusals( rows ):
    """
    Count the refusals by reason.

    Requires:
        - rows is what read_refusals returns
    Ensures:
        - returns { label: count } with every label in REASON_LABELS in order, zeros included, then the other row
        - a refused record with two reasons counts under each
        - an accepted record counts nowhere here
    """
    out = { label: 0 for _, label in REASON_LABELS } | { OTHER_REASON: 0 }
    for row in rows:
        for reason in row.get( "reasons", [] ): out[ reason_label( reason ) ] += 1
    return out


def report( records, rows ):
    """
    Render the behaviour report in its plain form.

    Requires:
        - records is what merge_call_logs returns; rows is what read_refusals returns
    Ensures:
        - returns four counts tables joined by a blank line: lookups, scanned lines by status, outcome lines by kind, refusals by reason
    """
    status = { "accepted": sum( 1 for r in rows if r.get( "status" ) == "accepted" ), "refused": sum( 1 for r in rows if r.get( "status" ) == "refused" ) }
    return "\n\n".join( [ counts_table( "Lookups", count_lookups( records ) ), counts_table( "Scanned outcome lines", status ),
                          counts_table( "Outcome lines by kind", count_outcomes( rows ) ), counts_table( "Refusals by reason", count_refusals( rows ) ) ] )


def main( argv=None, out=None ):
    """
    Command line: --data-dir D [--log-dir D].

    Ensures:
        - prints the report; --data-dir holds refusals.jsonl and, unless --log-dir says otherwise, the call-log folder
        - returns 0
    """
    ap = argparse.ArgumentParser( description="Count lookups, outcome lines by kind and refusals by reason." )
    ap.add_argument( "--data-dir", required=True )
    ap.add_argument( "--log-dir", default=None, help="the call log folder; default is <data dir>/call-log" )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    records, _bad = eg.merge_call_logs( a.log_dir or pathlib.Path( a.data_dir ) / "call-log" )
    print( report( records, read_refusals( a.data_dir ) ), file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
