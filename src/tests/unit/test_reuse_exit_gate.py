"""
Unit tests for the exit gate over fixture call logs and review documents.

Each test writes its own per-session logs, diff and review. A definition passes only with a
`fetch_similar` receipt and a ruling that cites it.
"""
import io
import json

from lupin_mcp import reuse_exit_gate as eg


def _call( session, entry, receipt, tool="fetch_similar", error=None ):
    return { "ts": "2026-10-14T10:00:00+00:00", "tool": tool, "caller": "p " + session, "session": session,
             "receipt_id": receipt, "error": error, "args": repr( { "entry": entry } ) }


def _write_log( d, name, records, extra=() ):
    ( d / f"{name}.jsonl" ).write_text( "\n".join( [ json.dumps( r ) for r in records ] + list( extra ) ) + "\n", encoding="utf-8" )


def _ruling( sid, ruling, rid ):
    return f"RULING {sid} :: {ruling} :: reuse-receipt: {rid}"


def _fixture( tmp_path, ids, calls_a, calls_b, review_lines ):
    logs = tmp_path / "call-log"; logs.mkdir()
    _write_log( logs, "sess-a", calls_a ); _write_log( logs, "sess-b", calls_b )
    diff = tmp_path / "diff.json"; diff.write_text( json.dumps( { "added": ids, "removed": [], "changed": [] } ), encoding="utf-8" )
    rev = tmp_path / "review.md"; rev.write_text( "\n".join( review_lines ) + "\n", encoding="utf-8" )
    return logs, diff, rev


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


def test_gate_passes_when_every_definition_has_call_and_ruling( tmp_path ):
    ids   = [ f"m.f{i}" for i in range( 10 ) ]
    calls = [ _call( "a", i, f"r{n}" ) for n, i in enumerate( ids[ :5 ] ) ], [ _call( "b", i, f"r{n + 5}" ) for n, i in enumerate( ids[ 5: ] ) ]
    rev   = [ _ruling( i, "DUPLICATE", f"r{n}" ) for n, i in enumerate( ids ) ]
    logs, diff, rv = _fixture( tmp_path, ids, calls[ 0 ], calls[ 1 ], rev )
    res = eg.run_gate( [ { "diff": str( diff ), "review": str( rv ) } ], logs )
    assert res[ "passed"  ] is True and res[ "total_new" ] == 10 and res[ "reasons" ] == []


def test_gate_fails_on_a_call_without_ruling_and_a_ruling_without_call( tmp_path ):
    ids   = [ f"m.f{i}" for i in range( 10 ) ]
    calls = [ _call( "a", i, f"r{n}" ) for n, i in enumerate( ids[ :9 ] ) ]                     # m.f9 never fetched
    rev   = [ _ruling( i, "DUPLICATE", f"r{n}" ) for n, i in enumerate( ids[ 1: ], 1 ) ]       # m.f0 never ruled
    logs, diff, rv = _fixture( tmp_path, ids, calls, [], rev )
    res = eg.run_gate( [ { "diff": str( diff ), "review": str( rv ) } ], logs )
    assert res[ "passed" ] is False
    assert sorted( res[ "reasons" ] ) == [ "m.f0: NO_RULING", "m.f9: NO_CALL" ]


def test_gate_refuses_a_near_empty_diff_even_when_every_row_is_ok( tmp_path ):
    logs, diff, rv = _fixture( tmp_path, [ "m.only" ], [ _call( "a", "m.only", "r1" ) ], [], [ _ruling( "m.only", "DUPLICATE", "r1" ) ] )
    res = eg.run_gate( [ { "diff": str( diff ), "review": str( rv ) } ], logs )
    assert res[ "passed" ] is False and "only 1 new definitions, at least 10 required" in res[ "reasons" ]


def test_gate_with_no_runs_fails( tmp_path ):
    ( tmp_path / "call-log" ).mkdir()
    res = eg.run_gate( [], tmp_path / "call-log" )
    assert res[ "passed" ] is False and "no runs given" in res[ "reasons" ]


def test_gate_reports_algorithm_change( tmp_path ):
    logs = tmp_path / "call-log"; logs.mkdir()
    diff = tmp_path / "d.json"; diff.write_text( json.dumps( { "algorithm_changed": { "was": "a", "now": "b" } } ), encoding="utf-8" )
    rev  = tmp_path / "r.md"; rev.write_text( "", encoding="utf-8" )
    res  = eg.run_gate( [ { "diff": str( diff ), "review": str( rev ) } ], logs )
    assert res[ "passed" ] is False and any( "pin algorithm changed" in r for r in res[ "reasons" ] )


def test_main_exit_codes_and_output( tmp_path ):
    ids   = [ f"m.f{i}" for i in range( 10 ) ]
    logs, diff, rv = _fixture( tmp_path, ids, [ _call( "a", i, f"r{n}" ) for n, i in enumerate( ids ) ], [],
                               [ _ruling( i, "DUPLICATE", f"r{n}" ) for n, i in enumerate( ids ) ] )
    buf = io.StringIO()
    assert eg.main( [ "--log-dir", str( logs ), "--run", f"{diff}:{rv}" ], out=buf ) == 0
    assert json.loads( buf.getvalue() )[ "passed" ] is True
    assert eg.main( [ "--log-dir", str( logs ), "--run", f"{diff}:{rv}", "--min-new", "11" ], out=io.StringIO() ) == 1


def test_main_stdout_default_and_malformed_run( tmp_path, capsys ):
    logs = tmp_path / "call-log"; logs.mkdir()
    assert eg.main( [ "--log-dir", str( logs ), "--run", "nocolon" ] ) == 2
    assert "DIFF.json:review.md" in capsys.readouterr().err
    assert eg.main( [ "--log-dir", str( logs ) ] ) == 1
    assert json.loads( capsys.readouterr().out )[ "passed" ] is False
