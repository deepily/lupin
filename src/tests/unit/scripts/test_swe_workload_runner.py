"""
Coverage ramp for `src/scripts/swe_workload_runner.py` — 163 statements, 44 branches,
previously zero (row ba6df71e, fourth file off the 29-file zero set).

WHAT THIS FILE IS AND IS NOT. The runner is a THIN ORCHESTRATOR over four seams it
does not own: HTTP (`requests`), the clock (`time.sleep`), PostgreSQL, and argv.
Every one of them is injected here — no server, no database, no sleeping. What is
worth pinning in a file like this is not "does HTTP work" but the DECISIONS it makes
around those seams: which failures it swallows, which it reports, what it writes to
the manifest, and what exit code it leaves behind. Those are the parts a refactor
can silently invert.

⚠️ REPORTED AS STATEMENTS AND BRANCHES, NEVER A PERCENTAGE. `pyproject.toml` lists
six packages and `src/scripts` is not among them, so these statements sit outside the
gate's denominator until Rachel's frame change lands. A percentage computed against a
frame that exists in one tree travels wrong the moment it leaves the row; 163 and 44
stay true whatever floor gets pinned.

THE DELIBERATE NEGATIVE CONTROLS, because a runner's error handling is where a green
suite lies most easily:
  · `get_websocket_session_id` swallows EVERY exception and returns a fallback — so a
    test that only checks the happy path would pass against a function that had
    silently stopped calling the server at all.
  · `capture_decisions_for_job` returns `[]` on any failure, which is indistinguishable
    from "the job genuinely made no decisions". Both are asserted separately.
  · `poll_done_queue` prints and CONTINUES on a transport error. A test that asserted
    only the timeout would not notice if it started raising instead.
"""

import importlib
import json
import os
import sys
import uuid
from datetime import datetime
from types import ModuleType, SimpleNamespace

import pytest
import requests

_SCRIPTS = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" )
if _SCRIPTS not in sys.path:
    sys.path.insert( 0, _SCRIPTS )

import swe_workload_runner as swr


# ── Injected seams ────────────────────────────────────────────────────────────

class _Resp:
    """The slice of a requests.Response this module actually touches."""
    def __init__( self, status_code=200, payload=None, text="" ):
        self.status_code = status_code
        self._payload    = payload if payload is not None else {}
        self.text        = text

    def json( self ):
        return self._payload

    def raise_for_status( self ):
        if self.status_code >= 400:
            raise requests.HTTPError( f"HTTP {self.status_code}" )


def _task( task_id="T1", text="do the thing", category="testing" ):
    return { "id": task_id, "task": text, "category": category }


@pytest.fixture( autouse=True )
def _creds( monkeypatch ):
    """Every test starts with credentials present; the missing case sets its own."""
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )


@pytest.fixture( autouse=True )
def _no_sleeping( monkeypatch ):
    """The poll loop's clock. Left real, this suite would take minutes."""
    monkeypatch.setattr( swr.time, "sleep", lambda _s: None )


# ── Module bootstrap ──────────────────────────────────────────────────────────

class TestBootstrap:
    """
    The import-time guard. It runs before anything else can, so a broken message here
    is the first thing a new operator sees.
    """

    def test_a_missing_lupin_root_refuses_at_import_with_the_fix_in_the_message( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        with pytest.raises( RuntimeError ) as excinfo:
            importlib.reload( swr )
        # Not merely "it raised" — the message must carry the remedy, which is the
        # only reason to raise here rather than let the later import fail on its own.
        assert "LUPIN_ROOT" in str( excinfo.value )
        assert "export LUPIN_ROOT" in str( excinfo.value )

    def test_reimport_with_src_already_on_the_path_does_not_duplicate_it( self, monkeypatch ):
        """
        The `if src_path not in sys.path` FALSE branch. Reloading a module whose path
        entry is already present must leave sys.path alone — an import guard that
        appended every time would grow the path without bound in a long session.
        """
        root = os.environ[ "LUPIN_ROOT" ]
        src  = os.path.join( root, "src" )
        assert src in sys.path, "precondition: the first import already inserted it"
        before = sys.path.count( src )

        importlib.reload( swr )

        assert sys.path.count( src ) == before

    def test_a_path_without_src_gets_it_inserted_at_the_front( self, monkeypatch ):
        """
        The TRUE half of the same guard. `insert( 0, ... )` not `append` is the part
        worth pinning: the runner imports `scripts.swe_workload_catalog`, and a repo
        earlier on the path could otherwise shadow it.
        """
        root  = os.environ[ "LUPIN_ROOT" ]
        src   = os.path.join( root, "src" )
        monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )

        importlib.reload( swr )

        assert sys.path[ 0 ] == src


