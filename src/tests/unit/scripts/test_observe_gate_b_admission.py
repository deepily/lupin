"""
The Gate B admission observer, covered without a server, a container, or a socket.

Row `8541b1c6` — `src/scripts/observe_gate_b_admission.py`, 149 statements / 34 branches at
zero. The script's whole job is to submit a monopolizing test-suite job to `:8000` and watch
`/api/queue/pool-status` until it sees one sample where Gate B has admitted the child. None of
that may happen here.

WHAT THIS FILE IS CAREFUL ABOUT, because the script is a live probe and these tests are not:

· 🔴 NO LIVE SERVER, EITHER VENUE. `:7999` is shared and `:8000` is monopolize-mode. Every
  HTTP call is stopped at `urllib.request.urlopen` or at the module's own `_http`, so a missed
  patch surfaces as an error rather than as a real POST to `/api/test-suite/submit` — which
  would submit a monopolizing job off a unit test.
· 🔴 NO DOCKER. `check_mount` shells out to `docker inspect`; `subprocess.run` is patched at
  the MODULE attribute, so a missed patch is an error, not a container query.
· `time` is replaced with a stub clock. The real `watch` sleeps `POLL_SECONDS` between samples
  and watches for up to 1800 seconds; a test that used the real clock would either hang or
  measure the machine instead of the code.
· The filesystem is real but confined to `tmp_path`. `watch` fsyncs every sample deliberately
  (the 2026-08-21 attempt left no log), so it is exercised against a real file rather than a
  fake handle — the flush-and-fsync is the behaviour, not an implementation detail.
· No database is involved, so the two-venue database hazard does not apply here. Saying so
  rather than leaving the reader to wonder.

Each test names the change that reddens it.
"""

import argparse
import io
import json
import os
import subprocess
import sys

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import observe_gate_b_admission as obs


# ── doubles ───────────────────────────────────────────────────────────────────────────────

class _Resp:
    """The three things `_http` reads off a urlopen result, as a context manager."""

    def __init__( self, status, raw ):
        self.status = status
        self._raw   = raw

    def read( self ):
        return self._raw.encode()

    def __enter__( self ):
        return self

    def __exit__( self, *exc ):
        return False


