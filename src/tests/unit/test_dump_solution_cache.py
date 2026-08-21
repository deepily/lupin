#!/usr/bin/env python3
"""
Row 1e597a65 — dump_solution_cache.py, the step-13 cache-dump tool (PREP; execution on GO).

What must not silently break:
  · SCOPE is exactly the flags — --db picks the database(s), --synonyms / --adjacent-caches
    pick the tables; nothing else is ever named in the SQL (a dump that quietly widened to
    input_and_output would take 376k rows with it);
  · DRY-RUN is the default — without --apply no pg_dump and no DELETE argv is ever built;
  · the DELETE is one transaction with DELETE (never TRUNCATE) and before/after counts;
  · BACKUP precedes DELETE, and a failing pg_dump stops the run before any DELETE;
  · the two verification halves: --verify-empty flags any non-zero count; learn-back flags
    every 9a/9b failure shape (blank user_id, no routed command, confirmed row, replay on
    the second ask) and passes the clean shape.
Every subprocess and HTTP call is stubbed; the tests are deterministic and red-capable
(each guard has its inverse control).
"""
import datetime
import io
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import dump_solution_cache as dsc


# ── stand-ins ────────────────────────────────────────────────────────────────────

class FakeRunner:
    """Routes argv to canned stdout and records every argv it saw."""

    def __init__( self, counts=( 3, 3 ), after=( 0, 0 ), row="abc|u-1|agent router go to todo|", pg_dump_rc=0, psql_rc=0, committed=None ):
        self.calls      = [ ]
        self.counts     = counts
        self.after      = after
        self.row        = row
        self.pg_dump_rc = pg_dump_rc
        self.psql_rc    = psql_rc
        # `committed` is what an INDEPENDENT count (a fresh psql call AFTER the delete
        # transaction returned) reports. None → same as `after`. Set it differently to
        # model a transaction whose own 'after' row said 0 but whose COMMIT did not land.
        self.committed  = committed
        self.deleted    = False

    def __call__( self, argv, capture_output=True, text=True ):
        self.calls.append( argv )
        proc = types.SimpleNamespace( returncode=0, stdout="", stderr="" )
        if "pg_dump" in argv:
            proc.returncode = self.pg_dump_rc
            proc.stdout     = "-- pg_dump output\n"
            proc.stderr     = "pg_dump: boom" if self.pg_dump_rc else ""
            return proc
        sql = argv[ -1 ]
        proc.returncode = self.psql_rc
        if self.psql_rc:
            proc.stderr = "psql: boom"
            return proc
        if sql.startswith( "BEGIN;" ):
            self.deleted = True
            proc.stdout = "before|" + "|".join( str( c ) for c in self.counts ) + "\n" + "after|" + "|".join( str( c ) for c in self.after ) + "\n"
        elif sql.startswith( "SELECT id_hash" ):
            proc.stdout = ( self.row + "\n" ) if self.row is not None else ""
        else:
            now = ( self.committed if self.committed is not None else self.after ) if self.deleted else self.counts
            proc.stdout = "|".join( str( c ) for c in now ) + "\n"
        return proc

    def sql_seen( self ):
        return [ a[ -1 ] for a in self.calls if "psql" in a ]


class FakeResp:
    def __init__( self, status_code, body ):
        self.status_code = status_code
        self._body       = body
        self.text        = json.dumps( body )

    def json( self ):
        return self._body


class FakeHttp:
    """Answers /auth/login then /api/v2/ask in sequence from a queue of AskResponse dicts."""

    def __init__( self, asks, login_status=200 ):
        self.asks         = list( asks )
        self.login_status = login_status
        self.posts        = [ ]

    def post( self, url, json=None, headers=None, timeout=None ):
        self.posts.append( ( url, json, headers ) )
        if url.endswith( "/auth/login" ):
            return FakeResp( self.login_status, { "tokens": { "access_token": "tok" } } )
        return FakeResp( 200, self.asks.pop( 0 ) )


def _ask( **over ):
    base = { "path": "agent", "status": "done", "answer": "It is noon.", "wrote_snapshot": True,
             "snapshot_id": "abc", "cache_hit": False, "trace_id": "t1" }
    base.update( over )
    return base


