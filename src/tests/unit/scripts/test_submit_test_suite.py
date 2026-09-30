"""
scripts/submit-test-suite.py posts through /api/v2/submit (row a3c59f2d) and reads the reply,
not the HTTP code: v2 answers a refused submit with HTTP 200 and status "failed".
"""

import importlib.util
import os
import types

import pytest

_SCRIPT = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "submit-test-suite.py" )
_spec   = importlib.util.spec_from_file_location( "submit_test_suite", _SCRIPT )
sts     = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( sts )


class _Resp:
    def __init__( self, code, body, text=None ):
        self.status_code = code
        self._body       = body
        self.text        = text if text is not None else str( body )

    def json( self ):
        if self._body is None: raise ValueError( "not json" )
        return self._body


@pytest.fixture
def wired( monkeypatch ):
    state = { "posts": [ ], "submit": _Resp( 200, { "status": "waiting", "job_id": "ts-1", "queue_position": 2 } ) }

    def fake_post( url, headers=None, json=None, timeout=None ):
        state[ "posts" ].append( ( url, json ) )
        if url.endswith( "/auth/login" ): return _Resp( 200, { "tokens": { "access_token": "JWT" } } )
        return state[ "submit" ]

    monkeypatch.setattr( sts.requests, "post", fake_post )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "e" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "p" )
    return state


def test_it_posts_the_v2_test_suite_body_and_exits_zero_on_waiting( wired, capsys ):
    assert sts.main( [ "--test-types", "e2e_b", "--pytest-args", "-k x", "--scheduled-at", "T" ] ) == 0
    url, body = wired[ "posts" ][ -1 ]
    assert url.endswith( "/api/v2/submit" )
    assert body[ "command" ] == "agent router go to test suite" and body[ "scheduled_at" ] == "T"
    assert body[ "args" ] == { "test_types": "e2e_b", "dry_run": False, "pytest_args": "-k x", "auto_fix_on_failure": False }
    assert "queue_position=2" in capsys.readouterr().out


def test_auto_fix_and_dry_run_flags_reach_the_args( wired ):
    sts.main( [ "--test-types", "unit", "--auto-fix", "--dry-run" ] )
    args = wired[ "posts" ][ -1 ][ 1 ][ "args" ]
    assert args[ "auto_fix_on_failure" ] is True and args[ "dry_run" ] is True


def test_a_200_refusal_exits_three_and_says_why( wired, capsys ):
    wired[ "submit" ] = _Resp( 200, { "status": "failed", "error": "unknown test suite(s) ['e2e_ui']" } )
    assert sts.main( [ "--test-types", "e2e_ui" ] ) == 3
    assert "e2e_ui" in capsys.readouterr().err


def test_a_non_json_answer_exits_three( wired ):
    wired[ "submit" ] = _Resp( 502, None, text="bad gateway" )
    assert sts.main( [ "--test-types", "unit" ] ) == 3


def test_missing_credentials_exit_one( monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )
    assert sts.main( [ "--test-types", "unit" ] ) == 1


def test_a_failed_login_exits_two( monkeypatch, wired ):
    monkeypatch.setattr( sts.requests, "post", lambda url, **kw: _Resp( 401, { }, text="no" ) )
    assert sts.main( [ "--test-types", "unit" ] ) == 2