class _Proc:
    """The three attributes of a CompletedProcess `check_mount` reads."""

    def __init__( self, returncode=0, stdout="", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


class _Clock:
    """
    A stub for the module's `time`.

    Time advances ONLY on sleep, so the number of samples a watch takes is decided by the
    test rather than by how fast this box happens to be.
    """

    def __init__( self, step=1.0 ):
        self.now    = 1000.0
        self.step   = step
        self.sleeps = []

    def time( self ):
        return self.now

    def sleep( self, seconds ):
        self.sleeps.append( seconds )
        self.now += self.step


@pytest.fixture
def clock( monkeypatch ):
    """Every watch-touching test depends on this; the real clock would hang the suite."""

    c = _Clock()
    monkeypatch.setattr( obs, "time", c )

    return c


def _args( out, max_seconds=10, dry_run=False, watch_only=None ):
    """The argparse Namespace `main` builds, for the helpers that receive it directly."""

    return argparse.Namespace( out=str( out ), max_seconds=max_seconds,
                               dry_run=dry_run, watch_only=watch_only )


# ── _http ─────────────────────────────────────────────────────────────────────────────────

def test_a_body_is_sent_as_json_and_a_token_becomes_a_bearer_header( monkeypatch ):
    """Reddens if the body stops being JSON-encoded or the token stops reaching the header."""

    seen = { }

    def fake_urlopen( req, timeout=None ):
        seen[ "url" ]     = req.full_url
        seen[ "method" ]  = req.method
        seen[ "data" ]    = req.data
        seen[ "headers" ] = dict( req.headers )
        seen[ "timeout" ] = timeout
        return _Resp( 200, '{"ok": true}' )

    monkeypatch.setattr( obs.urllib.request, "urlopen", fake_urlopen )

    status, payload = obs._http( "POST", "/some/path", token="tok123", body={ "a": 1 } )

    assert ( status, payload )       == ( 200, { "ok": True } )
    assert seen[ "url" ]             == "http://localhost:8000/some/path"
    assert seen[ "method" ]          == "POST"
    assert json.loads( seen[ "data" ] ) == { "a": 1 }
    assert seen[ "timeout" ]         == 30
    assert seen[ "headers" ][ "Authorization" ] == "Bearer tok123"
    assert seen[ "headers" ][ "Content-type" ]  == "application/json"


def test_no_body_and_no_token_sends_neither_data_nor_an_auth_header( monkeypatch ):
    """Reddens if an empty GET starts carrying a body or an unset token becomes 'Bearer None'."""

    seen = { }

    def fake_urlopen( req, timeout=None ):
        seen[ "data" ]    = req.data
        seen[ "headers" ] = dict( req.headers )
        return _Resp( 200, "{}" )

    monkeypatch.setattr( obs.urllib.request, "urlopen", fake_urlopen )

    obs._http( "GET", "/api/queue/pool-status" )

    assert seen[ "data" ] is None
    assert "Authorization" not in seen[ "headers" ]


def test_a_non_json_success_body_comes_back_as_raw_text( monkeypatch ):
    """Reddens if a plain-text 200 raises instead of being handed back for the caller to print."""

    monkeypatch.setattr( obs.urllib.request, "urlopen",
                         lambda req, timeout=None: _Resp( 200, "not json at all" ) )

    assert obs._http( "GET", "/x" ) == ( 200, "not json at all" )


def test_an_http_error_is_returned_as_its_code_and_json_body_not_raised( monkeypatch ):
    """Reddens if a 4xx starts propagating — the script prints the payload and returns 2."""

    def fake_urlopen( req, timeout=None ):
        raise obs.urllib.error.HTTPError( "http://x", 422, "unprocessable", { },
                                          io.BytesIO( b'{"detail": "string_type"}' ) )

    monkeypatch.setattr( obs.urllib.request, "urlopen", fake_urlopen )

    assert obs._http( "POST", "/x", body={ } ) == ( 422, { "detail": "string_type" } )


def test_an_http_error_with_a_non_json_body_comes_back_as_raw_text( monkeypatch ):
    """Reddens if an HTML error page raises JSONDecodeError instead of reaching the report."""

    def fake_urlopen( req, timeout=None ):
        raise obs.urllib.error.HTTPError( "http://x", 502, "bad gateway", { },
                                          io.BytesIO( b"<html>nginx</html>" ) )

    monkeypatch.setattr( obs.urllib.request, "urlopen", fake_urlopen )

    assert obs._http( "GET", "/x" ) == ( 502, "<html>nginx</html>" )


# ── login ─────────────────────────────────────────────────────────────────────────────────

def test_a_missing_email_names_both_credentials_rather_than_raising_a_key_error( monkeypatch ):
    """Reddens if the error stops naming the variables — that is the commonest start failure."""

    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )

    with pytest.raises( RuntimeError ) as e:
        obs.login()

    assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL"    in str( e.value )
    assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" in str( e.value )


def test_a_missing_password_is_refused_even_when_the_email_is_set( monkeypatch ):
    """Reddens if the check short-circuits on the email alone and lets a blank password through."""

    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", raising=False )

    with pytest.raises( RuntimeError ):
        obs.login()


def test_a_failed_login_raises_with_the_status_and_payload( monkeypatch ):
    """Reddens if a 401 returns a token-shaped None and the failure surfaces later as a 403."""

    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    monkeypatch.setattr( obs, "_http",
                         lambda *a, **k: ( 401, { "detail": "bad creds" } ) )

    with pytest.raises( RuntimeError ) as e:
        obs.login()

    assert "401"       in str( e.value )
    assert "bad creds" in str( e.value )


def test_a_successful_login_returns_the_access_token_and_posts_the_credentials( monkeypatch ):
    """Reddens if the token stops being read out of tokens.access_token."""

    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    seen = { }

    def fake_http( method, path, token=None, body=None, timeout=30 ):
        seen.update( method=method, path=path, body=body )
        return 200, { "tokens": { "access_token": "JWT-HERE" } }

    monkeypatch.setattr( obs, "_http", fake_http )

    assert obs.login() == "JWT-HERE"
    assert ( seen[ "method" ], seen[ "path" ] ) == ( "POST", "/auth/login" )
    assert seen[ "body" ] == { "email": "a@b.c", "password": "pw" }