# ── login ─────────────────────────────────────────────────────────────────────

class TestLogin:

    def test_returns_the_token_and_a_bearer_header( self, monkeypatch ):
        seen = {}
        def _post( url, json=None, timeout=None ):
            seen[ "url" ]  = url
            seen[ "json" ] = json
            return _Resp( payload={ "tokens": { "access_token": "tok-123" } } )
        monkeypatch.setattr( swr.requests, "post", _post )

        token, headers = swr.login()

        assert token == "tok-123"
        assert headers == { "Authorization": "Bearer tok-123" }
        assert seen[ "url" ].endswith( "/auth/login" )
        assert seen[ "json" ] == { "email": "a@b.c", "password": "pw" }

    @pytest.mark.parametrize( "missing", [ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL",
                                           "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ] )
    def test_either_credential_missing_refuses_before_any_request( self, monkeypatch, missing ):
        """
        Both halves of the `not email or not password` guard, and the important part:
        it must refuse WITHOUT calling the server, so a misconfigured run fails at the
        operator's terminal rather than as a puzzling 401 in the server log.
        """
        monkeypatch.delenv( missing, raising=False )
        def _boom( *a, **k ):
            raise AssertionError( "login() reached the network with no credentials" )
        monkeypatch.setattr( swr.requests, "post", _boom )

        with pytest.raises( ValueError ) as excinfo:
            swr.login()
        assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" in str( excinfo.value )

    def test_a_rejected_login_propagates_rather_than_returning_a_bad_token( self, monkeypatch ):
        monkeypatch.setattr( swr.requests, "post", lambda *a, **k: _Resp( status_code=401 ) )
        with pytest.raises( requests.HTTPError ):
            swr.login()


# ── get_websocket_session_id ──────────────────────────────────────────────────

class TestWebsocketSessionId:

    def test_returns_the_servers_session_id( self, monkeypatch ):
        monkeypatch.setattr( swr.requests, "get",
                             lambda *a, **k: _Resp( payload={ "session_id": "wise-penguin" } ) )
        assert swr.get_websocket_session_id( {} ) == "wise-penguin"

    def test_a_200_that_omits_the_id_still_yields_the_fallback( self, monkeypatch ):
        monkeypatch.setattr( swr.requests, "get", lambda *a, **k: _Resp( payload={} ) )
        assert swr.get_websocket_session_id( {} ) == "workload-runner"

    def test_a_non_200_yields_the_fallback( self, monkeypatch ):
        monkeypatch.setattr( swr.requests, "get", lambda *a, **k: _Resp( status_code=503 ) )
        assert swr.get_websocket_session_id( {} ) == "workload-runner"

    def test_a_transport_failure_yields_the_fallback_rather_than_raising( self, monkeypatch ):
        """
        THE SWALLOW. This function catches bare `Exception`, so it cannot fail — which
        is right for a cosmetic id, and is exactly why the other three cases above are
        asserted separately. Without them, a function that had stopped calling the
        server entirely would still pass.
        """
        def _boom( *a, **k ):
            raise requests.ConnectionError( "no server" )
        monkeypatch.setattr( swr.requests, "get", _boom )
        assert swr.get_websocket_session_id( {} ) == "workload-runner"


# ── submit_task ───────────────────────────────────────────────────────────────

class TestSubmitTask:
    """
    Every failure here returns ( None, message ) rather than raising — the runner is a
    batch job and one bad task must not end the run. That makes the MESSAGE the only
    signal an operator gets, so each one is asserted for content, not just truthiness.
    """

    def _capture( self, monkeypatch, resp ):
        seen = {}
        def _post( url, json=None, headers=None, timeout=None ):
            seen[ "url" ]     = url
            seen[ "json" ]    = json
            seen[ "headers" ] = headers
            return resp
        monkeypatch.setattr( swr.requests, "post", _post )
        return seen

    def test_posts_through_the_one_front_door_with_routing_command_and_top_level_websocket_id( self, monkeypatch ):
        """
        The v2 front-door contract. `websocket_id` is TOP-LEVEL and the task's own
        fields live under `args` — the dedicated door this replaced answers 410, and
        putting `websocket_id` inside `args` is exactly how the payload gets rejected
        against the command's argument contract.
        """
        seen = self._capture( monkeypatch, _Resp( payload={ "job_id": "job-77" } ) )

        job_id, error = swr.submit_task( _task(), { "Authorization": "Bearer t" }, "ws-9" )

        assert ( job_id, error ) == ( "job-77", None )
        assert seen[ "url" ].endswith( "/api/v2/submit" )
        assert seen[ "json" ][ "command" ]      == "agent router go to swe team"
        assert seen[ "json" ][ "websocket_id" ] == "ws-9"
        assert seen[ "json" ][ "args" ]         == { "task": "do the thing", "dry_run": True }
        assert "websocket_id" not in seen[ "json" ][ "args" ]
        assert seen[ "headers" ] == { "Authorization": "Bearer t" }

    def test_trust_mode_when_given_rides_in_args_and_is_absent_otherwise( self, monkeypatch ):
        seen = self._capture( monkeypatch, _Resp( payload={ "job_id": "j" } ) )

        swr.submit_task( _task(), {}, "ws", dry_run=False, trust_mode="shadow" )
        assert seen[ "json" ][ "args" ] == { "task": "do the thing", "dry_run": False, "trust_mode": "shadow" }

        swr.submit_task( _task(), {}, "ws", trust_mode=None )
        assert "trust_mode" not in seen[ "json" ][ "args" ]

    def test_a_timeout_is_named_as_a_timeout_not_folded_into_the_generic_error( self, monkeypatch ):
        """
        `requests.exceptions.Timeout` has its own except arm ahead of the bare one.
        Collapsing the two would still pass a test that only asserted "some error",
        and would cost the operator the one distinction that says 'retry me'.
        """
        def _post( *a, **k ):
            raise requests.exceptions.Timeout( "slow" )
        monkeypatch.setattr( swr.requests, "post", _post )

        assert swr.submit_task( _task(), {}, "ws" ) == ( None, "Submit timed out" )

    def test_any_other_transport_failure_reports_the_underlying_message( self, monkeypatch ):
        def _post( *a, **k ):
            raise requests.ConnectionError( "connection refused" )
        monkeypatch.setattr( swr.requests, "post", _post )

        job_id, error = swr.submit_task( _task(), {}, "ws" )
        assert job_id is None
        assert error.startswith( "Submit error: " )
        assert "connection refused" in error

    def test_a_non_200_reports_the_status_and_a_bounded_slice_of_the_body( self, monkeypatch ):
        """The [:200] truncation — an HTML error page must not flood the console."""
        self._capture( monkeypatch, _Resp( status_code=500, text="x" * 500 ) )

        job_id, error = swr.submit_task( _task(), {}, "ws" )
        assert job_id is None
        assert error.startswith( "HTTP 500: " )
        assert error.count( "x" ) == 200

    def test_a_200_carrying_no_job_id_is_a_failure_not_a_silent_none( self, monkeypatch ):
        """
        The case a happy-path-only suite misses: HTTP said fine, the queue gave us
        nothing to poll for. Returning ( None, None ) here would send the caller into
        poll_done_queue with a null id.
        """
        self._capture( monkeypatch, _Resp( payload={ "detail": "rejected" } ) )

        job_id, error = swr.submit_task( _task(), {}, "ws" )
        assert job_id is None
        assert "No job_id in response" in error


# ── poll_done_queue ───────────────────────────────────────────────────────────

class TestPollDoneQueue:

    def test_returns_the_matching_job_out_of_a_queue_holding_several( self, monkeypatch ):
        """
        Not merely 'it returns something' — the done queue holds every user's finished
        jobs, so picking the FIRST entry rather than the matching one would pass a
        single-entry test and hand back a stranger's job in production.
        """
        payload = { "done_jobs_metadata": [
            { "job_id": "other-1", "status": "done" },
            { "job_id": "mine",    "status": "completed" },
        ] }
        monkeypatch.setattr( swr.requests, "get", lambda *a, **k: _Resp( payload=payload ) )

        job, error = swr.poll_done_queue( "mine", {} )

        assert error is None
        assert job == { "job_id": "mine", "status": "completed" }

    def test_keeps_polling_past_a_queue_that_does_not_hold_it_yet( self, monkeypatch ):
        calls = { "n": 0 }
        def _get( *a, **k ):
            calls[ "n" ] += 1
            if calls[ "n" ] < 3:
                return _Resp( payload={ "done_jobs_metadata": [] } )
            return _Resp( payload={ "done_jobs_metadata": [ { "job_id": "j" } ] } )
        monkeypatch.setattr( swr.requests, "get", _get )

        job, error = swr.poll_done_queue( "j", {}, timeout=60 )

        assert ( job, error ) == ( { "job_id": "j" }, None )
        assert calls[ "n" ] == 3

    def test_a_non_200_is_tolerated_and_the_loop_carries_on( self, monkeypatch ):
        calls = { "n": 0 }
        def _get( *a, **k ):
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:
                return _Resp( status_code=502 )
            return _Resp( payload={ "done_jobs_metadata": [ { "job_id": "j" } ] } )
        monkeypatch.setattr( swr.requests, "get", _get )

        job, error = swr.poll_done_queue( "j", {}, timeout=60 )
        assert ( job, error ) == ( { "job_id": "j" }, None )

    def test_a_transport_failure_prints_and_continues_rather_than_aborting_the_run( self, monkeypatch, capsys ):
        """
        THE SWALLOW, and the reason it is right: a server bounce mid-poll should cost
        one interval, not the whole batch. A test asserting only the timeout would not
        notice if this started raising.
        """
        calls = { "n": 0 }
        def _get( *a, **k ):
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:
                raise requests.ConnectionError( "server bounced" )
            return _Resp( payload={ "done_jobs_metadata": [ { "job_id": "j" } ] } )
        monkeypatch.setattr( swr.requests, "get", _get )

        job, error = swr.poll_done_queue( "j", {}, timeout=60 )

        assert ( job, error ) == ( { "job_id": "j" }, None )
        assert "Poll error: server bounced" in capsys.readouterr().out

    def test_gives_up_after_the_timeout_and_names_the_budget_it_spent( self, monkeypatch ):
        monkeypatch.setattr( swr.requests, "get",
                             lambda *a, **k: _Resp( payload={ "done_jobs_metadata": [] } ) )

        job, error = swr.poll_done_queue( "never-arrives", {}, timeout=4 )

        assert job is None
        assert error == "Timeout after 4s"

    def test_a_zero_timeout_never_calls_the_server_at_all( self, monkeypatch ):
        """The while-loop's false-on-entry branch."""
        def _boom( *a, **k ):
            raise AssertionError( "polled despite a zero budget" )
        monkeypatch.setattr( swr.requests, "get", _boom )

        assert swr.poll_done_queue( "j", {}, timeout=0 ) == ( None, "Timeout after 0s" )


# ── capture_decisions_for_job ─────────────────────────────────────────────────

class _FakeSession:
    def __init__( self, rows ):
        self.rows = rows
        self.seen = {}

    def execute( self, statement, params ):
        self.seen[ "sql" ]    = str( statement )
        self.seen[ "params" ] = params
        return iter( self.rows )


class _FakeGetDb:
    """Stands in for `cosa.rest.db.database.get_db` — a context manager, not a call."""
    def __init__( self, session ):
        self.session = session
        self.exited  = False

    def __call__( self ):
        return self

    def __enter__( self ):
        return self.session

    def __exit__( self, *exc ):
        self.exited = True
        return False


def _row( **over ):
    base = {
        "id"                 : uuid.UUID( "00000000-0000-0000-0000-0000000000aa" ),
        "notification_id"    : "n-1",
        "domain"             : "swe",
        "category"           : "testing",
        "question"           : "run it?",
        "action"             : "approve",
        "decision_value"     : "yes",
        "confidence"         : 0.91,
        "trust_level"        : "high",
        "reason"             : "because",
        "ratification_state" : "pending",
        "data_origin"        : "proxy",
        "metadata_json"      : { "job_id": "j-1" },
        "created_at"         : datetime( 2026, 8, 29, 12, 0, 0 ),
    }
    base.update( over )
    return SimpleNamespace( **base )


@pytest.fixture
def _fake_db( monkeypatch ):
    """Injects a stand-in for the PG module the function imports lazily."""
    def _install( rows ):
        session = _FakeSession( rows )
        getdb   = _FakeGetDb( session )
        module  = ModuleType( "cosa.rest.db.database" )
        module.get_db = getdb
        monkeypatch.setitem( sys.modules, "cosa.rest.db.database", module )
        return getdb
    return _install


class TestCaptureDecisions:

    def test_maps_every_column_and_stringifies_the_uuid_for_jsonl( self, _fake_db ):
        getdb = _fake_db( [ _row() ] )

        decisions = swr.capture_decisions_for_job( "j-1" )

        assert len( decisions ) == 1
        d = decisions[ 0 ]
        # The id must be a str, not a UUID — this row is json.dumps'd into the manifest.
        assert d[ "id" ] == "00000000-0000-0000-0000-0000000000aa"
        assert isinstance( d[ "id" ], str )
        assert d[ "created_at" ] == "2026-08-29T12:00:00"
        assert d[ "category" ] == "testing"
        assert d[ "confidence" ] == 0.91
        assert d[ "metadata_json" ] == { "job_id": "j-1" }
        assert getdb.exited, "the session must be closed even on the happy path"
        assert getdb.session.seen[ "params" ] == { "job_id": "j-1" }

    def test_scopes_the_query_to_the_job_via_the_metadata_json_key( self, _fake_db ):
        """
        The WHERE clause is the whole point: proxy_decisions holds every job's rows,
        so a query that lost its filter would attribute the fleet's decisions to one job.
        """
        getdb = _fake_db( [] )
        swr.capture_decisions_for_job( "j-9" )

        sql = getdb.session.seen[ "sql" ]
        assert "metadata_json->>'job_id' = :job_id" in sql
        assert "ORDER BY created_at ASC" in sql
        assert getdb.session.seen[ "params" ] == { "job_id": "j-9" }

    def test_a_null_created_at_becomes_none_rather_than_raising_on_isoformat( self, _fake_db ):
        _fake_db( [ _row( created_at=None ) ] )
        assert swr.capture_decisions_for_job( "j-1" )[ 0 ][ "created_at" ] is None

    def test_a_job_with_no_decisions_returns_an_empty_list( self, _fake_db ):
        assert swr.capture_decisions_for_job( "j-1" ) == []

    def test_a_database_failure_warns_and_returns_empty_rather_than_killing_the_run( self, monkeypatch, capsys ):
        """
        THE AMBIGUOUS EMPTY. This returns [] on failure, which is byte-identical to the
        legitimate no-decisions case above — so both are asserted, and this one is
        distinguished by the warning it must print. Drop the print and an unreachable
        database becomes indistinguishable from a quiet job.
        """
        module = ModuleType( "cosa.rest.db.database" )
        def _boom():
            raise RuntimeError( "could not connect to lupin_db_test" )
        module.get_db = _boom
        monkeypatch.setitem( sys.modules, "cosa.rest.db.database", module )

        assert swr.capture_decisions_for_job( "j-1" ) == []

        out = capsys.readouterr().out
        assert "Warning: Failed to capture decisions" in out
        assert "could not connect to lupin_db_test" in out


# ── run_workload ──────────────────────────────────────────────────────────────

@pytest.fixture
def _wired( monkeypatch ):
    """
    Wires the four collaborators run_workload calls, each already pinned by its own
    class above. What is under test here is the ORCHESTRATION — which failures end a
    task, what lands in the manifest, and what the summary counts.
    """
    state = {
        "submits" : [],
        "polls"   : [],
        "captures": [],
    }
    monkeypatch.setattr( swr, "login", lambda: ( "tok", { "Authorization": "Bearer tok" } ) )
    monkeypatch.setattr( swr, "get_websocket_session_id", lambda headers: "ws-1" )

    def _submit( task, headers, ws_id, dry_run=True, trust_mode=None ):
        state[ "submits" ].append( { "task": task, "dry_run": dry_run, "trust_mode": trust_mode, "ws_id": ws_id } )
        return state[ "submit_returns" ].pop( 0 )
    def _poll( job_id, headers, timeout=swr.DEFAULT_TIMEOUT ):
        state[ "polls" ].append( job_id )
        return state[ "poll_returns" ].pop( 0 )
    def _capture( job_id ):
        state[ "captures" ].append( job_id )
        return state[ "capture_returns" ].pop( 0 )

    monkeypatch.setattr( swr, "submit_task", _submit )
    monkeypatch.setattr( swr, "poll_done_queue", _poll )
    monkeypatch.setattr( swr, "capture_decisions_for_job", _capture )
    return state


def _decision( category="testing", confidence=0.5, value="yes" ):
    return { "category": category, "confidence": confidence, "decision_value": value }


class TestRunWorkload:

    def test_a_completed_task_writes_one_jsonl_line_carrying_its_decisions( self, _wired, tmp_path ):
        _wired[ "submit_returns" ]  = [ ( "job-1", None ) ]
        _wired[ "poll_returns" ]    = [ ( { "job_id": "job-1", "status": "done" }, None ) ]
        _wired[ "capture_returns" ] = [ [ _decision( confidence=0.75 ) ] ]
        manifest = tmp_path / "m.jsonl"

        results, path = swr.run_workload( [ _task() ], manifest_path=str( manifest ) )

        assert path == str( manifest )
        assert results[ 0 ][ "status" ] == "completed"
        assert results[ 0 ][ "expected_category" ] == "testing"
        # The file is the deliverable — assert the bytes on disk, not just the return value.
        lines = manifest.read_text().strip().splitlines()
        assert len( lines ) == 1
        written = json.loads( lines[ 0 ] )
        assert written[ "job_id" ] == "job-1"
        assert written[ "decisions" ][ 0 ][ "confidence" ] == 0.75

    def test_a_submit_failure_records_it_and_moves_to_the_next_task( self, _wired, tmp_path ):
        """
        The `continue` after a failed submit. A batch runner that stopped on the first
        bad task would silently shrink the workload; the manifest must still hold a
        line for it, with a null job_id and the error.
        """
        _wired[ "submit_returns" ]  = [ ( None, "HTTP 500: boom" ), ( "job-2", None ) ]
        _wired[ "poll_returns" ]    = [ ( { "status": "done" }, None ) ]
        _wired[ "capture_returns" ] = [ [] ]
        manifest = tmp_path / "m.jsonl"

        results, _ = swr.run_workload( [ _task( "T1" ), _task( "T2" ) ], manifest_path=str( manifest ) )

        assert [ r[ "status" ] for r in results ] == [ "submit_failed", "completed" ]
        assert results[ 0 ][ "job_id" ] is None
        assert results[ 0 ][ "error" ] == "HTTP 500: boom"
        assert results[ 0 ][ "decisions" ] == []
        # The failed task must never have been polled or queried for decisions.
        assert _wired[ "polls" ]    == [ "job-2" ]
        assert _wired[ "captures" ] == [ "job-2" ]
        assert len( manifest.read_text().strip().splitlines() ) == 2

    def test_a_poll_timeout_keeps_the_job_id_so_the_run_can_be_traced_afterwards( self, _wired, tmp_path ):
        """
        The distinction that matters between the two failure rows: a submit failure has
        no job to look up, a timeout does. Losing the id here would make a slow job
        indistinguishable from one that never entered the queue.
        """
        _wired[ "submit_returns" ] = [ ( "job-3", None ) ]
        _wired[ "poll_returns" ]   = [ ( None, "Timeout after 120s" ) ]
        manifest = tmp_path / "m.jsonl"

        results, _ = swr.run_workload( [ _task() ], manifest_path=str( manifest ) )

        assert results[ 0 ][ "status" ] == "timeout"
        assert results[ 0 ][ "job_id" ] == "job-3"
        assert results[ 0 ][ "error" ]  == "Timeout after 120s"
        assert _wired[ "captures" ] == []

    def test_the_summary_counts_only_completed_tasks_and_dedupes_categories( self, _wired, tmp_path, capsys ):
        _wired[ "submit_returns" ]  = [ ( "job-a", None ), ( None, "nope" ) ]
        _wired[ "poll_returns" ]    = [ ( { "status": "done" }, None ) ]
        _wired[ "capture_returns" ] = [ [ _decision( "testing" ), _decision( "testing" ), _decision( "docs" ) ] ]
        manifest = tmp_path / "m.jsonl"

        swr.run_workload( [ _task( "T1" ), _task( "T2" ) ], manifest_path=str( manifest ) )

        out = capsys.readouterr().out
        assert "Total: 1/2 completed, 3 proxy decisions captured" in out
        # Two "testing" decisions collapse to one label in the categories column.
        assert "—" in out, "the failed row's empty-categories placeholder"

    def test_a_generated_manifest_path_names_the_mode_and_category_under_lupin_root( self, _wired, tmp_path, monkeypatch ):
        """
        The manifest_path=None branch. The filename is the only handle a downstream
        fixture-generator has, so mode and category must survive into it.
        """
        monkeypatch.setattr( swr, "lupin_root", str( tmp_path ) )
        _wired[ "submit_returns" ]  = [ ( "j", None ) ]
        _wired[ "poll_returns" ]    = [ ( { "status": "done" }, None ) ]
        _wired[ "capture_returns" ] = [ [] ]

        _, path = swr.run_workload( [ _task() ], dry_run=False, category="testing" )

        assert path.startswith( str( tmp_path / "io" / "decision-proxies" ) )
        assert "workload-manifest-swe-team-catalog-testing-live-" in path
        assert path.endswith( ".jsonl" )
        assert os.path.exists( path )

    def test_a_generated_path_with_no_category_says_all_and_dry_run_says_dry_run( self, _wired, tmp_path, monkeypatch ):
        monkeypatch.setattr( swr, "lupin_root", str( tmp_path ) )
        _wired[ "submit_returns" ]  = [ ( "j", None ) ]
        _wired[ "poll_returns" ]    = [ ( { "status": "done" }, None ) ]
        _wired[ "capture_returns" ] = [ [] ]

        _, path = swr.run_workload( [ _task() ] )

        assert "workload-manifest-swe-team-catalog-all-dry-run-" in path

    def test_dry_run_and_trust_mode_reach_submit_task_unchanged( self, _wired, tmp_path ):
        _wired[ "submit_returns" ]  = [ ( "j", None ) ]
        _wired[ "poll_returns" ]    = [ ( { "status": "done" }, None ) ]
        _wired[ "capture_returns" ] = [ [] ]

        swr.run_workload( [ _task() ], dry_run=False, trust_mode="active",
                          manifest_path=str( tmp_path / "m.jsonl" ) )

        assert _wired[ "submits" ][ 0 ][ "dry_run" ]    is False
        assert _wired[ "submits" ][ 0 ][ "trust_mode" ] == "active"
        assert _wired[ "submits" ][ 0 ][ "ws_id" ]      == "ws-1"

    def test_a_job_whose_metadata_omits_status_still_prints_rather_than_raising( self, _wired, tmp_path, capsys ):
        _wired[ "submit_returns" ]  = [ ( "j", None ) ]
        _wired[ "poll_returns" ]    = [ ( {}, None ) ]
        _wired[ "capture_returns" ] = [ [] ]

        swr.run_workload( [ _task() ], manifest_path=str( tmp_path / "m.jsonl" ) )

        assert "Completed: status=unknown" in capsys.readouterr().out


# ── main ──────────────────────────────────────────────────────────────────────

class TestMain:

    @pytest.fixture( autouse=True )
    def _catalog_and_runner( self, monkeypatch ):
        self.seen = {}
        monkeypatch.setattr( swr, "get_tasks_by_category",
                             lambda cat: self.catalog_returns( cat ) )
        def _run( tasks, dry_run=True, trust_mode=None, manifest_path=None, category=None ):
            self.seen.update( { "tasks": tasks, "dry_run": dry_run, "trust_mode": trust_mode,
                                "manifest_path": manifest_path, "category": category } )
            return self.run_returns, "/tmp/m.jsonl"
        monkeypatch.setattr( swr, "run_workload", _run )
        self.catalog_returns = lambda cat: [ _task( "T1" ), _task( "T2" ), _task( "T3" ) ]
        self.run_returns     = [ { "status": "completed" } ]

    def _argv( self, monkeypatch, *args ):
        monkeypatch.setattr( sys, "argv", [ "swe_workload_runner.py", *args ] )

    def test_defaults_are_dry_run_over_the_whole_catalog_and_exit_zero( self, monkeypatch ):
        self._argv( monkeypatch )

        with pytest.raises( SystemExit ) as excinfo:
            swr.main()

        assert excinfo.value.code == 0
        assert self.seen[ "dry_run" ]    is True
        assert self.seen[ "category" ]   is None
        assert self.seen[ "trust_mode" ] is None
        assert len( self.seen[ "tasks" ] ) == 3

    def test_the_live_flag_inverts_dry_run( self, monkeypatch ):
        """
        `dry_run = not args.live` is a one-line inversion guarding real LLM spend.
        Nothing else in the file would fail if it were dropped.
        """
        self._argv( monkeypatch, "--live" )
        with pytest.raises( SystemExit ):
            swr.main()
        assert self.seen[ "dry_run" ] is False

    def test_limit_truncates_the_selection_and_category_is_passed_through( self, monkeypatch ):
        got = {}
        def _catalog( cat ):
            got[ "cat" ] = cat
            return [ _task( "T1" ), _task( "T2" ), _task( "T3" ) ]
        self.catalog_returns = _catalog
        self._argv( monkeypatch, "--category", "testing", "--limit", "2" )

        with pytest.raises( SystemExit ):
            swr.main()

        assert got[ "cat" ] == "testing"
        assert [ t[ "id" ] for t in self.seen[ "tasks" ] ] == [ "T1", "T2" ]
        assert self.seen[ "category" ] == "testing"

    def test_no_limit_leaves_the_selection_whole( self, monkeypatch ):
        """The falsy-limit branch — `if args.limit` is skipped, not applied as zero."""
        self._argv( monkeypatch )
        with pytest.raises( SystemExit ):
            swr.main()
        assert len( self.seen[ "tasks" ] ) == 3

    def test_trust_mode_and_manifest_reach_the_runner( self, monkeypatch ):
        self._argv( monkeypatch, "--trust-mode", "shadow", "--manifest", "/tmp/out.jsonl" )
        with pytest.raises( SystemExit ):
            swr.main()
        assert self.seen[ "trust_mode" ]    == "shadow"
        assert self.seen[ "manifest_path" ] == "/tmp/out.jsonl"

    def test_an_empty_selection_exits_one_before_authenticating( self, monkeypatch, capsys ):
        """
        A bad --category filter must not reach login() — an empty run that authenticated,
        wrote an empty manifest and exited 0 would read in CI as a clean pass.
        """
        self.catalog_returns = lambda cat: []
        self._argv( monkeypatch, "--category", "nonesuch" )

        with pytest.raises( SystemExit ) as excinfo:
            swr.main()

        assert excinfo.value.code == 1
        assert "No tasks selected" in capsys.readouterr().out
        assert self.seen == {}, "run_workload must not have been reached"

    def test_any_task_short_of_completed_exits_one( self, monkeypatch ):
        """The exit code IS the CI signal — a run with a timed-out task must not read green."""
        self.run_returns = [ { "status": "completed" }, { "status": "timeout" } ]
        self._argv( monkeypatch )

        with pytest.raises( SystemExit ) as excinfo:
            swr.main()

        assert excinfo.value.code == 1
