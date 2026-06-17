"""
Unit tests for the Spine cutover migration drain (task_store_drain).

:7999-eligible: no network, no DB — every store call (client.query_by_correlation_key
/ client.create_task), every replay, and every generation read is injected as a
fake. 100% lines/branches/functions on the drain module.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.16-store-canonical-task-mgmt-cascade-review.md §Q(d).
"""

import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import task_store_drain as drain


SETTINGS = { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 }


def _session( **overrides ):
    base = {
        "session_id"      : "sid12345",
        "transcript_path" : "/t.jsonl",
        "persona_lower"   : "krishna",
        "project"         : "lupin",
    }
    base.update( overrides )
    return base


def _hit( *statuses ):
    """A query result carrying one item per status (correlation_key probe hit)."""
    return ( True, 200, { "tasks": [ { "status": s } for s in statuses ], "count": len( statuses ) } )


def _miss():
    """A clean probe with no matching item."""
    return ( True, 200, { "tasks": [ ], "count": 0 } )


def _fail():
    """A transport/non-2xx probe failure."""
    return ( False, None, { "error": "refused" } )


# ---------------------------------------------------------------------------
# _read_bridge
# ---------------------------------------------------------------------------

class TestReadBridge:

    def test_reads_dict( self, tmp_path ):
        p = tmp_path / "cc-x.json"
        p.write_text( '{"transcript_path": "/t.jsonl", "cwd": "/repo"}' )
        assert drain._read_bridge( p ) == { "transcript_path": "/t.jsonl", "cwd": "/repo" }

    def test_missing_file_is_none( self, tmp_path ):
        assert drain._read_bridge( tmp_path / "nope.json" ) is None

    def test_bad_json_is_none( self, tmp_path ):
        p = tmp_path / "cc-x.json"
        p.write_text( "{ not json" )
        assert drain._read_bridge( p ) is None

    def test_non_dict_json_is_none( self, tmp_path ):
        p = tmp_path / "cc-x.json"
        p.write_text( "[1, 2, 3]" )
        assert drain._read_bridge( p ) is None


# ---------------------------------------------------------------------------
# _project_from_cwd
# ---------------------------------------------------------------------------