# ── check_mount ───────────────────────────────────────────────────────────────────────────

def test_a_docker_that_will_not_run_is_could_not_verify_not_verified_wrong( monkeypatch ):
    """Reddens if a docker hiccup returns False — 'unknown' and 'wrong tree' must stay distinct."""

    def boom( *a, **k ):
        raise FileNotFoundError( "docker" )

    monkeypatch.setattr( obs.subprocess, "run", boom )

    ok, detail = obs.check_mount()

    assert ok is None
    assert "could not run docker inspect" in detail


def test_a_nonzero_docker_exit_is_also_could_not_verify_and_quotes_stderr( monkeypatch ):
    """Reddens if a missing container reads as a clean mount instead of an unknown one."""

    monkeypatch.setattr( obs.subprocess, "run",
                         lambda *a, **k: _Proc( returncode=1, stderr="  No such object  \n" ) )

    ok, detail = obs.check_mount()

    assert ok is None
    assert "No such object" in detail


def test_a_container_mounted_on_a_worktree_is_refused_and_the_mount_is_named( monkeypatch ):
    """Reddens if a worktree mount stops being caught — it measures the WRONG TREE silently."""

    stdout = ( "/mnt/DATA01/projects/lupin->/app\n"
               "\n"
               "/home/u/.claude/worktrees/wt-x->/app/src\n" )
    monkeypatch.setattr( obs.subprocess, "run",
                         lambda *a, **k: _Proc( returncode=0, stdout=stdout ) )

    ok, detail = obs.check_mount()

    assert ok is False
    assert "/home/u/.claude/worktrees/wt-x->/app/src" in detail


def test_a_bare_worktrees_path_also_counts_as_a_worktree_mount( monkeypatch ):
    """Reddens if only the .claude form is caught — worktrees live beside the repo here too."""

    monkeypatch.setattr( obs.subprocess, "run",
                         lambda *a, **k: _Proc( returncode=0,
                                                stdout="/srv/worktrees/wt-y->/app\n" ) )

    ok, _ = obs.check_mount()

    assert ok is False


def test_a_main_checkout_passes_and_counts_only_non_blank_mount_lines( monkeypatch ):
    """Reddens if the blank trailing line from the docker template is counted as a mount."""

    seen = { }

    def fake_run( cmd, capture_output=False, text=False, timeout=None ):
        seen[ "cmd" ] = cmd
        return _Proc( returncode=0, stdout="/a->/b\n/c->/d\n\n" )

    monkeypatch.setattr( obs.subprocess, "run", fake_run )

    ok, detail = obs.check_mount()

    assert ok is True
    assert "2 mounts" in detail
    assert seen[ "cmd" ][ :2 ]  == [ "docker", "inspect" ]
    assert seen[ "cmd" ][ -1 ]  == obs.TEST_CONTAINER


# ── check_prior_yaml ──────────────────────────────────────────────────────────────────────

def test_a_missing_yaml_directory_is_refused_and_the_path_is_printed( tmp_path, monkeypatch ):
    """Reddens if the absent directory reads as 'no YAML' without saying where it looked."""

    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )

    ok, detail = obs.check_prior_yaml()

    assert ok is False
    assert obs.YAML_DIR in detail


def test_an_empty_yaml_directory_is_refused( tmp_path, monkeypatch ):
    """Reddens if an existing but empty directory passes — the child could not spawn at all."""

    ( tmp_path / obs.YAML_DIR ).mkdir( parents=True )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )

    ok, detail = obs.check_prior_yaml()

    assert ok is False
    assert "no .yaml" in detail


def test_non_yaml_files_do_not_satisfy_the_precondition( tmp_path, monkeypatch ):
    """Reddens if the extension filter goes away and a stray .json passes as a prior render."""

    d = tmp_path / obs.YAML_DIR
    d.mkdir( parents=True )
    ( d / "notes.json" ).write_text( "{}" )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )

    assert obs.check_prior_yaml()[ 0 ] is False


