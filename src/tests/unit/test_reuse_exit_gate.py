"""
Unit tests for the exit gate over fixture call logs and review documents.

Each test writes its own per-session logs, diff and review. A definition passes only with a
`fetch_similar` receipt and a ruling that cites it.
"""
import io
import json
import pathlib
import re

import cosa.utils.util as cu
from lupin_mcp import reuse_exit_gate as eg

SKILL = pathlib.Path( cu.get_project_root() ) / ".claude" / "skills" / "reuse-reviewer" / "SKILL.md"
SID   = "rs-0123456789"
SID2  = "rs-abcdef0123"


def _call( session, entry, receipt, tool="fetch_similar", error=None ):
    return { "ts": "2026-10-14T10:00:00+00:00", "tool": tool, "caller": "p " + session, "session": session,
             "receipt_id": receipt, "error": error, "args": repr( { "entry": entry } ) }


def _write_log( d, name, records, extra=() ):
    ( d / f"{name}.jsonl" ).write_text( "\n".join( [ json.dumps( r ) for r in records ] + list( extra ) ) + "\n", encoding="utf-8" )


def _ruling( sid, ruling, rid ):
    return f"RULING {sid} :: {ruling} :: reuse-receipt: {rid}"


def _search_call( session, search_id, entry=None, receipt=None, tool="record_search", error=None ):
    args = { "entry": entry } if entry is not None else { "receipt_id": receipt }
    return { "ts": "2026-10-14T10:00:00+00:00", "tool": tool, "caller": "p " + session, "session": session,
             "receipt_id": receipt, "search_id": search_id, "error": error, "args": repr( args ) }


def _write_record( data, search_id, cands, entry=None, receipt_id=None, **over ):
    """Ensures: writes the search record the server would write, with these candidate ids."""
    ( data / "search-records" ).mkdir( parents=True, exist_ok=True )
    doc = { "id": search_id, "entry": entry, "receipt_id": receipt_id, "candidates": [ { "id": c } for c in cands ] }
    doc.update( over )
    ( data / "search-records" / f"{search_id}.json" ).write_text( json.dumps( doc ), encoding="utf-8" )


def _write_receipt( data, receipt_id, tool, query ):
    ( data / "receipts" ).mkdir( parents=True, exist_ok=True )
    ( data / "receipts" / f"{receipt_id}.json" ).write_text( json.dumps( { "tool": tool, "query": query } ), encoding="utf-8" )


def _two_runs( tmp_path, run_a, run_b, calls_a=(), calls_b=(), pad=True ):
    """
    Write two crew runs and their call logs.

    Requires:
        - run_a and run_b are ( added ids, review lines ) pairs
        - an empty run_b is filled with one valid definition, `m.pad`, unless pad is false
    Ensures:
        - returns ( log dir, [ run dict, run dict ] ) in the shape run_gate takes
    """
    logs = tmp_path / "call-log"; logs.mkdir()
    if pad and not run_b[ 0 ]:
        run_b, calls_b = ( [ "m.pad" ], [ _ruling( "m.pad", "DUPLICATE", "rpad" ) ] ), [ _call( "b", "m.pad", "rpad" ) ]
    _write_log( logs, "sess-a", list( calls_a ) ); _write_log( logs, "sess-b", list( calls_b ) )
    runs = []
    for n, ( ids, lines ) in enumerate( ( run_a, run_b ) ):
        diff = tmp_path / f"diff{n}.json"; diff.write_text( json.dumps( { "added": ids, "removed": [], "changed": [] } ), encoding="utf-8" )
        rev  = tmp_path / f"review{n}.md"; rev.write_text( "\n".join( lines ) + "\n", encoding="utf-8" )
        runs.append( { "diff": str( diff ), "review": str( rev ) } )
    return logs, runs


def _ten( prefix="m.f" ):
    """Ensures: returns ten symbol ids, each with its own receipt id."""
    ids = [ f"{prefix}{i}" for i in range( 10 ) ]
    return ids, { i: f"r{prefix.replace( '.', '' )}{n}" for n, i in enumerate( ids ) }


def test_merge_skips_blank_bad_and_non_object_lines( tmp_path ):
    _write_log( tmp_path, "s1", [ _call( "s1", "m.a", "r1" ) ], extra=[ "", "not json", "[1, 2]" ] )
    recs, bad = eg.merge_call_logs( tmp_path )
    assert len( recs ) == 1 and bad == 2


def test_merge_reads_every_file_in_name_order( tmp_path ):
    _write_log( tmp_path, "b", [ _call( "b", "m.b", "r2" ) ] ); _write_log( tmp_path, "a", [ _call( "a", "m.a", "r1" ) ] )
    recs, bad = eg.merge_call_logs( tmp_path )
    assert [ r[ "session" ] for r in recs ] == [ "a", "b" ] and bad == 0


def test_entry_of_variants():
    assert eg.entry_of( { "args": "{'entry': 'm.f'}" } ) == "m.f"
    assert eg.entry_of( { "args": "{'need': 'x'}" } ) is None
    assert eg.entry_of( { "args": "['m.f']" } ) is None
    assert eg.entry_of( { "args": 5 } ) is None
    assert eg.entry_of( {} ) is None
    assert eg.entry_of( { "args": "{'entry': 'm.f', 'root': '/a/very" } ) == "m.f"       # cut at 300 chars: not a literal any more
    assert eg.entry_of( { "args": "{'need': 'x', 'root': '/a/ve" } ) is None


