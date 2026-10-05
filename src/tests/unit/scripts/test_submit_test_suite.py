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


# --env (row 4cbd4858): the scheduled full eval run raises the per-command sample this way.

def test_env_pairs_reach_the_args_as_env_vars( wired ):
    assert sts.main( [ "--test-types", "integration", "--env", "LUPIN_TEST_V2_EVAL_LIMIT=20",
                       "--env", "LUPIN_TEST_INTEGRATION_FILE_TIMEOUT_MINUTES=40" ] ) == 0
    args = wired[ "posts" ][ -1 ][ 1 ][ "args" ]
    assert args[ "env_vars" ] == { "LUPIN_TEST_V2_EVAL_LIMIT": "20", "LUPIN_TEST_INTEGRATION_FILE_TIMEOUT_MINUTES": "40" }


def test_without_env_the_field_is_absent( wired ):
    sts.main( [ "--test-types", "unit" ] )
    assert "env_vars" not in wired[ "posts" ][ -1 ][ 1 ][ "args" ]


def test_env_splits_on_the_first_equals_only_keeps_an_empty_value_and_lets_the_last_pair_win():
    assert sts.parse_env( [ "LUPIN_TEST_A=x=y", "LUPIN_TEST_B=", "LUPIN_TEST_A=z" ] ) == { "LUPIN_TEST_A": "z", "LUPIN_TEST_B": "" }
    assert sts.parse_env( [] ) == {}


@pytest.mark.parametrize( "pair, says", [
    ( "LUPIN_TEST_X",      "takes KEY=VALUE" ),
    ( "=5",                "takes KEY=VALUE" ),
    ( "PATH=/tmp",         "would drop this one" ),
    ( "lupin_test_x=1",    "would drop this one" ),
    ( "MY_LUPIN_TEST_X=1", "would drop this one" ),
] )
def test_a_bad_env_pair_exits_one_before_anything_is_sent( wired, capsys, pair, says ):
    assert sts.main( [ "--test-types", "unit", "--env", pair ] ) == 1
    assert wired[ "posts" ] == [ ], "nothing may be posted, not even the login"
    assert says in capsys.readouterr().err


def test_every_prefix_the_suite_job_allows_is_accepted_here():
    # The script asks the job's own filter, so a prefix added there is accepted here with no edit.
    from cosa.agents.test_suite.job import TestSuiteJob
    prefixes = TestSuiteJob._ENV_VAR_ALLOWED_PREFIXES
    assert len( prefixes ) >= 3
    for prefix in prefixes:
        assert sts.parse_env( [ f"{prefix}X=1" ] ) == { f"{prefix}X": "1" }


def test_a_name_the_job_filter_stops_allowing_is_refused_here_too( monkeypatch ):
    from cosa.agents.test_suite.job import TestSuiteJob
    monkeypatch.setattr( TestSuiteJob, "_ENV_VAR_ALLOWED_PREFIXES", ( "TFE_", ) )
    assert sts.parse_env( [ "TFE_X=1" ] ) == { "TFE_X": "1" }
    with pytest.raises( ValueError ):
        sts.parse_env( [ "LUPIN_TEST_X=1" ] )
