"""
Wiring guards for `src/scripts/capture-bounce-resubmit.py`.

The sibling file covers the capture and resubmit logic against a fake client.
These cases cover what sits around it.
The HTTP client, the bootstrap path, the report lines for a failed or lossless run,
the host bouncer, and the command-line entry.
"""

import importlib.util
import io
import json
import os
import runpy
import subprocess
import sys

import pytest

_SCRIPT = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "capture-bounce-resubmit.py" )


def _load():
    spec = importlib.util.spec_from_file_location( "capture_bounce_resubmit_wiring", _SCRIPT )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


@pytest.fixture
def cbr():
    return _load()


class _Reply:
    """What urlopen hands back: a context manager with a readable body."""
    def __init__( self, payload ): self._body = json.dumps( payload ).encode()
    def __enter__( self ): return self
    def __exit__( self, *a ): return False
    def read( self ): return self._body


@pytest.fixture
def wire( monkeypatch, cbr ):
    """Stand in for urlopen; `seen` holds the last request and `reply` is what comes back."""
    seen = { "reply": { "ok": True } }
    def fake_urlopen( req, timeout=None ):
        seen.update( url=req.full_url, method=req.get_method(), data=req.data,
                     headers=dict( req.header_items() ), timeout=timeout )
        return _Reply( seen[ "reply" ] )
    monkeypatch.setattr( cbr.urllib.request, "urlopen", fake_urlopen )
    return seen