def test_receipts_by_symbol_keeps_only_clean_fetch_similar_calls():
    recs = [ _call( "a", "m.f", "r1" ), _call( "b", "m.f", "r2" ),
             _call( "a", "m.g", "r3", tool="check_exists" ), _call( "a", "m.h", None ),
             _call( "a", "m.i", "r4", error="UNKNOWN_ENTRY" ), { "tool": "fetch_similar", "receipt_id": "r5", "args": "[]" } ]
    assert eg.receipts_by_symbol( recs ) == { "m.f": { "r1", "r2" } }


def test_parse_rulings_accepts_the_three_forms_and_ignores_prose():
    text = "\n".join( [ "# review", _ruling( "m.a", "DUPLICATE", "ab12" ), _ruling( "m.b", "EXTEND m.other", "cd34" ),
                       _ruling( "m.c", "DISTINCT it parses a different format", "ef56" ), "RULING m.d :: MAYBE :: reuse-receipt: 99",
                       "m.e looks distinct" ] )
    got = eg.parse_rulings( text )
    assert set( got ) == { "m.a", "m.b", "m.c" }
    assert got[ "m.c" ][ 0 ] == { "ruling": "DISTINCT it parses a different format", "receipt": "ef56", "search": None }


def test_a_distinct_ruling_may_end_with_the_search_it_cites_and_the_why_may_hold_a_separator():
    line = _ruling( "m.a", "DISTINCT it reads :: not writes", "ab12" ) + f" :: search: {SID}"
    assert eg.parse_rulings( line ) == { "m.a": [ { "ruling": "DISTINCT it reads :: not writes", "receipt": "ab12", "search": SID } ] }
    assert eg.parse_rulings( _ruling( "m.a", "DUPLICATE", "ab12" ) + f" :: search: {SID}" )[ "m.a" ][ 0 ][ "search" ] == SID      # the parser reads it, the gate judges it


def test_a_search_tail_with_a_malformed_id_is_an_unparsed_ruling_line_and_names_it():
    for tail in ( "rs-xyz", "rs-0123456789a", "0123456789", "" ):
        bad = _ruling( "m.a", "DISTINCT it differs", "ab12" ) + f" :: search: {tail}"
        assert eg.parse_rulings( bad ) == {} and eg.unparsed_ruling_lines( "ok\n" + bad ) == [ bad.strip() ], tail


def test_parse_searched_reads_both_forms_and_the_unparsed_report_names_the_rest():
    text = "\n".join( [ f"SEARCHED m.a :: {SID} :: m.c1 :: RELATED :: it only formats", f"SEARCHED m.a :: {SID} :: m.c2 :: UNRELATED :: other job :: with a separator",
                       f"SEARCHED m.b :: {SID2} :: none :: the terms were rare", "prose about SEARCHED things" ] )
    assert eg.parse_searched( text ) == { "m.a": { SID: { "m.c1": { "value": "RELATED", "why": "it only formats" },
                                                          "m.c2": { "value": "UNRELATED", "why": "other job :: with a separator" } } },
                                          "m.b": { SID2: { "none": { "value": None, "why": "the terms were rare" } } } }
    bad = [ f"SEARCHED m.a :: {SID} :: m.c1 :: MAYBE :: no", f"SEARCHED m.a :: {SID} :: m.c1 :: RELATED ::", f"SEARCHED m.a :: rs-bad :: m.c1 :: RELATED :: x",
            f"  SEARCHED m.a :: {SID} :: none ::", "SEARCHED" ]
    assert eg.unparsed_searched_lines( "\n".join( [ text ] + bad ) ) == [ b.strip() for b in bad ]
    assert eg.unparsed_searched_lines( text ) == []


def test_check_run_assigns_each_status():
    receipts = { "m.ok": { "r1" }, "m.norule": { "r2" }, "m.wrong": { "r3" } }
    rulings  = { "m.ok": [ { "ruling": "DUPLICATE", "receipt": "r1" } ], "m.wrong": [ { "ruling": "DUPLICATE", "receipt": "zz" } ],
                 "m.nocall": [ { "ruling": "DUPLICATE", "receipt": "r9" } ] }
    rows = eg.check_run( [ "m.ok", "m.norule", "m.wrong", "m.nocall" ], receipts, rulings )
    assert { r[ "id" ]: r[ "status" ] for r in rows } == { "m.ok": "OK", "m.norule": "NO_RULING", "m.wrong": "WRONG_RECEIPT", "m.nocall": "NO_CALL" }


def test_check_run_assigns_excluded_statuses():
    rows = eg.check_run( [ "m.priv", "m.priv2", "m.none" ], {}, { "m.priv": [ { "ruling": "DUPLICATE", "receipt": "excluded" } ] },
                         { "m.priv": "SENSITIVE_CONTENT", "m.priv2": "PREFIX" } )
    assert rows == [ { "id": "m.priv", "status": "EXCLUDED", "cause": "SENSITIVE_CONTENT" },
                     { "id": "m.priv2", "status": "EXCLUDED_NO_RULING", "cause": "PREFIX" },
                     { "id": "m.none", "status": "NO_CALL" } ]


