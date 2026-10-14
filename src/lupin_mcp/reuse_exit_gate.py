#!/usr/bin/env python3
"""
The exit gate for review integration: did the reviewer look before ruling?

Inputs, per crew run:

    - the run's added definitions, from `python -m cosa.repo.symindex diff OLD NEW --all`, saved as JSON
    - the review document, where each ruling is one line:
      `RULING <symbol id> :: <ruling> :: reuse-receipt: <id>`, with the ruling `DUPLICATE`,
      `EXTEND <symbol>` or `DISTINCT <why>`

For all runs together there are the per-session call logs under `<data>/call-log/*.jsonl`.
Each seat runs its own server, so one file shows only that seat's calls. This script merges them all.

A new definition passes when it has two things:

    - a `fetch_similar` call keyed on its symbol id that returned a receipt
    - a ruling that cites one of that definition's receipts

A matched log line proves a call happened. The cited ruling proves the reviewer used it.
Fewer than `MIN_NEW` definitions in total cannot pass, so a near-empty diff proves nothing.
"""
import argparse
import ast
import json
import pathlib
import re
import sys

MIN_NEW = 10

RULING_RE = re.compile( r"^\s*RULING\s+(?P<id>\S+)\s+::\s+(?P<ruling>DUPLICATE|EXTEND\s+\S+|DISTINCT\s+\S.*?)\s+::\s+reuse-receipt:\s*(?P<rid>[0-9A-Za-z_-]+)\s*$" )
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


def parse_rulings( text ):
    """
    Read the ruling lines of a review document.

    Ensures:
        - returns { symbol id: [ { ruling, receipt } ] } for every line in the ruling format
        - other lines are ignored
    """
    out = {}
    for line in text.splitlines():
        m = RULING_RE.match( line )
        if m: out.setdefault( m.group( "id" ), [] ).append( { "ruling": m.group( "ruling" ), "receipt": m.group( "rid" ) } )
    return out


def check_run( added, receipts, rulings ):
    """
    Give each added symbol a status.

    Requires:
        - added is a list of symbol ids
        - receipts and rulings are what receipts_by_symbol and parse_rulings return
    Ensures:
        - returns one { id, status } per added id
        - status is `OK` when a ruling cites one of the symbol's receipts
        - status is `NO_CALL` when the symbol has no `fetch_similar` receipt
        - status is `NO_RULING` when it has a receipt and no ruling line
        - status is `WRONG_RECEIPT` when rulings exist and none cites a receipt of the symbol
    """
    rows = []
    for sid in added:
        have, cited = receipts.get( sid, set() ), rulings.get( sid, [] )
        if not have:                                          status = "NO_CALL"
        elif not cited:                                       status = "NO_RULING"
        elif any( c[ "receipt" ] in have for c in cited ):    status = "OK"
        else:                                                 status = "WRONG_RECEIPT"
        rows.append( { "id": sid, "status": status } )
    return rows


def run_gate( runs, log_dir, min_new=MIN_NEW ):
    """
    Run the gate over every crew run.

    Requires:
        - runs is a list of { "diff": path to the diff JSON, "review": path to the review document }
    Ensures:
        - returns { passed, total_new, bad_log_lines, reasons, runs: [ { diff, review, rows } ] }
        - passed only when there is a run, total_new >= min_new and every row is `OK`
        - a diff that reports algorithm_changed has no per-symbol list and fails with that reason
    """
    records, bad = merge_call_logs( log_dir )
    receipts, out, reasons, total = receipts_by_symbol( records ), [], [], 0
    for run in runs:
        diff = json.loads( pathlib.Path( run[ "diff" ] ).read_text( encoding="utf-8" ) )
        if "algorithm_changed" in diff:
            reasons.append( f"{run[ 'diff' ]}: pin algorithm changed, no per-symbol diff" ); continue
        rows = check_run( diff[ "added" ], receipts, parse_rulings( pathlib.Path( run[ "review" ] ).read_text( encoding="utf-8" ) ) )
        total += len( rows )
        reasons += [ f"{r[ 'id' ]}: {r[ 'status' ]}" for r in rows if r[ "status" ] != "OK" ]
        out.append( { "diff": run[ "diff" ], "review": run[ "review" ], "rows": rows } )
    if not runs: reasons.append( "no runs given" )
    if total < min_new: reasons.append( f"only {total} new definitions, at least {min_new} required" )
    return { "passed": not reasons, "total_new": total, "bad_log_lines": bad, "reasons": reasons, "runs": out }


def main( argv=None, out=None ):
    """
    Command line: --log-dir D --run DIFF.json:review.md [--run ...] [--min-new N].

    Ensures:
        - prints the result as JSON on `out`
        - returns 0 on a pass, 1 on a fail, 2 on a malformed --run
    """
    ap = argparse.ArgumentParser( description="Match new definitions to fetch_similar calls and cited rulings." )
    ap.add_argument( "--log-dir", required=True )
    ap.add_argument( "--run", action="append", default=[] )
    ap.add_argument( "--min-new", type=int, default=MIN_NEW )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    runs = []
    for spec in a.run:
        diff, sep, review = spec.partition( ":" )
        if not sep or not diff or not review:
            print( f"--run must be DIFF.json:review.md, got {spec!r}", file=sys.stderr ); return 2
        runs.append( { "diff": diff, "review": review } )
    res = run_gate( runs, a.log_dir, a.min_new )
    print( json.dumps( res, indent=2 ), file=out )
    return 0 if res[ "passed" ] else 1


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
