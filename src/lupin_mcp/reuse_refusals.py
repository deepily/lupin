"""
Judge the outcome lines of one document and keep a record of every line scanned.

The shape reader, the call-log check, the token check and the kind pairing all live in reuse_outcome.
This module runs them on each line of one named document and appends what happened to <data dir>/refusals.jsonl.
A record is kept for a line that passed and for one that was refused, with the reasons. A later count can read the whole corpus.
The record is made once per document hash and line number. A second run on the same text adds nothing.
Nothing here sends anything or runs a model.
"""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import sys
import time

from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_outcome as ro

REFUSALS_NAME = "refusals.jsonl"
NOT_CHECKED   = 3                                               # the exit code for a run that could not check: neither a pass nor a refusal


def document_hash( text ):
    """Ensures: returns the sha256 of the document text, as hex."""
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def scanned_lines( text ):
    """
    List the lines the checker scans.

    Requires:
        - text is a string
    Ensures:
        - returns { n, line, outcome } for every line that opens with the keyword and is not a template line, in document order
        - n counts from 1; outcome is the parsed line, or None when the line does not match the shape
    """
    out = []
    for n, raw in enumerate( text.splitlines(), 1 ):
        if not ro.OUTCOME_LEAD_RE.match( raw ) or ro.TEMPLATE_RE.match( raw ): continue
        parsed = ro.parse_outcomes( raw )
        out.append( { "n": n, "line": raw.strip(), "outcome": parsed[ 0 ] if parsed else None } )
    return out


def judge( text, receipts, searches, exclusions, rulings, root ):
    """
    Judge every scanned line of a document.

    Requires:
        - receipts, searches, exclusions and rulings are what receipts_by_id, searches_by_receipt, exclusions_by_symbol and parse_rulings return
        - root is a repository root
    Ensures:
        - returns { n, line, status, reasons, pairs } per scanned line; status is `accepted` or `refused`
        - a line that does not match the shape is refused with that reason and no pairs
        - every other line gets the reasons of the token check, the call-log check and the kind pairing, each run on that line alone
        - pairs is [ symbol id, receipt id ] for each ruling that cites the line's receipt, the pairs the kind check read
    """
    out = []
    for s in scanned_lines( text ):
        o = s[ "outcome" ]
        if o is None: reasons, pairs = [ "the line does not match the REUSE-OUTCOME shape" ], []
        else:
            reasons = [ r[ "reason" ] for r in ro.token_refusals( [ o ], exclusions, root ) + ro.log_refusals( [ o ], receipts, searches ) + ro.pairing_refusals( [ o ], rulings ) ]
            pairs   = [ [ sym, row[ "receipt" ] ] for sym, rows in rulings.items() for row in rows if row[ "receipt" ] == o[ "receipt" ] ]
        out.append( { "n": s[ "n" ], "line": s[ "line" ], "status": "refused" if reasons else "accepted", "reasons": reasons, "pairs": pairs } )
    return out


def record( data_dir, text, verdicts ):
    """
    Append one record per judged line, once per document hash and line number.

    Requires:
        - data_dir is an existing directory; verdicts comes from judge
    Ensures:
        - appends one JSON line per verdict that the file does not already hold for ( document hash, n )
        - each record is written with a single write, under an exclusive lock held from the read of the existing keys to the last write, so two writers never tear or double a line
        - a line of the file that is not a JSON object with a document hash and n is ignored when reading the keys
        - a last line with no newline is left alone and the next record starts on a new line
        - returns the number of records appended
    """
    doc, path, stamp = document_hash( text ), pathlib.Path( data_dir ) / REFUSALS_NAME, time.strftime( "%Y-%m-%dT%H:%M:%S%z" )
    with path.open( "a+b" ) as f:
        fcntl.flock( f, fcntl.LOCK_EX )
        try:
            f.seek( 0 )
            held, keys = f.read(), set()
            for raw in held.splitlines():
                try: row = json.loads( raw )
                except ValueError: continue
                if isinstance( row, dict ) and "doc" in row and "n" in row: keys.add( ( row[ "doc" ], row[ "n" ] ) )
            lead, added = b"" if not held or held.endswith( b"\n" ) else b"\n", 0
            for v in verdicts:
                if ( doc, v[ "n" ] ) in keys: continue
                f.write( lead + ( json.dumps( { "doc": doc, **v, "at": stamp }, sort_keys=True ) + "\n" ).encode( "utf-8" ) )
                f.flush()
                lead, added = b"", added + 1
        finally: fcntl.flock( f, fcntl.LOCK_UN )
    return added