class TestProjectFromCwd:

    def test_git_ancestor_basename( self, tmp_path ):
        repo = tmp_path / "lupin"
        ( repo / ".git" ).mkdir( parents=True )
        sub = repo / "src" / "deep"
        sub.mkdir( parents=True )
        assert drain._project_from_cwd( str( sub ) ) == "lupin"

    def test_alias_applied_on_git_ancestor( self, tmp_path ):
        repo = tmp_path / "planning-is-prompting"     # an alias key -> "plan"
        ( repo / ".git" ).mkdir( parents=True )
        assert drain._project_from_cwd( str( repo ) ) == "plan"

    def test_no_git_falls_back_to_basename( self, tmp_path ):
        sub = tmp_path / "OrphanRepo"                  # no .git anywhere up the tmp tree
        sub.mkdir()
        assert drain._project_from_cwd( str( sub ) ) == "orphanrepo"

    def test_no_cwd_uses_lupin_root( self ):
        assert drain._project_from_cwd( None, environ={ "LUPIN_ROOT": "/opt/Lupin" } ) == "lupin"

    def test_no_cwd_no_root_uses_live_cwd( self, monkeypatch, tmp_path ):
        monkeypatch.chdir( tmp_path )
        assert drain._project_from_cwd( "", environ={ } ) == tmp_path.name.lower()

    def test_environ_none_uses_os_environ( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/srv/MyProj" )
        assert drain._project_from_cwd( None ) == "myproj"


# ---------------------------------------------------------------------------
# discover_active_sessions
# ---------------------------------------------------------------------------

class TestDiscover:

    def test_happy_builds_session_dicts( self ):
        find = lambda _t: [ ( "/b/cc-1.json", "sid1", { "name": "Krishna" } ) ]
        read = lambda _p: { "transcript_path": "/t1.jsonl", "cwd": None }
        out  = drain.discover_active_sessions( _find=find, _read_bridge=read, environ={ "LUPIN_ROOT": "/x/lupin" } )
        assert out == [ {
            "session_id"      : "sid1",
            "transcript_path" : "/t1.jsonl",
            "persona_lower"   : "krishna",
            "project"         : "lupin",
        } ]

    def test_unreadable_bridge_skipped( self ):
        find = lambda _t: [ ( "/b/cc-1.json", "sid1", { "name": "Krishna" } ) ]
        read = lambda _p: None
        assert drain.discover_active_sessions( _find=find, _read_bridge=read ) == [ ]

    def test_no_transcript_path_skipped( self ):
        find = lambda _t: [ ( "/b/cc-1.json", "sid1", { "name": "Krishna" } ) ]
        read = lambda _p: { "cwd": "/x" }                 # no transcript_path
        assert drain.discover_active_sessions( _find=find, _read_bridge=read ) == [ ]

    def test_non_dict_persona_is_unknown( self ):
        find = lambda _t: [ ( "/b/cc-1.json", "sid1", "not-a-dict" ) ]
        read = lambda _p: { "transcript_path": "/t.jsonl", "cwd": None }
        out  = drain.discover_active_sessions( _find=find, _read_bridge=read, environ={ "LUPIN_ROOT": "/x/lupin" } )
        assert out[ 0 ][ "persona_lower" ] == "unknown"

    def test_malformed_cwd_skipped( self ):
        # an embedded null byte makes _project_from_cwd raise — the loop is the
        # never-raises boundary, so the session is skipped (not propagated).
        find = lambda _t: [ ( "/b/cc-1.json", "sid1", { "name": "Krishna" } ) ]
        read = lambda _p: { "transcript_path": "/t.jsonl", "cwd": "\x00bad" }
        assert drain.discover_active_sessions( _find=find, _read_bridge=read ) == [ ]

    def test_threshold_passed_to_find( self ):
        seen = { }
        def find( t ):
            seen[ "t" ] = t
            return [ ]
        drain.discover_active_sessions( stale_threshold_seconds=99, _find=find )
        assert seen[ "t" ] == 99


# ---------------------------------------------------------------------------
# _owed_harness_ids
# ---------------------------------------------------------------------------

class TestOwedHarnessIds:

    def test_filters_to_owed_statuses( self ):
        state = { "1": "completed", "2": "in_progress", "3": "pending", "4": "deleted" }
        assert drain._owed_harness_ids( "/t", lambda _p: state ) == [ "2", "3" ]

    def test_empty_state( self ):
        assert drain._owed_harness_ids( "/t", lambda _p: { } ) == [ ]


# ---------------------------------------------------------------------------
# drain_owed_items_for_session
# ---------------------------------------------------------------------------

class TestDrainSession:

    def _run( self, *, state, subjects=None, query_results, apply=True, create_ok=True ):
        calls = { "created_payloads": [ ] }
        q_iter = iter( query_results )
        def _query( settings, api_key, ck ):
            return next( q_iter )
        def _create( settings, api_key, payload ):
            calls[ "created_payloads" ].append( payload )
            return ( create_ok, 201, { } ) if create_ok else ( False, 500, { "error": "boom" } )
        result = drain.drain_owed_items_for_session(
            SETTINGS, "key", _session(), apply=apply,
            _replay             = lambda _p: state,
            _subjects           = lambda _p: subjects or { },
            _current_generation = lambda _sid, _bd: 0,
            _query              = _query,
            _create             = _create,
        )
        return result, calls

    def test_apply_creates_missing_owed( self ):
        res, calls = self._run(
            state         = { "1": "in_progress", "2": "pending" },
            subjects      = { "1": "fix bug", "2": "write doc" },
            query_results = [ _miss(), _miss() ],
        )
        assert ( res[ "owed" ], res[ "created" ], res[ "skipped" ], res[ "would_create" ], res[ "failed" ] ) == ( 2, 2, 0, 0, 0 )
        assert len( calls[ "created_payloads" ] ) == 2
        # identity matches the mirror's create branch
        p = calls[ "created_payloads" ][ 0 ]
        assert p[ "owner_persona" ] == "krishna" and p[ "accountable_manager" ] == "krishna"
        assert p[ "project" ] == "lupin" and p[ "item_class" ] == "task"
        assert p[ "created_by" ] == "krishna sid12345"
        assert p[ "correlation_key" ] == "cc-task:sid12345:g0:1"
        assert p[ "title" ] == "fix bug"

    def test_idempotent_skip_when_present( self ):
        res, calls = self._run(
            state         = { "1": "in_progress" },
            query_results = [ _hit( "queued" ) ],          # already in store
        )
        assert ( res[ "created" ], res[ "skipped" ], res[ "failed" ] ) == ( 0, 1, 0 )
        assert calls[ "created_payloads" ] == [ ]          # NEVER duplicates

    def test_dry_run_counts_would_create_no_writes( self ):
        res, calls = self._run(
            state         = { "1": "in_progress", "2": "pending" },
            query_results = [ _miss(), _hit( "in_progress" ) ],
            apply         = False,
        )
        assert ( res[ "would_create" ], res[ "skipped" ], res[ "created" ] ) == ( 1, 1, 0 )
        assert calls[ "created_payloads" ] == [ ]          # dry-run writes nothing

    def test_probe_failure_counts_failed( self ):
        res, _ = self._run(
            state         = { "1": "in_progress" },
            query_results = [ _fail() ],
        )
        assert ( res[ "failed" ], res[ "created" ], res[ "skipped" ] ) == ( 1, 0, 0 )

    def test_create_failure_counts_failed( self ):
        res, _ = self._run(
            state         = { "1": "in_progress" },
            query_results = [ _miss() ],
            create_ok     = False,
        )
        assert ( res[ "failed" ], res[ "created" ] ) == ( 1, 0 )

    def test_subject_fallback_when_missing( self ):
        res, calls = self._run(
            state         = { "1": "pending" },
            subjects      = { },                            # no recovered subject
            query_results = [ _miss() ],
        )
        assert calls[ "created_payloads" ][ 0 ][ "title" ] == drain.DRAIN_TITLE_FALLBACK

    def test_no_owed_is_all_zero( self ):
        res, calls = self._run(
            state         = { "1": "completed", "2": "deleted" },
            query_results = [ ],
        )
        assert ( res[ "owed" ], res[ "created" ], res[ "skipped" ], res[ "failed" ] ) == ( 0, 0, 0, 0 )
        assert res[ "generation" ] == 0


# ---------------------------------------------------------------------------
# check_session_parity
# ---------------------------------------------------------------------------

class TestParity:

    def _run( self, *, state, query_results ):
        q_iter = iter( query_results )
        return drain.check_session_parity(
            SETTINGS, "key", _session(),
            _replay             = lambda _p: state,
            _current_generation = lambda _sid, _bd: 0,
            _query              = lambda s, k, ck: next( q_iter ),
        )

    def test_parity_true_when_all_owed_present( self ):
        res = self._run(
            state         = { "1": "in_progress", "2": "pending" },
            query_results = [ _hit( "in_progress" ), _hit( "queued" ) ],
        )
        assert ( res[ "transcript_owed" ], res[ "store_owed" ], res[ "query_ok" ], res[ "parity" ] ) == ( 2, 2, True, True )

    def test_parity_false_on_missing_store_row( self ):
        res = self._run(
            state         = { "1": "in_progress", "2": "pending" },
            query_results = [ _hit( "queued" ), _miss() ],      # one owed row absent
        )
        assert ( res[ "store_owed" ], res[ "parity" ] ) == ( 1, False )

    def test_terminal_store_row_not_counted_owed( self ):
        res = self._run(
            state         = { "1": "in_progress" },
            query_results = [ _hit( "done" ) ],                 # present but NOT owed
        )
        assert ( res[ "store_owed" ], res[ "parity" ] ) == ( 0, False )

    def test_probe_failure_sets_query_not_ok( self ):
        res = self._run(
            state         = { "1": "in_progress" },
            query_results = [ _fail() ],
        )
        assert res[ "query_ok" ] is False and res[ "parity" ] is False

    def test_none_tasks_body_treated_empty( self ):
        # a probe that answers 2xx but with tasks=None must not raise
        res = self._run(
            state         = { "1": "in_progress" },
            query_results = [ ( True, 200, { "tasks": None, "count": 0 } ) ],
        )
        assert ( res[ "store_owed" ], res[ "parity" ] ) == ( 0, False )

    def test_zero_owed_is_trivially_parity_true( self ):
        res = self._run( state={ "1": "completed" }, query_results=[ ] )
        assert ( res[ "transcript_owed" ], res[ "store_owed" ], res[ "parity" ] ) == ( 0, 0, True )


# ---------------------------------------------------------------------------
# run_drain (orchestrator) + format_report + main
# ---------------------------------------------------------------------------

class TestRunDrain:

    def _sessions( self ):
        return [ _session( session_id="s1" ), _session( session_id="s2" ) ]

    def test_aggregates_totals_and_parity( self ):
        def _drain( settings, api_key, session, base_dir=None, environ=None, apply=True ):
            return { "session_id": session[ "session_id" ], "persona_lower": "krishna", "project": "lupin",
                     "generation": 0, "owed": 2, "created": 1, "skipped": 1, "would_create": 0, "failed": 0 }
        def _parity( settings, api_key, session, base_dir=None ):
            ok = session[ "session_id" ] == "s1"
            return { "session_id": session[ "session_id" ], "transcript_owed": 2,
                     "store_owed": 2 if ok else 1, "query_ok": True, "parity": ok }
        report = drain.run_drain(
            apply          = True,
            _load_settings = lambda: SETTINGS,
            _read_api_key  = lambda environ=None: "key",
            _discover      = lambda stale_threshold_seconds=43200, environ=None: self._sessions(),
            _drain         = _drain,
            _parity        = _parity,
        )
        assert report[ "apply" ] is True and report[ "sessions" ] == 2
        t = report[ "totals" ]
        assert t == { "owed": 4, "created": 2, "skipped": 2, "would_create": 0, "failed": 0, "parity_ok": 1 }
        assert len( report[ "drains" ] ) == 2 and len( report[ "parities" ] ) == 2

    def test_empty_fleet( self ):
        report = drain.run_drain(
            _load_settings = lambda: SETTINGS,
            _read_api_key  = lambda environ=None: "key",
            _discover      = lambda stale_threshold_seconds=43200, environ=None: [ ],
        )
        assert report[ "sessions" ] == 0 and report[ "totals" ][ "parity_ok" ] == 0
        assert report[ "apply" ] is False                  # default dry-run


class TestFormatReport:

    def _report( self, apply, parity ):
        return {
            "apply"    : apply,
            "sessions" : 1,
            "totals"   : { "owed": 1, "created": 1, "skipped": 0, "would_create": 0, "failed": 0, "parity_ok": 1 if parity else 0 },
            "drains"   : [ { "session_id": "s1abcdef", "persona_lower": "krishna", "owed": 1,
                             "created": 1, "skipped": 0, "would_create": 0, "failed": 0 } ],
            "parities" : [ { "session_id": "s1abcdef", "parity": parity } ],
        }

    def test_apply_header_and_parity_ok_row( self ):
        out = drain.format_report( self._report( True, True ) )
        assert "[APPLY]" in out and "OK" in out and "TOTAL:" in out

    def test_dry_run_header_and_parity_no_row( self ):
        out = drain.format_report( self._report( False, False ) )
        assert "[DRY-RUN]" in out and "NO" in out

    def test_missing_parity_for_sid_renders_no( self ):
        report = self._report( True, True )
        report[ "parities" ] = [ ]                          # no parity row for the drain's sid
        out = drain.format_report( report )
        assert "NO" in out


class TestMain:

    def test_dry_run_all_green_returns_zero( self, monkeypatch, capsys ):
        monkeypatch.setattr( drain, "run_drain", lambda apply=False: {
            "apply": apply, "sessions": 1,
            "totals": { "owed": 0, "created": 0, "skipped": 0, "would_create": 0, "failed": 0, "parity_ok": 1 },
            "drains": [ ], "parities": [ ],
        } )
        assert drain.main( [ ] ) == 0
        assert "[DRY-RUN]" in capsys.readouterr().out

    def test_apply_flag_parsed_and_failure_returns_one( self, monkeypatch ):
        seen = { }
        def _run( apply=False ):
            seen[ "apply" ] = apply
            return { "apply": apply, "sessions": 2,
                     "totals": { "owed": 0, "created": 0, "skipped": 0, "would_create": 0, "failed": 1, "parity_ok": 2 },
                     "drains": [ ], "parities": [ ] }
        monkeypatch.setattr( drain, "run_drain", _run )
        assert drain.main( [ "--apply" ] ) == 1            # failed>0 → non-zero exit
        assert seen[ "apply" ] is True

    def test_parity_short_returns_one( self, monkeypatch ):
        monkeypatch.setattr( drain, "run_drain", lambda apply=False: {
            "apply": apply, "sessions": 3,
            "totals": { "owed": 0, "created": 0, "skipped": 0, "would_create": 0, "failed": 0, "parity_ok": 2 },
            "drains": [ ], "parities": [ ] } )                # parity_ok 2 < sessions 3
        assert drain.main( [ ] ) == 1

    def test_argv_none_reads_sys_argv( self, monkeypatch ):
        seen = { }
        monkeypatch.setattr( sys, "argv", [ "prog", "--apply" ] )
        def _run( apply=False ):
            seen[ "apply" ] = apply
            return { "apply": apply, "sessions": 0,
                     "totals": { "owed": 0, "created": 0, "skipped": 0, "would_create": 0, "failed": 0, "parity_ok": 0 },
                     "drains": [ ], "parities": [ ] }
        monkeypatch.setattr( drain, "run_drain", _run )
        assert drain.main() == 0                            # 0 sessions, 0 failed → green
        assert seen[ "apply" ] is True


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