def test_a_ruling_that_cites_another_symbols_receipt_is_wrong_receipt():
    """The receipt exists in the log, but it belongs to m.b. m.a's ruling must not pass on it."""
    receipts = { "m.a": { "r-a" }, "m.b": { "r-b" } }
    rulings  = eg.parse_rulings( _ruling( "m.a", "DUPLICATE", "r-b" ) + "\n" + _ruling( "m.b", "DUPLICATE", "r-b" ) )
    rows     = { r[ "id" ]: r[ "status" ] for r in eg.check_run( [ "m.a", "m.b" ], receipts, rulings ) }
    assert rows == { "m.a": "WRONG_RECEIPT", "m.b": "OK" }


def test_exclusions_by_symbol_reads_the_refusal_cause():
    recs = [ _call( "a", "m.p", None, error="EXCLUDED_SENSITIVE_CONTENT" ), _call( "a", "m.q", None, error="EXCLUDED_PREFIX" ),
             _call( "a", "m.r", None, error="UNKNOWN_ENTRY" ), _call( "a", "m.s", None, tool="check_exists", error="EXCLUDED_PREFIX" ),
             { "tool": "fetch_similar", "error": "EXCLUDED_PREFIX", "args": "[]" }, _call( "a", "m.t", "r1" ) ]
    assert eg.exclusions_by_symbol( recs ) == { "m.p": "SENSITIVE_CONTENT", "m.q": "PREFIX" }


def test_gate_passes_when_every_definition_has_call_and_ruling( tmp_path ):
    ids_a, rid_a = _ten( "m.a" ); ids_b, rid_b = _ten( "m.b" )
    logs, runs = _two_runs( tmp_path, ( ids_a[ :5 ], [ _ruling( i, "DUPLICATE", rid_a[ i ] ) for i in ids_a[ :5 ] ] ),
                            ( ids_b[ :5 ], [ _ruling( i, "EXTEND m.x", rid_b[ i ] ) for i in ids_b[ :5 ] ] ),
                            [ _call( "a", i, rid_a[ i ] ) for i in ids_a[ :5 ] ], [ _call( "b", i, rid_b[ i ] ) for i in ids_b[ :5 ] ] )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is True and res[ "total_new" ] == 10 and res[ "reasons" ] == []


def test_the_two_runs_count_together_not_one_by_one( tmp_path ):
    """Five new definitions in each run is ten together: the plan's floor is on the pair."""
    ids_a, rid_a = _ten( "m.a" ); ids_b, rid_b = _ten( "m.b" )
    one = ( ids_a[ :5 ], [ _ruling( i, "DUPLICATE", rid_a[ i ] ) for i in ids_a[ :5 ] ] )
    two = ( ids_b[ :4 ], [ _ruling( i, "DUPLICATE", rid_b[ i ] ) for i in ids_b[ :4 ] ] )
    logs, runs = _two_runs( tmp_path, one, two, [ _call( "a", i, rid_a[ i ] ) for i in ids_a[ :5 ] ], [ _call( "b", i, rid_b[ i ] ) for i in ids_b[ :4 ] ] )
    res = eg.run_gate( runs, logs )
    assert res[ "total_new" ] == 9 and res[ "passed" ] is False and "only 9 new definitions, at least 10 required" in res[ "reasons" ]


def test_gate_refuses_other_than_two_runs( tmp_path ):
    ids, rid = _ten()
    ids_b, rid_b = _ten( "m.g" )
    logs, runs = _two_runs( tmp_path, ( ids[ :5 ], [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ :5 ] ] ),
                            ( ids_b[ :5 ], [ _ruling( i, "DUPLICATE", rid_b[ i ] ) for i in ids_b[ :5 ] ] ),
                            [ _call( "a", i, rid[ i ] ) for i in ids[ :5 ] ], [ _call( "b", i, rid_b[ i ] ) for i in ids_b[ :5 ] ] )
    assert eg.run_gate( runs, logs )[ "passed" ] is True
    one = eg.run_gate( runs[ :1 ], logs )
    assert one[ "passed" ] is False and "exactly 2 runs are required together, got 1" in one[ "reasons" ]
    assert "exactly 2 runs are required together, got 0" in eg.run_gate( [], logs )[ "reasons" ]
    assert eg.run_gate( runs[ :1 ], logs, runs_required=1 )[ "passed" ] is False                          # five definitions are under the floor
    ids_c, rid_c = _ten( "m.h" )
    third = tmp_path / "diff2.json"; third.write_text( json.dumps( { "added": ids_c, "removed": [], "changed": [] } ), encoding="utf-8" )
    ( tmp_path / "review2.md" ).write_text( "\n".join( _ruling( i, "DUPLICATE", rid_c[ i ] ) for i in ids_c ) + "\n", encoding="utf-8" )
    _write_log( logs, "sess-c", [ _call( "c", i, rid_c[ i ] ) for i in ids_c ] )
    three = eg.run_gate( runs + [ { "diff": str( third ), "review": str( tmp_path / "review2.md" ) } ], logs )
    assert three[ "passed" ] is False and "exactly 2 runs are required together, got 3" in three[ "reasons" ]
    assert three[ "total_new" ] == 20                                                                         # only the run count fails it


