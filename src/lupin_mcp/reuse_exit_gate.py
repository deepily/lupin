#!/usr/bin/env python3
"""
The exit gate for review integration: did the reviewer look before ruling?

Inputs, per crew run:

    - the run's added definitions, from `python -m cosa.repo.symindex diff OLD NEW --all`, saved as JSON
    - the review document, where each ruling is one line:
      `RULING <symbol id> :: <ruling> :: reuse-receipt: <id>`, with the ruling `DUPLICATE`,
      `EXTEND <symbol>` or `DISTINCT <why>`. A `DISTINCT` ruling also ends `:: search: <search id>`.
    - the same document's `SEARCHED <symbol id> :: <search id> :: <candidate id> :: <value> :: <why>` lines,
      one for each candidate of a recorded search. The value is `SAME_JOB`, `RELATED` or `UNRELATED`.

For all runs together there are the per-session call logs under `<data>/call-log/*.jsonl`.
Each seat runs its own server, so one file shows only that seat's calls. This script merges them all.

The gate takes the first two runs together, as the plan says, and counts their new
definitions as one total. Any other number of runs fails. One run may be empty when the pair holds
the floor. The floor is on the pair, as the plan says.

A new definition passes when it has two things:

    - a `fetch_similar` call keyed on its symbol id that returned a receipt
    - a ruling that cites one of that definition's receipts

A matched log line proves a call happened. The cited ruling proves the reviewer used it.
A definition that sendable() would not send has no receipt, because nothing was sent. Its call logs an error
starting with `EXCLUDED_`, and the gate reports it as `EXCLUDED` with that cause. It passes
only with a ruling line for the symbol whose receipt token is exactly `excluded`.
Fewer than `MIN_NEW` definitions in total cannot pass, so a near-empty diff proves nothing.

A `DISTINCT` ruling passes only with a recorded search. The server logs each `record_search` call and writes its record
under `<data>/search-records`, so a ruling cannot cite a search that never ran. The ruling must cite that search, and
every candidate of it needs a `SEARCHED` line that is not `SAME_JOB`. An empty search needs a `none` line with its reason.
A gate that is not given the searches refuses every `DISTINCT` ruling.
"""
import argparse
import ast
import json
import pathlib
import re
import sys

MIN_NEW         = 10
RUNS_REQUIRED   = 2
EXCLUDED_PREFIX = "EXCLUDED_"
EXCLUDED_TOKEN  = "excluded"
NO_CANDIDATE    = "none"                                        # the word that stands for the candidate of an empty search

RULING_RE = re.compile( r"^\s*RULING\s+(?P<id>\S+)\s+::\s+(?P<ruling>DUPLICATE|EXTEND\s+\S+|DISTINCT\s+\S.*?)\s+::\s+reuse-receipt:\s*(?P<rid>[0-9A-Za-z_-]+)"
                        r"(?:\s+::\s+search:\s*(?P<search>rs-[0-9a-f]{10}))?\s*$" )
RULING_LEAD_RE = re.compile( r"^\s*RULING\b" )
SEARCHED_RE = re.compile( r"^\s*SEARCHED\s+(?P<id>\S+)\s+::\s+(?P<search>rs-[0-9a-f]{10})\s+::\s+"
                          r"(?:none\s+::\s+(?P<none_why>\S.*?)|(?P<cand>\S+)\s+::\s+(?P<value>SAME_JOB|RELATED|UNRELATED)\s+::\s+(?P<why>\S.*?))\s*$" )
SEARCHED_LEAD_RE = re.compile( r"^\s*SEARCHED\b" )
SEARCH_ID_RE  = re.compile( r"^rs-[0-9a-f]{10}$" )
RECEIPT_ID_RE = re.compile( r"[0-9a-f]{16}" )                  # read with fullmatch, so it has no anchors to lose
ENTRY_RE  = re.compile( r"""['"]entry['"]\s*:\s*(['"])(?P<id>.+?)\1""" )