def test_the_newest_yaml_is_the_one_named( tmp_path, monkeypatch ):
    """Reddens if 'newest' becomes 'first listed' — directory order is not modification order."""

    d = tmp_path / obs.YAML_DIR
    d.mkdir( parents=True )
    old = d / "aaa-old.yaml"
    new = d / "zzz-new.yaml"
    old.write_text( "a: 1" )
    new.write_text( "b: 2" )
    os.utime( old, ( 1_000_000, 1_000_000 ) )
    os.utime( new, ( 2_000_000, 2_000_000 ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )

    ok, detail = obs.check_prior_yaml()

    assert ok is True
    assert "2 found"     in detail
    assert "zzz-new.yaml" in detail


def test_an_unset_lupin_root_falls_back_to_the_current_directory( tmp_path, monkeypatch ):
    """Reddens if the fallback disappears and an unset LUPIN_ROOT becomes a TypeError."""

    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    monkeypatch.chdir( tmp_path )
    d = tmp_path / obs.YAML_DIR
    d.mkdir( parents=True )
    ( d / "one.yaml" ).write_text( "a: 1" )

    assert obs.check_prior_yaml() == ( True, "1 found, newest one.yaml" )


# ── check_idle ────────────────────────────────────────────────────────────────────────────

def test_a_pool_status_that_does_not_answer_200_is_not_idle( monkeypatch ):
    """Reddens if an unreachable pool reads as an empty box and the script submits into it."""

    monkeypatch.setattr( obs, "_http", lambda *a, **k: ( 503, "unavailable" ) )

    ok, payload = obs.check_idle( "tok" )

    assert ok is False
    assert payload[ "error" ]   == "pool-status HTTP 503"
    assert payload[ "payload" ] == "unavailable"


def test_a_monopolizer_already_holding_is_busy_even_with_no_agentic_jobs( monkeypatch ):
    """Reddens if the monopolize clause drops — a held box is the exact thing not to submit into."""

    pool = { "monopolize_inflight": True, "inflight_agentic_jobs": 0 }
    monkeypatch.setattr( obs, "_http", lambda *a, **k: ( 200, pool ) )

    assert obs.check_idle( "tok" ) == ( False, pool )


def test_an_inflight_agentic_job_is_busy_even_with_no_monopolizer( monkeypatch ):
    """Reddens if shared-pool work stops counting — pool-status is read, not the filtered queue."""

    pool = { "monopolize_inflight": False, "inflight_agentic_jobs": 2 }
    monkeypatch.setattr( obs, "_http", lambda *a, **k: ( 200, pool ) )

    assert obs.check_idle( "tok" ) == ( False, pool )


def test_an_empty_pool_is_idle_and_the_token_reaches_the_request( monkeypatch ):
    """Reddens if the JWT stops being passed — pool-status would answer 401, not 200."""

    seen = { }

    def fake_http( method, path, token=None, body=None, timeout=30 ):
        seen.update( method=method, path=path, token=token )
        return 200, { "monopolize_inflight": False, "inflight_agentic_jobs": 0 }

    monkeypatch.setattr( obs, "_http", fake_http )

    ok, _ = obs.check_idle( "tok" )

    assert ok is True
    assert ( seen[ "method" ], seen[ "path" ], seen[ "token" ] ) == \
           ( "GET", "/api/queue/pool-status", "tok" )


def test_a_pool_missing_the_keys_entirely_is_read_as_idle_not_as_a_crash( monkeypatch ):
    """Reddens if the defaults go away and an older pool-status shape raises instead of answering."""

    monkeypatch.setattr( obs, "_http", lambda *a, **k: ( 200, { } ) )

    assert obs.check_idle( "tok" ) == ( True, { } )


# ── _job_key ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "raw, expected", [
    ( "ts-21fd1f2b::50c73ba7-36dd-4eaf-a7e2-63256252c84f", "ts-21fd1f2b" ),
    ( "ts-21fd1f2b",                                       "ts-21fd1f2b" ),
    ( None,                                                None ),
    ( "",                                                  None ),
] )
def test_the_identity_half_is_taken_whichever_form_the_id_arrives_in( raw, expected ):
    """
    Reddens if the `::<user_uuid>` suffix stops being stripped.

    A plain `==` here would have reported NO QUALIFYING SAMPLE — a FAIL — while Gate B was
    admitting the child correctly, because the live id carries a suffix the endpoint's own
    field description does not mention.
    """

    assert obs._job_key( raw ) == expected


# ── qualifies ─────────────────────────────────────────────────────────────────────────────