def test_one_run_given_twice_cannot_reach_the_floor( tmp_path ):
    ids, rid = _ten()
    logs, runs = _two_runs( tmp_path, ( ids[ :5 ], [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ :5 ] ] ), ( [], [] ),
                            [ _call( "a", i, rid[ i ] ) for i in ids[ :5 ] ], pad=False )
    same = eg.run_gate( [ runs[ 0 ], runs[ 0 ] ], logs )
    assert same[ "passed" ] is False and same[ "total_new" ] == 5
    assert "two runs name the same diff file" in same[ "reasons" ] and "only 5 new definitions, at least 10 required" in same[ "reasons" ]
    copy = tmp_path / "copy.json"; copy.write_text( pathlib.Path( runs[ 0 ][ "diff" ] ).read_text( encoding="utf-8" ), encoding="utf-8" )
    again = eg.run_gate( [ runs[ 0 ], { "diff": str( copy ), "review": runs[ 0 ][ "review" ] } ], logs )
    assert again[ "total_new" ] == 5 and again[ "passed" ] is False                                          # a copied diff counts its ids once


def test_an_empty_run_passes_when_the_pair_holds_the_floor_and_fails_when_it_does_not( tmp_path ):
    ids, rid = _ten()
    logs, runs = _two_runs( tmp_path, ( ids, [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids ] ), ( [], [] ), [ _call( "a", i, rid[ i ] ) for i in ids ], pad=False )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is True and res[ "total_new" ] == 10 and res[ "reasons" ] == []              # the floor is on the pair
    ( tmp_path / "short" ).mkdir()
    logs2, runs2 = _two_runs( tmp_path / "short", ( ids[ :9 ], [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ :9 ] ] ), ( [], [] ),
                              [ _call( "a", i, rid[ i ] ) for i in ids[ :9 ] ], pad=False )
    short = eg.run_gate( runs2, logs2 )
    assert short[ "passed" ] is False and short[ "reasons" ] == [ "only 9 new definitions, at least 10 required" ]


def test_gate_fails_on_a_call_without_ruling_and_a_ruling_without_call( tmp_path ):
    ids, rid = _ten()
    calls = [ _call( "a", i, rid[ i ] ) for i in ids[ :9 ] ]                                      # m.f9 never fetched
    rev   = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ 1: ] ]                            # m.f0 never ruled
    logs, runs = _two_runs( tmp_path, ( ids, rev ), ( [], [] ), calls )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is False and sorted( res[ "reasons" ] ) == [ "m.f0: NO_RULING", "m.f9: NO_CALL" ]


def test_gate_fails_when_a_ruling_cites_a_receipt_of_another_symbol( tmp_path ):
    ids, rid = _ten()
    rev = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ 1: ] ] + [ _ruling( ids[ 0 ], "DUPLICATE", rid[ ids[ 1 ] ] ) ]
    logs, runs = _two_runs( tmp_path, ( ids, rev ), ( [], [] ), [ _call( "a", i, rid[ i ] ) for i in ids ] )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is False and res[ "reasons" ] == [ "m.f0: WRONG_RECEIPT" ]


def test_an_excluded_definition_shows_its_cause_and_passes_only_with_a_ruling( tmp_path ):
    ids, rid = _ten()
    sent, priv = ids[ :9 ], ids[ 9 ]
    calls = [ _call( "a", i, rid[ i ] ) for i in sent ] + [ _call( "a", priv, None, error="EXCLUDED_SENSITIVE_CONTENT" ) ]
    rev   = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in sent ]
    logs, runs = _two_runs( tmp_path, ( ids, rev ), ( [], [] ), calls )
    bad = eg.run_gate( runs, logs )
    assert bad[ "passed" ] is False and bad[ "reasons" ] == [ f"{priv}: EXCLUDED_NO_RULING" ]
    row = [ r for r in bad[ "runs" ][ 0 ][ "rows" ] if r[ "id" ] == priv ][ 0 ]
    assert row == { "id": priv, "status": "EXCLUDED_NO_RULING", "cause": "SENSITIVE_CONTENT" }       # not NO_CALL
    ( tmp_path / "again" ).mkdir()
    again = tmp_path / "again"
    _write_record( again, SID, [ "m.near" ], entry=priv )
    searched = [ f"SEARCHED {priv} :: {SID} :: m.near :: UNRELATED :: it formats" ]
    logs2, runs2 = _two_runs( again, ( ids, rev + [ _ruling( priv, "DISTINCT it reads a mailbox", "excluded" ) + f" :: search: {SID}" ] + searched ), ( [], [] ),
                              calls + [ _search_call( "a", SID, entry=priv ) ] )
    res = eg.run_gate( runs2, logs2 )
    assert res[ "passed" ] is True and res[ "runs" ][ 0 ][ "rows" ][ -1 ][ "status" ] == "EXCLUDED"
    ( tmp_path / "bare" ).mkdir()
    logs3, runs3 = _two_runs( tmp_path / "bare", ( ids, rev + [ _ruling( priv, "DISTINCT it reads a mailbox", "excluded" ) ] ), ( [], [] ), calls )
    assert eg.run_gate( runs3, logs3 )[ "reasons" ] == [ f"{priv}: NO_SEARCH" ]                  # an excluded definition ruled DISTINCT needs its entry-keyed search