def merge_call_logs( log_dir ):
    """
    Merge every per-session call log into one list.

    Requires:
        - log_dir is a directory of per-session JSONL files
    Ensures:
        - returns ( records, bad_lines ), the records of every *.jsonl file in name order
        - a line that is not a JSON object is counted in bad_lines and skipped
    """
    records, bad = [], 0
    for path in sorted( pathlib.Path( log_dir ).glob( "*.jsonl" ) ):
        for line in path.read_text( encoding="utf-8" ).splitlines():
            if not line.strip(): continue
            try:
                rec = json.loads( line )
            except ValueError:
                bad += 1; continue
            if isinstance( rec, dict ): records.append( rec )
            else: bad += 1
    return records, bad


def entry_of( record ):
    """
    Read the `entry` argument of one logged call.

    Ensures:
        - returns the `entry` argument, or None when the call has none
        - the args field is a repr cut at 300 characters, so a literal that no longer parses
          falls back to a pattern match on the entry key
    """
    args = record.get( "args" )
    if not isinstance( args, str ): return None
    try:
        parsed = ast.literal_eval( args )
    except ( ValueError, SyntaxError ):
        m = ENTRY_RE.search( args )
        return m.group( "id" ) if m else None
    return parsed.get( "entry" ) if isinstance( parsed, dict ) else None


def receipts_by_symbol( records ):
    """
    Collect the receipts each symbol was asked about under.

    Ensures:
        - returns { symbol id: set of receipt ids }
        - only `fetch_similar` calls that carry a receipt id and logged no error count
    """
    out = {}
    for r in records:
        if r.get( "tool" ) != "fetch_similar" or not r.get( "receipt_id" ) or r.get( "error" ): continue
        entry = entry_of( r )
        if entry: out.setdefault( entry, set() ).add( r[ "receipt_id" ] )
    return out


def exclusions_by_symbol( records ):
    """
    Collect the definitions the tool refused to send.

    Ensures:
        - returns { symbol id: cause } over `fetch_similar` calls whose error starts with `EXCLUDED_`
        - the cause is the error name after the prefix
    """
    out = {}
    for r in records:
        err = r.get( "error" )
        if r.get( "tool" ) != "fetch_similar" or not isinstance( err, str ) or not err.startswith( EXCLUDED_PREFIX ): continue
        entry = entry_of( r )
        if entry: out[ entry ] = err[ len( EXCLUDED_PREFIX ): ]
    return out


def parse_rulings( text ):
    """
    Read the ruling lines of a review document.

    Ensures:
        - returns { symbol id: [ { ruling, receipt, search } ] } for every line in the ruling format
        - search is the id the line cites after `:: search:`, or None when it has no such tail
        - other lines are ignored
    """
    out = {}
    for line in text.splitlines():
        m = RULING_RE.match( line )
        if m: out.setdefault( m.group( "id" ), [] ).append( { "ruling": m.group( "ruling" ), "receipt": m.group( "rid" ), "search": m.group( "search" ) } )
    return out


def unparsed_ruling_lines( text ):
    """
    Find the lines that open as a ruling and do not read as one.

    Ensures:
        - returns the stripped text of every line that opens with the ruling keyword and that RULING_RE does not match, in document order
        - a line that does not open with that keyword is never returned
    """
    return [ line.strip() for line in text.splitlines() if RULING_LEAD_RE.match( line ) and not RULING_RE.match( line ) ]


def parse_searched( text ):
    """
    Read the `SEARCHED` lines of a review document.

    Ensures:
        - returns { symbol id: { search id: { candidate id: { value, why } } } } for every line in the `SEARCHED` format
        - the line `SEARCHED <symbol id> :: <search id> :: none :: <why>` gives the candidate id `none` with the value None
        - a candidate named on two lines keeps `SAME_JOB` if either line says it, so a later line cannot undo a finding
        - other lines are ignored
    """
    out = {}
    for line in text.splitlines():
        m = SEARCHED_RE.match( line )
        if not m: continue
        cand = out.setdefault( m.group( "id" ), {} ).setdefault( m.group( "search" ), {} )
        if m.group( "cand" ) is None: cand[ NO_CANDIDATE ] = { "value": None, "why": m.group( "none_why" ) }
        elif m.group( "cand" ) not in cand or cand[ m.group( "cand" ) ][ "value" ] != "SAME_JOB": cand[ m.group( "cand" ) ] = { "value": m.group( "value" ), "why": m.group( "why" ) }
    return out