def _sample( monopolize=True, inflight=1, mono_id="ts-abc::u-1" ):
    return { "monopolize_inflight": monopolize,
             "inflight_agentic_jobs": inflight,
             "monopolize_id": mono_id }


def test_all_three_clauses_true_in_one_sample_qualifies():
    """Reddens if the conjunction loosens — this is the whole observable of row 99b09840."""

    assert obs.qualifies( _sample(), "ts-abc" ) is True


def test_a_suffixed_monopolize_id_still_matches_an_unsuffixed_submit_id():
    """Reddens if the two ids are compared raw — the shapes differ and the run would read FAIL."""

    assert obs.qualifies( _sample( mono_id="ts-abc::50c7-3ba7" ), "ts-abc" ) is True


def test_somebody_elses_monopolizer_does_not_qualify():
    """
    Reddens if clause 3 weakens to 'some monopolizer is holding'.

    That is precisely the 2026-08-21 defect: a watcher reading monopolize_inflight off another
    session's E2E hold would print QUALIFYING SAMPLE against a job that was not its own.
    """

    assert obs.qualifies( _sample( mono_id="ts-someone-else::u-9" ), "ts-abc" ) is False


def test_no_monopolizer_does_not_qualify():
    """Reddens if clause 1 drops — a child running with nothing holding is not an admission."""

    assert obs.qualifies( _sample( monopolize=False ), "ts-abc" ) is False


def test_a_hold_with_no_child_running_does_not_qualify():
    """Reddens if clause 2 drops — a deferred child that runs after release looks like this."""

    assert obs.qualifies( _sample( inflight=0 ), "ts-abc" ) is False


def test_an_unknown_own_job_id_can_never_qualify():
    """Reddens if a missing submit id degrades to matching anything at all."""

    assert obs.qualifies( _sample( mono_id=None ), None ) is False


def test_a_sample_missing_the_keys_entirely_does_not_qualify():
    """Reddens if the defaults go away and a truncated pool payload raises mid-watch."""

    assert obs.qualifies( { }, "ts-abc" ) is False


# ── watch ─────────────────────────────────────────────────────────────────────────────────

def test_every_sample_is_written_as_one_flushed_json_line( tmp_path, monkeypatch, clock ):
    """
    Reddens if sampling stops being written per-sample.

    The 2026-08-21 attempt left no log anywhere, and that is half of why nobody could say what
    happened. The file is read back here while the loop's own writes are the only source.
    """

    monkeypatch.setattr( obs, "_http",
                         lambda *a, **k: ( 200, { "monopolize_inflight": False,
                                                  "inflight_agentic_jobs": 0 } ) )
    out = tmp_path / "gate-b"

    qualifying, n = obs.watch( "tok", "ts-abc", str( out ), max_seconds=3 )

    assert qualifying is None
    assert n == 3
    lines = ( out / "samples.jsonl" ).read_text().strip().splitlines()
    assert len( lines ) == 3
    first = json.loads( lines[ 0 ] )
    assert first[ "n" ]           == 1
    assert first[ "elapsed_s" ]   == 0.0
    assert first[ "http_status" ] == 200
    assert first[ "my_job_id" ]   == "ts-abc"
    assert first[ "qualifies" ]   is False
    assert json.loads( lines[ 2 ] )[ "elapsed_s" ] == 2.0
    assert clock.sleeps == [ obs.POLL_SECONDS ] * 3


def test_the_watch_stops_on_the_first_qualifying_sample( tmp_path, monkeypatch, clock ):
    """Reddens if the loop keeps polling past the answer — the row asks for ONE sample."""

    payloads = [
        ( 200, { "monopolize_inflight": False, "inflight_agentic_jobs": 0 } ),
        ( 200, { "monopolize_inflight": True,  "inflight_agentic_jobs": 1,
                 "monopolize_id": "ts-abc::u-1" } ),
    ]
    monkeypatch.setattr( obs, "_http", lambda *a, **k: payloads.pop( 0 ) )
    out = tmp_path / "gate-b"

    qualifying, n = obs.watch( "tok", "ts-abc", str( out ), max_seconds=100 )

    assert n == 2
    assert qualifying[ "n" ] == 2
    assert qualifying[ "qualifies" ] is True
    assert qualifying[ "sample" ][ "monopolize_id" ] == "ts-abc::u-1"
    assert len( clock.sleeps ) == 1          # no sleep after the qualifying sample
    assert len( ( out / "samples.jsonl" ).read_text().strip().splitlines() ) == 2