def default_data_dir( root ):
    """
    Resolve the data folder the way the lookup tools do.

    Ensures:
        - returns LUPIN_REUSE_DATA_DIR when it is set, else the per-repository data directory of root
    """
    from lupin_mcp import reuse_tools as rt
    return os.environ.get( "LUPIN_REUSE_DATA_DIR" ) or str( rt.data_dir( pathlib.Path( root ) ) )


def not_checked( error, out ):
    """
    Report a run that could not read or write what it needed.

    Ensures:
        - prints one JSON object with the error's class and message on `out`
        - returns NOT_CHECKED, which is neither a pass nor a refusal
    """
    print( json.dumps( { "error": f"{type( error ).__name__}: {error}" } ), file=out )
    return NOT_CHECKED


def main( argv=None, out=None ):
    """
    Command line: a document path, then --diff, --root, --data-dir, --log-dir.

    Ensures:
        - judges the outcome lines of the named document, appends the records, and prints a JSON summary
        - the summary holds the document hash, the lines scanned, the lines refused, the records appended, and the new definitions with no outcome line
        - returns 0 when every line is accepted and no definition is missing, 1 otherwise
        - returns 3 with the reason printed when a file cannot be read or written, when the diff is not a symbol index diff, or when it reports algorithm_changed, which lists no definitions to check
    """
    ap = argparse.ArgumentParser( description="Judge the REUSE-OUTCOME lines of one document and keep a record of each." )
    ap.add_argument( "document" )
    ap.add_argument( "--diff", default=None, help="a symbol index diff; each added definition must then have an outcome line" )
    ap.add_argument( "--root", default=".", help="the repository root; default is the current directory" )
    ap.add_argument( "--data-dir", default=None, help="the folder that holds receipts, search-records and refusals.jsonl" )
    ap.add_argument( "--log-dir", default=None, help="the call log folder; default is <data dir>/call-log" )
    a    = ap.parse_args( argv )
    out  = out if out is not None else sys.stdout
    root = pathlib.Path( a.root ).resolve()
    data = pathlib.Path( a.data_dir or default_data_dir( root ) )
    try:
        diff = json.loads( pathlib.Path( a.diff ).read_text( encoding="utf-8" ) ) if a.diff else { "added": [] }
        if not isinstance( diff, dict ) or not isinstance( diff.get( "added", [] ), list ): raise ValueError( f"{a.diff} is not a symbol index diff" )
        if "algorithm_changed" in diff: raise ValueError( f"{a.diff}: the pin algorithm changed, so the diff lists no definitions to check" )
        text          = pathlib.Path( a.document ).read_text( encoding="utf-8" )
        records, _bad = eg.merge_call_logs( a.log_dir or data / "call-log" )
    except ( OSError, ValueError ) as e: return not_checked( e, out )
    rulings  = eg.parse_rulings( text )
    verdicts = judge( text, eg.receipts_by_id( records ), eg.searches_by_receipt( records, data ), eg.exclusions_by_symbol( records ), rulings, root )
    missing  = ro.missing_outcome_refusals( diff.get( "added", [] ), ro.parse_outcomes( text ), rulings )
    refused  = [ v for v in verdicts if v[ "status" ] == "refused" ]
    try: appended = record( data, text, verdicts )
    except OSError as e: return not_checked( e, out )
    print( json.dumps( { "document": document_hash( text ), "scanned": len( verdicts ), "refused": len( refused ), "appended": appended,
                         "refusals": [ { "n": v[ "n" ], "reasons": v[ "reasons" ] } for v in refused ], "missing": missing }, indent=2 ), file=out )
    return 1 if refused or missing else 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