def unparsed_searched_lines( text ):
    """
    Find the lines that open as a `SEARCHED` line and do not read as one.

    Ensures:
        - returns the stripped text of every line that opens with the `SEARCHED` keyword and that SEARCHED_RE does not match, in document order
    """
    return [ line.strip() for line in text.splitlines() if SEARCHED_LEAD_RE.match( line ) and not SEARCHED_RE.match( line ) ]


def _read_json( path ):
    """Ensures: returns the JSON object in a file, or None when it cannot be read as one."""
    try:
        doc = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ):
        return None
    return doc if isinstance( doc, dict ) else None


def _receipt_symbol( data, receipt_id ):
    """
    Name the symbol a fetch_similar receipt was about.

    Ensures:
        - returns the receipt's query when the receipt is a readable fetch_similar receipt, else None
        - an id that is not 16 hex characters is never turned into a path
    """
    if not isinstance( receipt_id, str ) or not RECEIPT_ID_RE.fullmatch( receipt_id ): return None
    doc = _read_json( data / "receipts" / f"{receipt_id}.json" )
    return doc[ "query" ] if doc is not None and doc.get( "tool" ) == "fetch_similar" and isinstance( doc.get( "query" ), str ) else None


def searches_by_symbol( records, data_dir ):
    """
    Collect the recorded searches each symbol was searched under.

    Requires:
        - records is what merge_call_logs returns; data_dir holds the receipts and search-records folders

    Ensures:
        - returns { symbol id: { search id: [ candidate ids ] } }
        - only `record_search` calls that logged no error and a well-formed search id count
        - the symbol is the record's `entry`, else the query of the fetch_similar receipt the record names
        - the call log only says that a search ran, because its args field is cut at 300 characters and can hide the entry
        - a call whose record file is missing, unreadable, or does not carry its own id yields no search
        - reads the files with plain json, so the gate needs nothing from reuse_tools
    """
    data, out = pathlib.Path( data_dir ), {}
    for r in records:
        sid = r.get( "search_id" )
        if r.get( "tool" ) != "record_search" or r.get( "error" ) or not isinstance( sid, str ) or not SEARCH_ID_RE.match( sid ): continue
        doc = _read_json( data / "search-records" / f"{sid}.json" )
        if doc is None or doc.get( "id" ) != sid or not isinstance( doc.get( "candidates" ), list ): continue
        symbol = doc.get( "entry" ) or _receipt_symbol( data, doc.get( "receipt_id" ) )
        if not symbol: continue
        out.setdefault( symbol, {} )[ sid ] = [ c[ "id" ] for c in doc[ "candidates" ] if isinstance( c, dict ) and "id" in c ]
    return out


def _search_status( sid, ruling, searches, searched ):
    """
    Judge the recorded search behind one `DISTINCT` ruling.

    Requires:
        - searches is what searches_by_symbol returns, or None when the gate was not given the searches
        - searched is what parse_searched returns for the review, or None

    Ensures:
        - returns `NO_SEARCH` when the symbol has no logged search, or searches is None
        - returns `SEARCH_NOT_CITED` when the ruling names no search of the symbol's
        - an empty search is `SEARCH_EMPTY_UNEXPLAINED` without a `none` line, otherwise `OK`
        - returns `CANDIDATES_UNRULED` when a candidate has no `SEARCHED` line, then `DISTINCT_CONTRADICTED` when one is `SAME_JOB`
        - returns `OK` otherwise
    """
    found = ( searches or {} ).get( sid )
    if not found: return "NO_SEARCH"
    if ruling[ "search" ] not in found: return "SEARCH_NOT_CITED"
    candidates = found[ ruling[ "search" ] ]
    lines      = ( searched or {} ).get( sid, {} ).get( ruling[ "search" ], {} )
    if not candidates: return "OK" if NO_CANDIDATE in lines else "SEARCH_EMPTY_UNEXPLAINED"
    if any( c not in lines for c in candidates ): return "CANDIDATES_UNRULED"
    if any( lines[ c ][ "value" ] == "SAME_JOB" for c in candidates ): return "DISTINCT_CONTRADICTED"
    return "OK"