def test_a_non_200_sample_is_recorded_but_never_qualifies( tmp_path, monkeypatch, clock ):
    """
    Reddens if a failed poll is evaluated as a sample.

    `qualifies` would be handed an error string rather than a pool dict; recording it and
    marking it not-qualifying keeps the log complete without letting it decide the verdict.
    """

    monkeypatch.setattr( obs, "_http", lambda *a, **k: ( 500, "boom" ) )
    out = tmp_path / "gate-b"

    qualifying, n = obs.watch( "tok", "ts-abc", str( out ), max_seconds=1 )

    assert ( qualifying, n ) == ( None, 1 )
    rec = json.loads( ( out / "samples.jsonl" ).read_text().strip() )
    assert rec[ "http_status" ] == 500
    assert rec[ "sample" ]      == "boom"
    assert rec[ "qualifies" ]   is False


def test_a_zero_budget_takes_no_samples_and_still_creates_the_log( tmp_path, monkeypatch, clock ):
    """Reddens if the budget is checked after the first poll — a zero budget must poll nothing."""

    def never( *a, **k ):
        raise AssertionError( "polled despite a zero-second budget" )

    monkeypatch.setattr( obs, "_http", never )
    out = tmp_path / "gate-b"

    assert obs.watch( "tok", "ts-abc", str( out ), max_seconds=0 ) == ( None, 0 )
    assert ( out / "samples.jsonl" ).read_text() == ""


def test_an_existing_sample_log_is_appended_to_never_replaced( tmp_path, monkeypatch, clock ):
    """Reddens if the mode flips to 'w' — a resumed watch would erase what the killed run saw."""

    out = tmp_path / "gate-b"
    out.mkdir()
    ( out / "samples.jsonl" ).write_text( '{"n": 0, "from": "earlier run"}\n' )
    monkeypatch.setattr( obs, "_http", lambda *a, **k: ( 200, { } ) )

    obs.watch( "tok", "ts-abc", str( out ), max_seconds=1 )

    lines = ( out / "samples.jsonl" ).read_text().strip().splitlines()
    assert len( lines ) == 2
    assert json.loads( lines[ 0 ] )[ "from" ] == "earlier run"


# ── _report ───────────────────────────────────────────────────────────────────────────────

def test_a_qualifying_sample_is_a_pass_written_to_disk_and_printed_verbatim( tmp_path, capsys ):
    """Reddens if the sample is summarised instead of printed — the row asks for the sample."""

    qualifying = { "n": 4, "sample": { "monopolize_id": "ts-abc::u-1" }, "qualifies": True }

    rc = obs._report( _args( tmp_path ), "ts-abc", qualifying, 4 )
    out = capsys.readouterr().out

    assert rc == 0
    verdict = json.loads( ( tmp_path / "verdict.json" ).read_text() )
    assert verdict[ "verdict" ]           == "PASS"
    assert verdict[ "row" ]               == "99b09840"
    assert verdict[ "my_job_id" ]         == "ts-abc"
    assert verdict[ "samples_taken" ]     == 4
    assert verdict[ "qualifying_sample" ] == qualifying
    assert verdict[ "samples_path" ]      == os.path.join( str( tmp_path ), "samples.jsonl" )
    assert "ts-abc::u-1" in out


def test_no_qualifying_sample_is_a_fail_and_says_so_rather_than_inconclusive( tmp_path, capsys ):
    """
    Reddens if the empty case starts exiting 0 or calling itself inconclusive.

    Per row 99b09840 a deferred child that runs after the hold releases looks identical from
    outside and is the exact failure this script exists to detect.
    """

    rc = obs._report( _args( tmp_path ), "ts-abc", None, 900 )
    out = capsys.readouterr().out

    assert rc == 1
    assert json.loads( ( tmp_path / "verdict.json" ).read_text() )[ "verdict" ] == "FAIL"
    assert "NO QUALIFYING SAMPLE" in out
    assert "FAIL, not inconclusive" in out