def test_an_excluded_ruling_needs_the_excluded_token( tmp_path ):
    """A ruling on a refused definition that cites a real-looking receipt must not pass."""
    ids, rid = _ten()
    sent, priv = ids[ :9 ], ids[ 9 ]
    calls = [ _call( "a", i, rid[ i ] ) for i in sent ] + [ _call( "a", priv, None, error="EXCLUDED_PREFIX" ) ]
    base  = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in sent ]
    logs, runs = _two_runs( tmp_path, ( ids, base + [ _ruling( priv, "DUPLICATE", rid[ sent[ 0 ] ] ) ] ), ( [], [] ), calls )
    res = eg.run_gate( runs, logs )
    row = [ r for r in res[ "runs" ][ 0 ][ "rows" ] if r[ "id" ] == priv ][ 0 ]
    assert res[ "passed" ] is False and row == { "id": priv, "status": "EXCLUDED_BAD_TOKEN", "cause": "PREFIX" }


def test_gate_refuses_a_near_empty_diff_even_when_every_row_is_ok( tmp_path ):
    logs, runs = _two_runs( tmp_path, ( [ "m.only" ], [ _ruling( "m.only", "DUPLICATE", "r1" ) ] ), ( [], [] ), [ _call( "a", "m.only", "r1" ) ] )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is False and "only 2 new definitions, at least 10 required" in res[ "reasons" ]


def test_gate_reports_algorithm_change( tmp_path ):
    logs = tmp_path / "call-log"; logs.mkdir()
    diff = tmp_path / "d.json"; diff.write_text( json.dumps( { "algorithm_changed": { "was": "a", "now": "b" } } ), encoding="utf-8" )
    rev  = tmp_path / "r.md"; rev.write_text( "", encoding="utf-8" )
    run  = { "diff": str( diff ), "review": str( rev ) }
    res  = eg.run_gate( [ run, run ], logs )
    assert res[ "passed" ] is False and any( "pin algorithm changed" in r for r in res[ "reasons" ] )


def test_a_ruling_line_the_pattern_cannot_read_fails_the_gate_and_is_named( tmp_path ):
    ids, rid = _ten()
    bad  = "RULING m.f0, m.f1 :: DISTINCT no twin :: reuse-receipt: none (not in index)"          # comma in the id, free text receipt
    rev  = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids ] + [ bad, "RULINGS in prose are not rulings", "  RULING   " ]
    logs, runs = _two_runs( tmp_path, ( ids, rev ), ( [], [] ), [ _call( "a", i, rid[ i ] ) for i in ids ] )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is False
    assert res[ "reasons" ] == [ f"{runs[ 0 ][ 'review' ]}: unparsed RULING line: {bad}", f"{runs[ 0 ][ 'review' ]}: unparsed RULING line: RULING" ]
    assert eg.unparsed_ruling_lines( "no ruling here\n" + _ruling( "m.a", "DUPLICATE", "r1" ) ) == []   # a good line and prose stay quiet


def test_main_exit_codes_and_output( tmp_path ):
    ids, rid = _ten()
    logs, runs = _two_runs( tmp_path, ( ids, [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids ] ), ( [], [] ), [ _call( "a", i, rid[ i ] ) for i in ids ] )
    args = [ "--log-dir", str( logs ) ] + [ x for r in runs for x in ( "--run", f"{r[ 'diff' ]}:{r[ 'review' ]}" ) ]
    buf = io.StringIO()
    assert eg.main( args, out=buf ) == 0
    assert json.loads( buf.getvalue() )[ "passed" ] is True
    assert eg.main( args + [ "--min-new", "12" ], out=io.StringIO() ) == 1


def test_main_stdout_default_and_malformed_run( tmp_path, capsys ):
    logs = tmp_path / "call-log"; logs.mkdir()
    assert eg.main( [ "--log-dir", str( logs ), "--run", "nocolon" ] ) == 2
    assert "DIFF.json:review.md" in capsys.readouterr().err
    assert eg.main( [ "--log-dir", str( logs ) ] ) == 1
    assert json.loads( capsys.readouterr().out )[ "passed" ] is False


def test_searches_by_symbol_keys_a_search_by_its_entry_or_by_the_symbol_of_its_fetch_similar_receipt( tmp_path ):
    rid, other = "0123456789abcdef", "fedcba9876543210"
    _write_receipt( tmp_path, rid, "fetch_similar", "m.viaReceipt" ); _write_receipt( tmp_path, other, "check_exists", "a need in words" )
    _write_record( tmp_path, SID, [ "m.c1", "m.c2" ], entry="m.byEntry" ); _write_record( tmp_path, SID2, [], receipt_id=rid )
    _write_record( tmp_path, "rs-1111111111", [ "m.c3" ], receipt_id=other )                          # a check_exists receipt names no symbol
    _write_record( tmp_path, "rs-2222222222", [ "m.c4" ], entry="m.second" )
    recs = [ _search_call( "a", s ) for s in ( SID, SID2, "rs-1111111111", "rs-2222222222" ) ] + [ _search_call( "b", "rs-2222222222" ) ]
    assert eg.searches_by_symbol( recs, tmp_path ) == { "m.byEntry": { SID: [ "m.c1", "m.c2" ] }, "m.viaReceipt": { SID2: [] }, "m.second": { "rs-2222222222": [ "m.c4" ] } }