def _run_main( argv, runner=None, http=None, env=None ):
    runner = runner or FakeRunner()
    lines  = [ ]
    saved  = { k: os.environ.get( k ) for k in ( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ) }
    for k in saved: os.environ.pop( k, None )
    for k, v in ( env or { } ).items(): os.environ[ k ] = v
    try:
        rc = dsc.main( argv, runner=runner, http=http, now=datetime.datetime( 2026, 8, 21, 18, 30, 0 ), out=lines.append )
    finally:
        for k, v in saved.items():
            if v is None: os.environ.pop( k, None )
            else:         os.environ[ k ] = v
    return rc, lines, runner


# ── bootstrap ────────────────────────────────────────────────────────────────────

class TestBootstrap( unittest.TestCase ):

    def test_bootstrap_guard_fires_without_lupin_root( self ):
        """The import-time guard is unreachable in-process (this test needs LUPIN_ROOT to import cosa), so prove it in a child."""
        import subprocess
        env = { k: v for k, v in os.environ.items() if k != "LUPIN_ROOT" }
        proc = subprocess.run( [ sys.executable, "-c", "import dump_solution_cache" ],
                               cwd=cu.get_project_root() + "/src/scripts", env=env, capture_output=True, text=True )
        self.assertNotEqual( proc.returncode, 0 )
        self.assertIn( "LUPIN_ROOT not set", proc.stderr )


# ── scope resolution ─────────────────────────────────────────────────────────────

class TestScope( unittest.TestCase ):

    def test_databases_for_each_target( self ):
        self.assertEqual( dsc.databases_for( "dev" ),  [ "lupin_db_dev" ] )
        self.assertEqual( dsc.databases_for( "test" ), [ "lupin_db_test" ] )
        self.assertEqual( dsc.databases_for( "both" ), [ "lupin_db_dev", "lupin_db_test" ] )

    def test_databases_for_rejects_unknown_target( self ):
        with self.assertRaises( ValueError ):
            dsc.databases_for( "prod" )

    def test_tables_for_all_four_flag_combinations( self ):
        self.assertEqual( dsc.tables_for( False, False ), [ "solution_snapshots" ] )
        self.assertEqual( dsc.tables_for( True,  False ), [ "solution_snapshots", "canonical_synonyms" ] )
        self.assertEqual( dsc.tables_for( False, True  ), [ "solution_snapshots" ] + dsc.ADJACENT_TABLES )
        self.assertEqual( dsc.tables_for( True,  True  ), [ "solution_snapshots", "canonical_synonyms" ] + dsc.ADJACENT_TABLES )

    def test_adjacent_list_is_exactly_the_five_ruled_out( self ):
        self.assertEqual( dsc.ADJACENT_TABLES, [ "gist_cache", "question_embeddings", "embedding_cache", "query_log", "input_and_output" ] )


# ── argv + SQL builders ──────────────────────────────────────────────────────────

class TestBuilders( unittest.TestCase ):

    def test_psql_argv_is_docker_exec_unaligned_tuples( self ):
        argv = dsc.psql_argv( "lupin_db_dev", "SELECT 1;" )
        self.assertEqual( argv[ :3 ], [ "docker", "exec", "lupin-postgres" ] )
        self.assertIn( "-At", argv )
        self.assertEqual( argv[ argv.index( "-d" ) + 1 ], "lupin_db_dev" )
        self.assertEqual( argv[ -1 ], "SELECT 1;" )

    def test_pg_dump_argv_names_each_table_once_in_order( self ):
        argv = dsc.pg_dump_argv( "lupin_db_test", [ "a", "b" ] )
        self.assertEqual( argv[ -4: ], [ "-t", "a", "-t", "b" ] )
        self.assertEqual( argv[ argv.index( "-d" ) + 1 ], "lupin_db_test" )

    def test_count_sql_one_subselect_per_table( self ):
        self.assertEqual( dsc.count_sql( [ "a", "b" ] ), "SELECT (SELECT count(*) FROM a), (SELECT count(*) FROM b);" )

    def test_delete_sql_is_one_transaction_with_delete_not_truncate( self ):
        sql = dsc.delete_sql( [ "solution_snapshots", "canonical_synonyms" ] )
        self.assertTrue( sql.startswith( "BEGIN;" ) )
        self.assertTrue( sql.endswith( "COMMIT;" ) )
        self.assertIn( "DELETE FROM solution_snapshots;", sql )
        self.assertIn( "DELETE FROM canonical_synonyms;", sql )
        self.assertNotIn( "TRUNCATE", sql )
        self.assertIn( "SELECT 'before'", sql )
        self.assertIn( "SELECT 'after'", sql )

    def test_delete_sql_names_only_the_given_tables( self ):
        sql = dsc.delete_sql( [ "solution_snapshots" ] )
        for t in [ "canonical_synonyms" ] + dsc.ADJACENT_TABLES:
            self.assertNotIn( t, sql )