# ── main ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def wired( monkeypatch, tmp_path ):
    """
    `main` with every outward call stopped at the module boundary.

    Returns a dict the test mutates to choose the path; nothing here can reach a server, a
    container, or the real clock.
    """

    state = {
        "yaml"   : ( True, "1 found, newest x.yaml" ),
        "mount"  : ( True, "3 mounts, none under a worktree path" ),
        "idle"   : ( True, { "monopolize_inflight": False, "inflight_agentic_jobs": 0 } ),
        "submit" : ( 200, { "job_id": "ts-abc" } ),
        "watch"  : ( None, 7 ),
        "submits": [ ],
        "watches": [ ],
    }

    def fake_http( method, path, token=None, body=None, timeout=30 ):
        state[ "submits" ].append( ( method, path, token, body ) )
        return state[ "submit" ]

    def fake_watch( token, my_job_id, out_dir, max_seconds ):
        state[ "watches" ].append( ( token, my_job_id, out_dir, max_seconds ) )
        return state[ "watch" ]

    monkeypatch.setattr( obs, "check_prior_yaml", lambda: state[ "yaml" ] )
    monkeypatch.setattr( obs, "check_mount",      lambda: state[ "mount" ] )
    monkeypatch.setattr( obs, "login",            lambda: "JWT" )
    monkeypatch.setattr( obs, "check_idle",       lambda token: state[ "idle" ] )
    monkeypatch.setattr( obs, "_http",            fake_http )
    monkeypatch.setattr( obs, "watch",            fake_watch )

    return state


def _argv( monkeypatch, tmp_path, *extra ):
    monkeypatch.setattr( obs.sys, "argv",
                         [ "observe_gate_b_admission.py", "--out", str( tmp_path ), *extra ] )


def test_a_missing_prior_yaml_refuses_before_anything_is_submitted( wired, monkeypatch,
                                                                    tmp_path, capsys ):
    """Reddens if the substitution's precondition stops being checked before submit."""

    wired[ "yaml" ] = ( False, "no .yaml in /x" )
    _argv( monkeypatch, tmp_path )

    assert obs.main() == 2
    assert "REFUSING" in capsys.readouterr().out
    assert wired[ "submits" ] == [ ]


def test_a_worktree_mount_refuses_rather_than_measuring_the_wrong_tree( wired, monkeypatch,
                                                                       tmp_path, capsys ):
    """Reddens if a worktree mount is allowed through — it returns a plausible wrong number."""

    wired[ "mount" ] = ( False, "container is mounted on a WORKTREE: /x" )
    _argv( monkeypatch, tmp_path )

    assert obs.main() == 2
    assert "WRONG TREE" in capsys.readouterr().out
    assert wired[ "submits" ] == [ ]


def test_an_unverifiable_mount_does_not_refuse_but_fails_a_dry_run( wired, monkeypatch,
                                                                    tmp_path ):
    """
    Reddens if `is False` loosens to a plain falsy test.

    'could not verify' (None) must keep running — it is not proof of a worktree — while still
    leaving a dry run short of a clean bill of health.
    """

    wired[ "mount" ] = ( None, "could not run docker inspect: docker" )
    _argv( monkeypatch, tmp_path, "--dry-run" )

    assert obs.main() == 1
    assert wired[ "submits" ] == [ ]


def test_a_dry_run_on_a_clean_idle_box_passes_and_submits_nothing( wired, monkeypatch,
                                                                   tmp_path, capsys ):
    """Reddens if --dry-run ever reaches the submit — it is the no-side-effect door."""

    _argv( monkeypatch, tmp_path, "--dry-run" )

    assert obs.main() == 0
    assert "nothing submitted" in capsys.readouterr().out
    assert ( wired[ "submits" ], wired[ "watches" ] ) == ( [ ], [ ] )


def test_a_dry_run_on_a_busy_box_reports_one_not_zero( wired, monkeypatch, tmp_path ):
    """Reddens if a dry run stops distinguishing a free box from an occupied one."""

    wired[ "idle" ] = ( False, { "monopolize_inflight": True } )
    _argv( monkeypatch, tmp_path, "--dry-run" )

    assert obs.main() == 1