def test_a_call_log_args_field_cut_before_the_entry_does_not_hide_the_search( tmp_path ):
    # red when: the symbol is read from the logged args, which the middleware cuts at 300 characters
    _write_record( tmp_path, SID, [ "m.c1" ], entry="m.hidden" )
    call = _search_call( "a", SID, entry="m.hidden" ); call[ "args" ] = repr( { "extra_terms": [ "word" * 20 ] * 4, "entry": "m.hidden" } )[ :60 ]
    assert "m.hidden" not in call[ "args"]
    assert eg.searches_by_symbol( [ call ], tmp_path ) == { "m.hidden": { SID: [ "m.c1" ] } }


def test_a_logged_search_with_nothing_usable_behind_it_yields_no_search( tmp_path ):
    _write_record( tmp_path, SID, [ "m.c1" ], entry="m.x" )
    ( tmp_path / "search-records" / f"{SID2}.json" ).write_text( "{not json", encoding="utf-8" )
    ( tmp_path / "search-records" / "rs-3333333333.json" ).write_text( "[1, 2]", encoding="utf-8" )
    _write_record( tmp_path, "rs-4444444444", [ "m.c1" ], entry="m.x", id="rs-5555555555" )          # the file does not carry its own name
    _write_record( tmp_path, "rs-6666666666", [], entry="m.x", candidates="not a list" )
    _write_record( tmp_path, "rs-7777777777", [ "m.keep" ], entry="m.partial" ); doc = json.loads( ( tmp_path / "search-records" / "rs-7777777777.json" ).read_text( encoding="utf-8" ) )
    doc[ "candidates" ] += [ "text", { "no_id": 1 } ]; ( tmp_path / "search-records" / "rs-7777777777.json" ).write_text( json.dumps( doc ), encoding="utf-8" )
    _write_receipt( tmp_path, "0123456789abcdef", "fetch_similar", None )                           # a receipt whose query is not text
    _write_receipt( tmp_path, "not-hex", "fetch_similar", "m.escaped" )                              # a readable receipt under an id that is not 16 hex characters
    ( tmp_path / "escape.json" ).write_text( json.dumps( { "tool": "fetch_similar", "query": "m.traversed" } ), encoding="utf-8" )
    ( tmp_path / "receipts" / "0123456789abcdef" ).mkdir()                                           # so that a path through it resolves
    ( tmp_path / "receipts" / "escape.json" ).write_text( json.dumps( { "tool": "fetch_similar", "query": "m.traversed" } ), encoding="utf-8" )
    ( tmp_path / "0123456789abcdef.json" ).write_text( json.dumps( { "tool": "fetch_similar", "query": "m.above" } ), encoding="utf-8" )
    _write_receipt( tmp_path, "0123456789abcdeg", "fetch_similar", "m.nothex" )                      # sixteen characters, one of them not hex
    _write_receipt( tmp_path, "0123456789abcde", "fetch_similar", "m.short" ); _write_receipt( tmp_path, "0123456789abcdef0", "fetch_similar", "m.long" )     # hex, one off the length
    ids16 = ( "0123456789abcdef", "not-hex", "../escape", "0000000000000000", "0123456789abcdef/../escape", "../0123456789abcdef", "0123456789abcdeg", "0123456789abcde", "0123456789abcdef0" )
    for n, rid in enumerate( ids16 ): _write_record( tmp_path, f"rs-{n}000000000", [ "m.c1" ], receipt_id=rid )
    recs = [ _search_call( "a", s ) for s in ( SID2, "rs-3333333333", "rs-4444444444", "rs-6666666666", "rs-8888888888" ) ]
    recs += [ _search_call( "a", SID, error="BAD_SEARCH_KEY" ), _search_call( "a", SID, tool="fetch_similar" ), _search_call( "a", "rs-short" ), _search_call( "a", None ) ]
    recs += [ _search_call( "a", f"rs-{n}000000000" ) for n in range( len( ids16 ) ) ]              # no text, a non-hex id, three traversals, a receipt that is not there, a non-hex letter
    _write_record( tmp_path, "rs-9999999999", [ "m.c1" ] )                                          # a record that names neither an entry nor a receipt
    recs += [ _search_call( "a", "rs-7777777777" ), _search_call( "a", "rs-9999999999" ) ]
    assert eg.searches_by_symbol( recs, tmp_path ) == { "m.partial": { "rs-7777777777": [ "m.keep" ] } }       # a malformed candidate entry is left out, the rest kept


def _row( ruling, searches, searched, receipts=None ):
    """Ensures: returns the status of the symbol `m.a` ruled by ( ruling, receipt, search )."""
    r, rid, search = ruling
    return eg.check_run( [ "m.a" ], receipts if receipts is not None else { "m.a": { "r1" } },
                         { "m.a": [ { "ruling": r, "receipt": rid, "search": search } ] }, None, searches, searched )[ 0 ][ "status" ]