# ── runner + parsing ─────────────────────────────────────────────────────────────

class TestRunAndParse( unittest.TestCase ):

    def test_run_argv_returns_stdout( self ):
        r = FakeRunner( counts=( 7, 8 ) )
        self.assertEqual( dsc.run_argv( dsc.psql_argv( "db", dsc.count_sql( [ "a", "b" ] ) ), runner=r ), "7|8\n" )

    def test_run_argv_raises_on_nonzero_with_stderr( self ):
        r = FakeRunner( psql_rc=1 )
        with self.assertRaises( RuntimeError ) as cm:
            dsc.run_argv( dsc.psql_argv( "db", "SELECT 1;" ), runner=r )
        self.assertIn( "psql: boom", str( cm.exception ) )

    def test_parse_count_row_with_and_without_label( self ):
        self.assertEqual( dsc.parse_count_row( "3|65", [ "a", "b" ] ),        { "a": 3, "b": 65 } )
        self.assertEqual( dsc.parse_count_row( "before|3|65", [ "a", "b" ] ), { "a": 3, "b": 65 } )

    def test_parse_count_row_short_or_non_int_raises( self ):
        with self.assertRaises( ValueError ): dsc.parse_count_row( "3", [ "a", "b" ] )
        with self.assertRaises( ValueError ): dsc.parse_count_row( "x|y", [ "a", "b" ] )

    def test_count_rows_maps_tables_in_order( self ):
        r = FakeRunner( counts=( 3, 65 ) )
        self.assertEqual( dsc.count_rows( "lupin_db_test", [ "solution_snapshots", "canonical_synonyms" ], runner=r ),
                          { "solution_snapshots": 3, "canonical_synonyms": 65 } )


# ── backup + dump ────────────────────────────────────────────────────────────────