def test_a_busy_box_refuses_rather_than_queueing_behind_a_live_gate( wired, monkeypatch,
                                                                     tmp_path, capsys ):
    """Reddens if the script queues behind somebody else's hold — a different experiment."""

    wired[ "idle" ] = ( False, { "monopolize_inflight": True } )
    _argv( monkeypatch, tmp_path )

    assert obs.main() == 2
    assert "not free" in capsys.readouterr().out
    assert wired[ "submits" ] == [ ]


def test_watch_only_resumes_an_existing_job_without_submitting( wired, monkeypatch,
                                                                tmp_path, capsys ):
    """
    Reddens if resuming submits again.

    A second submit would start a SECOND monopolizer and the watcher would then be measuring
    the wrong one — which is the reason this flag exists.
    """

    _argv( monkeypatch, tmp_path, "--watch-only", "ts-earlier" )

    assert obs.main() == 1                                    # no qualifying sample yet
    assert wired[ "submits" ] == [ ]
    assert wired[ "watches" ] == [ ( "JWT", "ts-earlier", str( tmp_path ), 1800 ) ]
    assert "NOT submitting" in capsys.readouterr().out


def test_a_rejected_submit_stops_the_run_and_prints_the_status( wired, monkeypatch,
                                                                tmp_path, capsys ):
    """Reddens if a 422 falls through to a watch that can only ever report FAIL."""

    wired[ "submit" ] = ( 422, { "detail": "string_type" } )
    _argv( monkeypatch, tmp_path )

    assert obs.main() == 2
    assert "submit failed: HTTP 422" in capsys.readouterr().out
    assert wired[ "watches" ] == [ ]


def test_the_submit_body_sends_strings_not_lists_and_leaves_auto_fix_off( wired, monkeypatch,
                                                                          tmp_path ):
    """
    Reddens if either field becomes a list (the endpoint answers 422) or auto-fix turns on.

    auto_fix_on_failure stays False so a false red cannot arm the TFE treadmill (bug 67473d91).
    """

    _argv( monkeypatch, tmp_path )
    obs.main()

    method, path, token, body = wired[ "submits" ][ 0 ]
    assert ( method, path, token ) == ( "POST", "/api/test-suite/submit", "JWT" )
    assert body[ "test_types" ]          == "smoke"
    assert body[ "pytest_args" ]         == f"{obs.TARGET_SUITE} --auto-proxy"
    assert body[ "auto_fix_on_failure" ] is False


def test_a_qualifying_watch_after_submit_is_a_pass( wired, monkeypatch, tmp_path, capsys ):
    """Reddens if the submit path stops handing its job id to the watch, or to the verdict."""

    wired[ "watch" ] = ( { "n": 3, "qualifies": True, "sample": { "x": 1 } }, 3 )
    _argv( monkeypatch, tmp_path, "--max-seconds", "60" )

    assert obs.main() == 0
    assert wired[ "watches" ] == [ ( "JWT", "ts-abc", str( tmp_path ), 60 ) ]
    verdict = json.loads( ( tmp_path / "verdict.json" ).read_text() )
    assert ( verdict[ "verdict" ], verdict[ "my_job_id" ] ) == ( "PASS", "ts-abc" )


def test_a_submit_that_answers_id_hash_instead_of_job_id_is_still_followed( wired, monkeypatch,
                                                                            tmp_path ):
    """Reddens if the id_hash fallback goes away — the watch would compare against None."""

    wired[ "submit" ] = ( 201, { "id_hash": "ts-fallback" } )
    _argv( monkeypatch, tmp_path )
    obs.main()

    assert wired[ "watches" ][ 0 ][ 1 ] == "ts-fallback"


# ── module surface ────────────────────────────────────────────────────────────────────────

def test_the_script_points_at_the_test_venue_and_the_render_only_sibling():
    """
    Reddens if the venue or the suite drifts.

    The substitution of the render-only sibling for the live smoke is deliberate and approved
    (Mr Radio, 2026-08-24); pinning it here means a silent swap back to the LLM-spending file
    cannot pass unnoticed.
    """

    assert obs.BASE_URL       == "http://localhost:8000"
    assert obs.TEST_CONTAINER == "lupin-rest-test"
    assert obs.TARGET_SUITE   == "src/tests/smoke/test_presentation_render_only_smoke.py"
    assert obs.POLL_SECONDS   == 2.0