def test_check_run_judges_a_distinct_ruling_on_its_recorded_search():
    distinct = ( "DISTINCT it differs", "r1", SID )
    found    = { "m.a": { SID: [ "m.c1", "m.c2" ] } }
    ruled    = { "m.a": { SID: { "m.c1": { "value": "RELATED", "why": "w" }, "m.c2": { "value": "UNRELATED", "why": "w" } } } }
    assert _row( distinct, found, ruled ) == "OK"
    assert _row( distinct, None, ruled ) == "NO_SEARCH"                                             # None fails closed
    assert _row( distinct, {}, ruled ) == "NO_SEARCH" and _row( distinct, { "m.b": found[ "m.a" ] }, ruled ) == "NO_SEARCH"
    assert _row( ( "DISTINCT it differs", "r1", None ), found, ruled ) == "SEARCH_NOT_CITED"
    assert _row( ( "DISTINCT it differs", "r1", SID2 ), found, ruled ) == "SEARCH_NOT_CITED"        # a search that is not this symbol's
    assert _row( distinct, found, None ) == "CANDIDATES_UNRULED"
    assert _row( distinct, found, { "m.a": { SID: { "m.c1": ruled[ "m.a" ][ SID ][ "m.c1" ] } } } ) == "CANDIDATES_UNRULED"
    assert _row( distinct, found, { "m.a": { SID2: ruled[ "m.a" ][ SID ] } } ) == "CANDIDATES_UNRULED"      # lines for another search do not count
    same = { "m.a": { SID: { "m.c1": { "value": "RELATED", "why": "w" }, "m.c2": { "value": "SAME_JOB", "why": "w" } } } }
    assert _row( distinct, found, same ) == "DISTINCT_CONTRADICTED"
    empty = { "m.a": { SID: [] } }
    assert _row( distinct, empty, None ) == "SEARCH_EMPTY_UNEXPLAINED"
    assert _row( distinct, empty, { "m.a": { SID: { "m.c1": ruled[ "m.a" ][ SID ][ "m.c1" ] } } } ) == "SEARCH_EMPTY_UNEXPLAINED"
    assert _row( distinct, empty, { "m.a": { SID: { "none": { "value": None, "why": "rare terms" } } } } ) == "OK"


def test_a_candidate_named_on_two_lines_stays_same_job_if_either_line_says_so():
    # red when: the last line wins, so a SAME_JOB finding can be undone by a later RELATED line
    for order in ( ( "SAME_JOB", "RELATED" ), ( "RELATED", "SAME_JOB" ) ):
        text   = "\n".join( f"SEARCHED m.a :: {SID} :: m.c1 :: {v} :: line {n}" for n, v in enumerate( order ) )
        parsed = eg.parse_searched( text )
        assert parsed[ "m.a" ][ SID ][ "m.c1" ][ "value" ] == "SAME_JOB", order
        assert _row( ( "DISTINCT it differs", "r1", SID ), { "m.a": { SID: [ "m.c1" ] } }, parsed ) == "DISTINCT_CONTRADICTED", order
    again = eg.parse_searched( f"SEARCHED m.a :: {SID} :: m.c1 :: RELATED :: first\nSEARCHED m.a :: {SID} :: m.c1 :: UNRELATED :: second" )
    assert again[ "m.a" ][ SID ][ "m.c1" ] == { "value": "UNRELATED", "why": "second" }


def test_a_row_with_no_distinct_ruling_ignores_the_searches_and_one_bad_distinct_ruling_fails_the_row():
    for ruling in ( ( "DUPLICATE", "r1", None ), ( "EXTEND m.x", "r1", None ) ):
        assert _row( ruling, None, None ) == "OK" and _row( ruling, {}, {} ) == "OK", ruling
    two = [ { "ruling": "DUPLICATE", "receipt": "r1", "search": None }, { "ruling": "DISTINCT it differs", "receipt": "r1", "search": None } ]
    assert eg.check_run( [ "m.a" ], { "m.a": { "r1" } }, { "m.a": two }, None, { "m.a": { SID: [] } }, {} )[ 0 ][ "status" ] == "SEARCH_NOT_CITED"
    elsewhere = [ { "ruling": "DISTINCT it differs", "receipt": "zz", "search": None } ] + two[ :1 ]
    assert eg.check_run( [ "m.a" ], { "m.a": { "r1" } }, { "m.a": elsewhere }, None, None, None )[ 0 ][ "status" ] == "OK"      # a DISTINCT ruling on a receipt that is not the symbol's is not what passed it


def _distinct_gate( tmp_path, tail=f" :: search: {SID}", searched=(), record=True, call=True, candidates=( "m.c1", ) ):
    """
    Run the gate over ten definitions, the first ruled `DISTINCT`, with the evidence given.

    Ensures:
        - returns the gate result; the data folder is the parent of the call log, the gate's default
    """
    ids, rid = _ten()
    calls  = [ _call( "a", i, rid[ i ] ) for i in ids ] + ( [ _search_call( "a", SID, entry=ids[ 0 ] ) ] if call else [] )
    review = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ 1: ] ] + [ _ruling( ids[ 0 ], "DISTINCT it reads a different format", rid[ ids[ 0 ] ] ) + tail ]
    if record: _write_record( tmp_path, SID, list( candidates ), entry=ids[ 0 ] )
    logs, runs = _two_runs( tmp_path, ( ids, review + [ l.replace( "<sym>", ids[ 0 ] ) for l in searched ] ), ( [], [] ), calls )
    return eg.run_gate( runs, logs )