def check_run( added, receipts, rulings, excluded=None, searches=None, searched=None ):
    """
    Give each added symbol a status.

    Requires:
        - added is a list of symbol ids
        - receipts and rulings are what receipts_by_symbol and parse_rulings return
        - excluded is what exclusions_by_symbol returns, or None
        - searches and searched are what searches_by_symbol and parse_searched return; None means the gate was not given them
    Ensures:
        - returns one { id, status } per added id, plus `cause` for an excluded one
        - status is `OK` when a ruling cites one of the symbol's own receipts
        - a receipt of another symbol never satisfies a ruling: that row is `WRONG_RECEIPT`
        - status is `EXCLUDED` when the symbol has no receipt, was refused for sending and a ruling line carries the token `excluded`
        - status is `EXCLUDED_NO_RULING` for the same symbol with no ruling line
        - status is `EXCLUDED_BAD_TOKEN` for the same symbol when every ruling line carries another token
        - status is `NO_CALL` when the symbol has no receipt and no recorded refusal
        - status is `NO_RULING` when it has a receipt and no ruling line
        - status is `WRONG_RECEIPT` when rulings exist and none cites a receipt of the symbol
        - a row that would be `OK` or `EXCLUDED` through a `DISTINCT` ruling takes that ruling's search status when it is not `OK`
        - searches None fails closed: a `DISTINCT` ruling gets `NO_SEARCH`, never a skipped rule; `DUPLICATE` and `EXTEND` rulings are unaffected
    """
    excluded = excluded or {}
    rows = []
    for sid in added:
        have, cited = receipts.get( sid, set() ), rulings.get( sid, [] )
        row = { "id": sid }
        if not have and sid in excluded:
            if not cited:                                           row[ "status" ] = "EXCLUDED_NO_RULING"
            elif any( c[ "receipt" ] == EXCLUDED_TOKEN for c in cited ): row[ "status" ] = "EXCLUDED"
            else:                                                   row[ "status" ] = "EXCLUDED_BAD_TOKEN"
            row[ "cause" ] = excluded[ sid ]
        elif not have:                                        row[ "status" ] = "NO_CALL"
        elif not cited:                                       row[ "status" ] = "NO_RULING"
        elif any( c[ "receipt" ] in have for c in cited ):    row[ "status" ] = "OK"
        else:                                                 row[ "status" ] = "WRONG_RECEIPT"
        if row[ "status" ] in ( "OK", "EXCLUDED" ):
            token    = EXCLUDED_TOKEN if row[ "status" ] == "EXCLUDED" else None
            distinct = [ c for c in cited if ( c[ "receipt" ] == token if token else c[ "receipt" ] in have ) and c[ "ruling" ].startswith( "DISTINCT" ) ]
            judged   = [ s for s in ( _search_status( sid, c, searches, searched ) for c in distinct ) if s != "OK" ]
            if judged: row[ "status" ] = judged[ 0 ]
        rows.append( row )
    return rows