def test_without_lupin_root_the_script_finds_its_own_tree( monkeypatch ):
    """The bootstrap falls back to two directories above the script, and puts src on the path."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    monkeypatch.setattr( sys, "path", [ p for p in sys.path if not p.endswith( os.sep + "src" ) ] )
    ns = runpy.run_path( _SCRIPT, run_name="not_main" )
    expected = os.path.abspath( os.path.join( os.path.dirname( _SCRIPT ), "..", ".." ) )
    assert os.path.abspath( ns[ "_lupin_root" ] ) == expected
    assert sys.path[ 0 ] == os.path.join( ns[ "_lupin_root" ], "src" )


def test_a_request_carries_json_and_the_token_when_there_is_one( cbr, wire ):
    client = cbr.QueueClient( "http://host:8000/", token="tok", timeout=3 )
    wire[ "reply" ] = { "x": 1 }
    assert client._request( "POST", "/p", body={ "a": 1 } ) == { "x": 1 }
    assert wire[ "url" ] == "http://host:8000/p"
    assert json.loads( wire[ "data" ] ) == { "a": 1 }
    assert wire[ "headers" ][ "Authorization" ] == "Bearer tok"
    assert wire[ "headers" ][ "Content-type" ] == "application/json"
    assert wire[ "timeout" ] == 3


def test_a_request_without_a_body_or_with_auth_off_sends_neither( cbr, wire ):
    client = cbr.QueueClient( "http://host", token="tok" )
    client._request( "GET", "/p", auth=False )
    assert wire[ "data" ] is None
    assert "Authorization" not in wire[ "headers" ]


def test_login_stores_and_returns_the_access_token( cbr, wire ):
    wire[ "reply" ] = { "tokens": { "access_token": "abc" } }
    client = cbr.QueueClient( "http://host" )
    assert client.login( "e@x", "pw" ) == "abc"
    assert client.token == "abc"
    assert wire[ "url" ].endswith( "/auth/login" )
    assert "Authorization" not in wire[ "headers" ]
    assert json.loads( wire[ "data" ] ) == { "email": "e@x", "password": "pw" }


def test_fetch_todo_returns_the_metadata_list_or_empty( cbr, wire ):
    client = cbr.QueueClient( "http://host" )
    wire[ "reply" ] = { "todo_jobs_metadata": [ { "job_id": "a" } ] }
    assert client.fetch_todo() == [ { "job_id": "a" } ]
    wire[ "reply" ] = { }
    assert client.fetch_todo() == [ ]


def _report( cbr, tmp_path, records ):
    return {
        "apply": True, "capture_path": str( tmp_path / "c.json" ), "total": len( records ),
        "resubmittable": 0, "moved": 0, "failed": 1, "unrecoverable": 0,
        "fidelity_loss_jobs": 0, "records": records,
    }


def test_a_failed_resubmit_shows_its_error_and_no_fidelity_note_when_nothing_was_lost( cbr, tmp_path ):
    rec = { "resubmit_status": "failed", "resubmit_error": "boom", "question_text": "[Tests] unit",
            "owner_email": None, "fidelity_loss": [ ], "resubmittable": True }
    text = cbr.format_report( _report( cbr, tmp_path, [ rec ] ) )
    assert "! resubmit error: boom" in text
    assert "(owner=?)" in text
    assert "NOTE:" not in text and "FIDELITY-LOSS" not in text


def test_the_host_bouncer_runs_the_refresh_script_and_raises_on_failure( cbr, monkeypatch ):
    calls = [ ]
    monkeypatch.setattr( cbr.subprocess, "run", lambda cmd, check=False: calls.append( ( cmd, check ) ) )
    cbr._make_host_bouncer()()
    cbr._make_host_bouncer( quiet=True )()
    assert calls[ 0 ][ 0 ][ 0 ].endswith( "refresh-test-server.sh" ) and len( calls[ 0 ][ 0 ] ) == 1
    assert calls[ 1 ][ 0 ][ 1: ] == [ "--quiet" ]
    assert all( check is True for _, check in calls )


def test_the_default_capture_path_is_per_process( cbr ):
    assert cbr._default_capture_path() == f"/tmp/cbr-capture-{os.getpid()}.json"


def test_main_without_credentials_exits_two_and_says_which_variables( cbr, monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    assert cbr.main( [ ] ) == 2
    assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" in capsys.readouterr().err


class _FakeClient:
    def __init__( self, base_url ): self.base_url = base_url; self.logged_in = None
    def login( self, email, password ): self.logged_in = ( email, password )


@pytest.fixture
def cli( cbr, monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "e@x" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    seen = { }
    monkeypatch.setattr( cbr, "QueueClient", _FakeClient )
    monkeypatch.setattr( cbr, "_make_host_bouncer", lambda quiet=False: seen.update( quiet=quiet ) or ( lambda: None ) )
    def fake_run( client, bouncer, capture_path, apply ):
        seen.update( client=client, capture_path=capture_path, apply=apply )
        if seen.get( "bounce_fails" ): raise subprocess.CalledProcessError( 1, "refresh" )
        return { "sentinel": True }
    monkeypatch.setattr( cbr, "run_capture_bounce_resubmit", fake_run )
    monkeypatch.setattr( cbr, "format_report", lambda report: f"REPORT {report}" )
    return seen


def test_main_logs_in_runs_a_dry_run_by_default_and_prints_the_report( cbr, cli, capsys, tmp_path ):
    assert cbr.main( [ "--base-url", "http://b:1", "--capture-file", str( tmp_path / "c.json" ) ] ) == 0
    assert cli[ "client" ].base_url == "http://b:1"
    assert cli[ "client" ].logged_in == ( "e@x", "pw" )
    assert cli[ "apply" ] is False and cli[ "quiet" ] is False
    assert cli[ "capture_path" ] == str( tmp_path / "c.json" )
    assert capsys.readouterr().out.strip() == "REPORT {'sentinel': True}"


def test_main_apply_and_quiet_reach_the_run_and_the_bouncer( cbr, cli ):
    assert cbr.main( [ "--apply", "--quiet" ] ) == 0
    assert cli[ "apply" ] is True and cli[ "quiet" ] is True
    assert cli[ "capture_path" ] == cbr._default_capture_path()


def test_a_failed_bounce_exits_one_and_names_the_capture_file( cbr, cli, capsys ):
    cli[ "bounce_fails" ] = True
    assert cbr.main( [ "--apply", "--capture-file", "/tmp/keep-me.json" ] ) == 1
    err = capsys.readouterr().err
    assert "bounce failed" in err and "/tmp/keep-me.json" in err and "no resubmit performed" in err