def test_the_gate_refuses_a_distinct_ruling_with_no_search_record_and_passes_one_that_has_it( tmp_path ):
    rule = [ f"SEARCHED <sym> :: {SID} :: m.c1 :: RELATED :: it only formats" ]
    for n, kwargs in enumerate( ( dict( record=False, call=False, searched=rule ), dict( record=True, call=False, searched=rule ) ) ):    # no log line; a log line is the evidence
        ( tmp_path / f"a{n}" ).mkdir()
        res = _distinct_gate( tmp_path / f"a{n}", **kwargs )
        assert res[ "passed" ] is False and res[ "reasons" ] == [ "m.f0: NO_SEARCH" ], kwargs
    ( tmp_path / "b" ).mkdir()
    assert _distinct_gate( tmp_path / "b", record=False, call=True, searched=rule )[ "reasons" ] == [ "m.f0: NO_SEARCH" ]     # a log line whose record file is missing
    ( tmp_path / "ok" ).mkdir()
    ok = _distinct_gate( tmp_path / "ok", searched=rule )
    assert ok[ "passed" ] is True and ok[ "reasons" ] == []
    ( tmp_path / "other" ).mkdir()
    assert _distinct_gate( tmp_path / "other", searched=[ f"SEARCHED <sym> :: {SID} :: m.c1 :: UNRELATED :: it is a formatter" ] )[ "passed" ] is True


def test_the_gate_names_each_search_failure_of_a_distinct_ruling( tmp_path ):
    cases = { "SEARCH_NOT_CITED": dict( tail="" ), "CANDIDATES_UNRULED": dict(),
              "DISTINCT_CONTRADICTED": dict( searched=[ f"SEARCHED <sym> :: {SID} :: m.c1 :: SAME_JOB :: it does the job" ] ),
              "SEARCH_EMPTY_UNEXPLAINED": dict( candidates=() ) }
    for n, ( status, kwargs ) in enumerate( cases.items() ):
        ( tmp_path / f"c{n}" ).mkdir()
        res = _distinct_gate( tmp_path / f"c{n}", **kwargs )
        assert res[ "passed" ] is False and res[ "reasons" ] == [ f"m.f0: {status}" ], status
    ( tmp_path / "invented" ).mkdir()
    assert _distinct_gate( tmp_path / "invented", tail=" :: search: rs-ffffffffff" )[ "reasons" ] == [ "m.f0: SEARCH_NOT_CITED" ]     # a ruling cannot cite a search that never ran
    ( tmp_path / "empty" ).mkdir()
    assert _distinct_gate( tmp_path / "empty", candidates=(), searched=[ f"SEARCHED <sym> :: {SID} :: none :: the terms were rare" ] )[ "passed" ] is True


def test_an_unparsed_searched_line_fails_the_gate_and_is_named( tmp_path ):
    rule = [ f"SEARCHED <sym> :: {SID} :: m.c1 :: RELATED :: it only formats", f"SEARCHED <sym> :: {SID} :: m.c1 :: MAYBE :: no" ]
    res  = _distinct_gate( tmp_path, searched=rule )
    assert res[ "passed" ] is False and len( res[ "reasons" ] ) == 1 and res[ "reasons" ][ 0 ].endswith( "unparsed SEARCHED line: SEARCHED m.f0 :: " + SID + " :: m.c1 :: MAYBE :: no" )


def test_main_reads_the_data_dir_option_and_the_review_of_the_skill_passes_the_gate( tmp_path ):
    """The review lines are the skill's own example blocks, filled in.

    The fixture cannot be better formed than the skill.
    """
    text    = SKILL.read_text( encoding="utf-8" )
    grab    = lambda lead: re.search( rf"^\s*({lead} .+)$", text, re.M ).group( 1 )
    ids, rid = _ten()
    search_line  = grab( "SEARCHED <symbol id> :: <search id> :: <candidate id>" ).replace( "SAME_JOB | RELATED | UNRELATED", "UNRELATED" )
    none_line    = grab( "SEARCHED <symbol id> :: <search id> :: none" )
    distinct     = grab( "RULING <symbol id> :: DISTINCT <why>" )
    fill = lambda line, sym, sid, rid_: line.replace( "<symbol id>", sym ).replace( "<search id>", sid ).replace( "<candidate id>", "m.near" ).replace( "<why>", "it formats" ).replace( "<receipt id>", rid_ )
    review = [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids[ 2: ] ]
    review += [ fill( distinct, ids[ 0 ], SID, rid[ ids[ 0 ] ] ), fill( search_line, ids[ 0 ], SID, "" ), fill( distinct, ids[ 1 ], SID2, rid[ ids[ 1 ] ] ), fill( none_line, ids[ 1 ], SID2, "" ) ]
    data = tmp_path / "elsewhere"; _write_record( data, SID, [ "m.near" ], entry=ids[ 0 ] ); _write_record( data, SID2, [], entry=ids[ 1 ] )
    calls = [ _call( "a", i, rid[ i ] ) for i in ids ] + [ _search_call( "a", SID, entry=ids[ 0 ] ), _search_call( "a", SID2, entry=ids[ 1 ] ) ]
    logs, runs = _two_runs( tmp_path, ( ids, review ), ( [], [] ), calls )
    args = [ "--log-dir", str( logs ) ] + [ x for r in runs for x in ( "--run", f"{r[ 'diff' ]}:{r[ 'review' ]}" ) ]
    buf = io.StringIO()
    assert eg.main( args + [ "--data-dir", str( data ) ], out=buf ) == 0, buf.getvalue()
    assert json.loads( buf.getvalue() )[ "reasons" ] == []
    assert eg.main( args, out=io.StringIO() ) == 1                                                  # the default data folder is the call log's parent: it holds no search records