def run_gate( runs, log_dir, min_new=MIN_NEW, runs_required=RUNS_REQUIRED, data_dir=None ):
    """
    Run the gate over every crew run.

    Requires:
        - runs is a list of { "diff": path to the diff JSON, "review": path to the review document }
        - data_dir holds the receipts and search-records folders; None means the parent of log_dir
    Ensures:
        - returns { passed, total_new, bad_log_lines, reasons, runs: [ { diff, review, rows } ] }
        - passed only when len( runs ) == runs_required, the runs name different diffs, the unique
          ids across the pair number min_new or more, and every row is `OK` or `EXCLUDED`
        - the floor is on the pair, so one run may add no definition when the other carries the floor
        - total_new counts each symbol id once, so one run given twice cannot reach the floor
        - a diff that reports algorithm_changed has no per-symbol list and fails with that reason
        - a review line that opens with the ruling keyword and does not parse fails the gate, with the line in the reason
        - the same holds for a line that opens with the `SEARCHED` keyword
        - the searches are always read and passed on, so a `DISTINCT` ruling is judged on its recorded search in every run
    """
    records, bad = merge_call_logs( log_dir )
    data_dir = pathlib.Path( log_dir ).parent if data_dir is None else data_dir
    receipts, excluded, out, reasons, seen = receipts_by_symbol( records ), exclusions_by_symbol( records ), [], [], set()
    searches = searches_by_symbol( records, data_dir )
    diffs = [ str( pathlib.Path( r[ "diff" ] ).resolve() ) for r in runs ]
    if len( set( diffs ) ) != len( diffs ): reasons.append( "two runs name the same diff file" )
    for run in runs:
        diff = json.loads( pathlib.Path( run[ "diff" ] ).read_text( encoding="utf-8" ) )
        if "algorithm_changed" in diff:
            reasons.append( f"{run[ 'diff' ]}: pin algorithm changed, no per-symbol diff" ); continue
        review = pathlib.Path( run[ "review" ] ).read_text( encoding="utf-8" )
        reasons += [ f"{run[ 'review' ]}: unparsed RULING line: {line}" for line in unparsed_ruling_lines( review ) ]
        reasons += [ f"{run[ 'review' ]}: unparsed SEARCHED line: {line}" for line in unparsed_searched_lines( review ) ]
        rows = check_run( diff[ "added" ], receipts, parse_rulings( review ), excluded, searches, parse_searched( review ) )
        seen.update( r[ "id" ] for r in rows )
        reasons += [ f"{r[ 'id' ]}: {r[ 'status' ]}" for r in rows if r[ "status" ] not in ( "OK", "EXCLUDED" ) ]
        out.append( { "diff": run[ "diff" ], "review": run[ "review" ], "rows": rows } )
    total = len( seen )
    if len( runs ) != runs_required: reasons.append( f"exactly {runs_required} runs are required together, got {len( runs )}" )
    if total < min_new: reasons.append( f"only {total} new definitions, at least {min_new} required" )
    return { "passed": not reasons, "total_new": total, "bad_log_lines": bad, "reasons": reasons, "runs": out }


def main( argv=None, out=None ):
    """
    Command line: --log-dir D --run DIFF:review [--run ...] [--min-new N] [--data-dir D].

    Ensures:
        - prints the result as JSON on `out`
        - returns 0 on a pass, 1 on a fail, 2 on a malformed --run
    """
    ap = argparse.ArgumentParser( description="Match new definitions to fetch_similar calls and cited rulings." )
    ap.add_argument( "--log-dir", required=True )
    ap.add_argument( "--run", action="append", default=[] )
    ap.add_argument( "--min-new", type=int, default=MIN_NEW )
    ap.add_argument( "--data-dir", default=None, help="the folder with receipts and search-records; default is the parent of --log-dir" )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    runs = []
    for spec in a.run:
        diff, sep, review = spec.partition( ":" )
        if not sep or not diff or not review:
            print( f"--run must be DIFF.json:review.md, got {spec!r}", file=sys.stderr ); return 2
        runs.append( { "diff": diff, "review": review } )
    res = run_gate( runs, a.log_dir, a.min_new, data_dir=a.data_dir )
    print( json.dumps( res, indent=2 ), file=out )
    return 0 if res[ "passed" ] else 1


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