class TestBackupAndDump( unittest.TestCase ):

    def test_backup_writes_timestamped_file_with_pg_dump_output( self ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            r    = FakeRunner()
            path = dsc.backup( "lupin_db_dev", [ "solution_snapshots" ], os.path.join( d, "sub" ), datetime.datetime( 2026, 8, 21, 18, 30, 0 ), runner=r )
            self.assertTrue( path.endswith( "cache-backup-lupin_db_dev-2026.08.21-at-183000.sql" ) )
            with open( path ) as f: self.assertEqual( f.read(), "-- pg_dump output\n" )
            self.assertTrue( any( "pg_dump" in a for a in r.calls ) )

    def test_backup_failure_writes_nothing( self ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            r = FakeRunner( pg_dump_rc=1 )
            with self.assertRaises( RuntimeError ):
                dsc.backup( "lupin_db_dev", [ "solution_snapshots" ], d, datetime.datetime( 2026, 8, 21 ), runner=r )
            self.assertEqual( os.listdir( d ), [ ] )

    def test_dump_returns_before_and_after_from_the_transaction( self ):
        r = FakeRunner( counts=( 3, 3 ), after=( 0, 0 ) )
        before, after = dsc.dump( "lupin_db_dev", [ "solution_snapshots", "canonical_synonyms" ], runner=r )
        self.assertEqual( before, { "solution_snapshots": 3, "canonical_synonyms": 3 } )
        self.assertEqual( after,  { "solution_snapshots": 0, "canonical_synonyms": 0 } )
        self.assertTrue( r.sql_seen()[ 0 ].startswith( "BEGIN;" ) )

    def test_dump_without_both_rows_raises( self ):
        class Half( FakeRunner ):
            def __call__( self, argv, capture_output=True, text=True ):
                return types.SimpleNamespace( returncode=0, stdout="before|3|3\n", stderr="" )
        with self.assertRaises( ValueError ):
            dsc.dump( "lupin_db_dev", [ "a", "b" ], runner=Half() )

    def test_verify_empty_lists_leftovers( self ):
        self.assertEqual( dsc.verify_empty( { "a": 0, "b": 0 } ), [ ] )
        self.assertEqual( dsc.verify_empty( { "a": 0, "b": 2 } ), [ "b" ] )


# ── learn-back ───────────────────────────────────────────────────────────────────

class TestLearnBack( unittest.TestCase ):

    def test_latest_snapshot_row_found_and_missing( self ):
        r = FakeRunner( row="abc|u-1|agent router go to todo|" )
        self.assertEqual( dsc.latest_snapshot_row( "db", "abc", runner=r ),
                          { "id_hash": "abc", "user_id": "u-1", "routing_command": "agent router go to todo", "answer_is_correct": "" } )
        with self.assertRaises( ValueError ):
            dsc.latest_snapshot_row( "db", "abc", runner=FakeRunner( row=None ) )

    def test_login_and_ask_v2_success( self ):
        h = FakeHttp( [ _ask() ] )
        self.assertEqual( dsc.login( "http://s", "e", "p", h ), "tok" )
        body = dsc.ask_v2( "http://s", "tok", "q", h )
        self.assertEqual( body[ "path" ], "agent" )
        self.assertEqual( h.posts[ 1 ][ 2 ], { "Authorization": "Bearer tok" } )

    def test_login_and_ask_v2_non_200_raise( self ):
        with self.assertRaises( RuntimeError ):
            dsc.login( "http://s", "e", "p", FakeHttp( [ ], login_status=401 ) )
        class Bad:
            def post( self, url, json=None, headers=None, timeout=None ): return FakeResp( 500, { "detail": "x" } )
        with self.assertRaises( RuntimeError ):
            dsc.ask_v2( "http://s", "tok", "q", Bad() )

    def test_clean_shape_passes( self ):
        h = FakeHttp( [ _ask(), _ask( wrote_snapshot=False, snapshot_id=None ) ] )
        lb = dsc.verify_learn_back( "db", "http://s", "e", "p", "q", h, runner=FakeRunner() )
        self.assertEqual( lb[ "failures" ], [ ] )
        self.assertEqual( lb[ "fresh_row" ][ "user_id" ], "u-1" )
        self.assertEqual( lb[ "second_ask" ][ "cache_hit" ], False )

    def test_each_first_ask_failure_is_named( self ):
        cases = {
            "first ask did not write a snapshot"         : _ask( wrote_snapshot=False ),
            "first ask returned no answer"                : _ask( answer=None ),
            "first ask replayed — cache was not empty"   : _ask( path="replay" ),
            "first ask returned no snapshot_id"           : _ask( snapshot_id=None ),
        }
        for expected, first in cases.items():
            lb = dsc.verify_learn_back( "db", "http://s", "e", "p", "q", FakeHttp( [ first, _ask() ] ), runner=FakeRunner() )
            self.assertIn( expected, lb[ "failures" ], expected )

    def test_each_9a_row_failure_is_named( self ):
        cases = {
            "fresh row has blank user_id (fails 9a)"                      : "abc||agent router go to todo|",
            "fresh row has no routing_command (fails 9a)"                 : "abc|u-1||",
            "fresh row already confirmed True — guard would serve it"     : "abc|u-1|cmd|True",
        }
        for expected, row in cases.items():
            lb = dsc.verify_learn_back( "db", "http://s", "e", "p", "q", FakeHttp( [ _ask(), _ask() ] ), runner=FakeRunner( row=row ) )
            self.assertIn( expected, lb[ "failures" ], expected )

    def test_second_ask_replay_fails_9b_on_either_signal( self ):
        for second in ( _ask( cache_hit=True ), _ask( path="replay" ) ):
            lb = dsc.verify_learn_back( "db", "http://s", "e", "p", "q", FakeHttp( [ _ask(), second ] ), runner=FakeRunner() )
            self.assertIn( "second ask replayed an unconfirmed row (fails 9b)", lb[ "failures" ] )


# ── main ─────────────────────────────────────────────────────────────────────────

class TestMain( unittest.TestCase ):

    def test_dry_run_both_counts_only_no_pg_dump_no_delete( self ):
        rc, lines, r = _run_main( [ "--db", "both" ] )
        self.assertEqual( rc, 0 )
        self.assertFalse( any( "pg_dump" in a for a in r.calls ) )
        self.assertFalse( any( s.startswith( "BEGIN;" ) for s in r.sql_seen() ) )
        self.assertEqual( len( r.sql_seen() ), 2 )
        self.assertIn( "[DRY-RUN]", lines[ 0 ] )
        receipts = json.loads( lines[ -1 ] )
        self.assertEqual( sorted( receipts[ "databases" ] ), [ "lupin_db_dev", "lupin_db_test" ] )
        self.assertEqual( receipts[ "tables" ], [ "solution_snapshots", "canonical_synonyms" ] )

    def test_flags_narrow_and_widen_scope( self ):
        _, lines, r = _run_main( [ "--db", "dev", "--no-synonyms" ] )
        self.assertEqual( json.loads( lines[ -1 ] )[ "tables" ], [ "solution_snapshots" ] )
        _, lines, r = _run_main( [ "--db", "dev", "--adjacent-caches" ], runner=FakeRunner( counts=( 1, ) * 7 ) )
        self.assertEqual( json.loads( lines[ -1 ] )[ "tables" ], [ "solution_snapshots", "canonical_synonyms" ] + dsc.ADJACENT_TABLES )

    def test_apply_backs_up_before_deleting_and_verifies_empty( self ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rc, lines, r = _run_main( [ "--db", "test", "--apply", "--verify-empty", "--backup-dir", d ] )
            self.assertEqual( rc, 0 )
            kinds = [ "pg_dump" if "pg_dump" in a else ( "delete" if a[ -1 ].startswith( "BEGIN;" ) else "count" ) for a in r.calls ]
            self.assertEqual( kinds, [ "count", "pg_dump", "delete", "count" ] )   # backup BEFORE delete; a fresh count AFTER
            entry = json.loads( lines[ -1 ] )[ "databases" ][ "lupin_db_test" ]
            self.assertEqual( entry[ "verify_empty" ], "pass" )
            self.assertTrue( entry[ "backup" ].startswith( d ) )
            self.assertEqual( entry[ "after" ], { "solution_snapshots": 0, "canonical_synonyms": 0 } )

    def test_apply_verify_empty_fails_on_leftover( self ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rc, lines, _ = _run_main( [ "--db", "dev", "--apply", "--verify-empty", "--backup-dir", d ], runner=FakeRunner( after=( 0, 1 ) ) )
            self.assertEqual( rc, 2 )
            self.assertIn( "FAIL: not empty ['canonical_synonyms']", json.loads( lines[ -1 ] )[ "databases" ][ "lupin_db_dev" ][ "verify_empty" ] )

    def test_verify_empty_reads_an_independent_count_after_the_transaction_returns( self ):
        """Pocholo's finding 2: the transaction's own 'after' row is PRE-commit. The check must
        come from a fresh psql call made after the delete call returned, and must fail when
        that read disagrees with the transaction's row."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            r = FakeRunner( after=( 0, 0 ), committed=( 0, 3 ) )   # tx said empty; the independent read says 3 synonyms remain
            rc, lines, _ = _run_main( [ "--db", "dev", "--apply", "--verify-empty", "--backup-dir", d ], runner=r )
            self.assertEqual( rc, 2 )
            entry = json.loads( lines[ -1 ] )[ "databases" ][ "lupin_db_dev" ]
            self.assertIn( "FAIL", entry[ "verify_empty" ] )
            self.assertEqual( entry[ "after" ], { "solution_snapshots": 0, "canonical_synonyms": 3 } )   # the independent read
            self.assertEqual( entry[ "tx_after" ], { "solution_snapshots": 0, "canonical_synonyms": 0 } ) # the tx row, kept but not trusted
            kinds = [ "pg_dump" if "pg_dump" in a else ( "delete" if a[ -1 ].startswith( "BEGIN;" ) else "count" ) for a in r.calls ]
            self.assertEqual( kinds, [ "count", "pg_dump", "delete", "count" ] )   # a count AFTER the delete call

    def test_dry_run_with_learn_back_sends_nothing( self ):
        """Pocholo's finding 1: dry-run must touch nothing live — no login, no /api/v2/ask
        (which writes a snapshot). Without --apply the learn-back is described, not run."""
        env  = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" }
        stub = FakeHttp( [ _ask(), _ask() ] )
        rc, lines, r = _run_main( [ "--db", "dev", "--verify-learn-back" ], http=stub, env=env )
        self.assertEqual( rc, 0 )
        self.assertEqual( stub.posts, [ ] )
        self.assertFalse( any( "pg_dump" in a for a in r.calls ) )
        self.assertFalse( any( s.startswith( "BEGIN;" ) for s in r.sql_seen() ) )
        entry = json.loads( lines[ -1 ] )[ "databases" ][ "lupin_db_dev" ]
        self.assertEqual( entry[ "learn_back" ], "skipped: dry-run" )
        self.assertTrue( any( "would" in l and "/api/v2/ask" in l for l in lines ) )

    def test_apply_without_verify_empty_skips_the_check( self ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rc, lines, _ = _run_main( [ "--db", "dev", "--apply", "--backup-dir", d ], runner=FakeRunner( after=( 0, 1 ) ) )
            self.assertEqual( rc, 0 )
            self.assertNotIn( "verify_empty", json.loads( lines[ -1 ] )[ "databases" ][ "lupin_db_dev" ] )

    def test_learn_back_refuses_both_databases( self ):
        with self.assertRaises( SystemExit ):
            _run_main( [ "--db", "both", "--verify-learn-back" ] )

    def test_learn_back_needs_credentials( self ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises( SystemExit ):
                _run_main( [ "--db", "dev", "--apply", "--backup-dir", d, "--verify-learn-back" ], http=FakeHttp( [ ] ) )

    def test_learn_back_pass_and_fail_drive_the_exit_code( self ):
        import tempfile
        env = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" }
        with tempfile.TemporaryDirectory() as d:
            rc, lines, _ = _run_main( [ "--db", "dev", "--apply", "--backup-dir", d, "--verify-learn-back" ], http=FakeHttp( [ _ask(), _ask() ] ), env=env )
            self.assertEqual( rc, 0 )
            self.assertEqual( json.loads( lines[ -1 ] )[ "databases" ][ "lupin_db_dev" ][ "learn_back" ][ "failures" ], [ ] )
            rc, lines, _ = _run_main( [ "--db", "dev", "--apply", "--backup-dir", d, "--verify-learn-back" ], http=FakeHttp( [ _ask(), _ask( cache_hit=True ) ] ), env=env )
            self.assertEqual( rc, 2 )
            self.assertTrue( any( "learn-back FAIL" in l for l in lines ) )

    def test_learn_back_imports_requests_when_no_http_given( self ):
        import tempfile
        env   = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" }
        stub  = FakeHttp( [ _ask(), _ask() ] )
        saved = sys.modules.get( "requests" )
        sys.modules[ "requests" ] = stub
        try:
            with tempfile.TemporaryDirectory() as d:
                rc, _, _ = _run_main( [ "--db", "dev", "--apply", "--backup-dir", d, "--verify-learn-back" ], http=None, env=env )
        finally:
            if saved is None: sys.modules.pop( "requests", None )
            else:             sys.modules[ "requests" ] = saved
        self.assertEqual( rc, 0 )
        self.assertEqual( len( stub.posts ), 3 )


if __name__ == "__main__":
    unittest.main()
