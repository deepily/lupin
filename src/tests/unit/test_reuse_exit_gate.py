"""
Unit tests for the exit gate over fixture call logs and review documents.

Each test writes its own per-session logs, diff and review. A definition passes only with a
`fetch_similar` receipt and a ruling that cites it.
"""
import io
import json
import pathlib

from lupin_mcp import reuse_exit_gate as eg


def _call( session, entry, receipt, tool="fetch_similar", error=None ):
    return { "ts": "2026-10-14T10:00:00+00:00", "tool": tool, "caller": "p " + session, "session": session,
             "receipt_id": receipt, "error": error, "args": repr( { "entry": entry } ) }


def _write_log( d, name, records, extra=() ):
    ( d / f"{name}.jsonl" ).write_text( "\n".join( [ json.dumps( r ) for r in records ] + list( extra ) ) + "\n", encoding="utf-8" )


def _ruling( sid, ruling, rid ):
    return f"RULING {sid} :: {ruling} :: reuse-receipt: {rid}"


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
    assert got[ "m.c" ][ 0 ] == { "ruling": "DISTINCT it parses a different format", "receipt": "ef56" }


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


def test_a_real_run_plus_an_empty_run_does_not_pass( tmp_path ):
    ids, rid = _ten()
    logs, runs = _two_runs( tmp_path, ( ids, [ _ruling( i, "DUPLICATE", rid[ i ] ) for i in ids ] ), ( [], [] ), [ _call( "a", i, rid[ i ] ) for i in ids ], pad=False )
    res = eg.run_gate( runs, logs )
    assert res[ "passed" ] is False and res[ "total_new" ] == 10
    assert res[ "reasons" ] == [ f"{runs[ 1 ][ 'diff' ]}: the run adds no definition" ]


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
    logs2, runs2 = _two_runs( tmp_path / "again", ( ids, rev + [ _ruling( priv, "DISTINCT it reads a mailbox", "excluded" ) ] ), ( [], [] ), calls )
    res = eg.run_gate( runs2, logs2 )
    assert res[ "passed" ] is True and res[ "runs" ][ 0 ][ "rows" ][ -1 ][ "status" ] == "EXCLUDED"


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
