"""
The test-suite job issues, exports and revokes the per-run lineage token.

With the INI switch on, a real sweep stores a token bound to its own id.
Every suite subprocess gets the value through one environment variable.
The token is revoked on every exit. With the switch off, nothing is stored or exported.

Doubles are reused from test_job.py: the voice seam, the fake process and the job builder.
Venue: :7999 (unit, no subprocess is spawned, no server).
"""
import asyncio
from pathlib import Path

import pytest

import cosa.agents.test_suite.job as job_mod
import cosa.utils.util as cu
from cosa.rest import suite_run_token as srt
from cosa.agents.test_suite.job import SUITE_TIMEOUTS_SECONDS, TestSuiteJob as TSJob
from cosa.tests.unit.agents.test_suite.test_job import (   # noqa: F401  (the fixtures are used by name)
    _FakeProcess, _isolate_artifact_root, _make_job, _passing_result, _patch_config_mgr, no_real_log, patched_voice,
)


@pytest.fixture( autouse=True )
def _empty_store():
    srt.clear()
    yield
    srt.clear()


@pytest.fixture
def switch( monkeypatch ):
    """The INI switch as a mutable cell, and a record of every issue call."""
    state = { "on": True, "issued": [ ] }
    real  = srt.issue
    def issue( parent_id, ttl_seconds, now=None ):
        state[ "issued" ].append( ( parent_id, ttl_seconds ) )
        return real( parent_id, ttl_seconds, now )
    monkeypatch.setattr( srt, "token_enabled", lambda: state[ "on" ] )
    monkeypatch.setattr( srt, "issue", issue )
    return state


def _sweep( monkeypatch, tmp_path, job, during=None, result=None ):
    """Drive _execute with a stubbed suite runner; `during` runs inside each suite."""
    monkeypatch.setattr( job_mod.cu, "get_project_root", lambda: str( tmp_path ) )
    def run_suite( suite_type, project_root ):
        if during is not None: during( job, suite_type )
        return result or _passing_result()
    monkeypatch.setattr( job, "_run_suite", run_suite )
    return asyncio.run( job._execute() )


def _is_live( job, token ):
    return srt.check( job.id_hash, token, lambda: job.id_hash ) == ( True, None )


# ── issued once per sweep, bound to the job, live during every suite ────────

def test_a_sweep_issues_one_token_for_its_own_id_and_it_is_live_during_every_suite( monkeypatch, tmp_path, patched_voice, switch ):
    job  = _make_job( test_types=[ "unit", "e2e" ] )
    seen = [ ]
    _sweep( monkeypatch, tmp_path, job, during=lambda j, suite: seen.append( ( suite, j._suite_token, _is_live( j, j._suite_token ) ) ) )
    assert [ s for s, _, _ in seen ] == [ "unit", "e2e" ]
    assert all( live for _, _, live in seen )
    assert len( { token for _, token, _ in seen } ) == 1, "one token for the whole sweep, so a seam does not drop it"
    assert [ parent for parent, _ in switch[ "issued" ] ] == [ job.id_hash ]


def test_the_lifetime_is_the_sum_of_the_suite_budgets_plus_the_slack( monkeypatch, tmp_path, patched_voice, switch ):
    job = _make_job( test_types=[ "unit", "e2e" ] )
    _sweep( monkeypatch, tmp_path, job )
    expected = SUITE_TIMEOUTS_SECONDS[ "unit" ] + SUITE_TIMEOUTS_SECONDS[ "e2e" ] + srt.EXPIRY_SLACK_SECONDS
    assert switch[ "issued" ] == [ ( job.id_hash, expected ) ]


def test_an_unlisted_suite_counts_at_the_default_budget( monkeypatch ):
    monkeypatch.setattr( srt, "token_enabled", lambda: True )
    job = _make_job( test_types=[ "unit" ] )
    token = job._issue_suite_token( [ "no-such-suite" ] )
    assert token is not None and _is_live( job, token )
    ttl = srt._store[ job.id_hash ][ 1 ] - srt.time.monotonic()
    assert ttl == pytest.approx( job_mod.SUITE_TIMEOUT_DEFAULT_SECONDS + srt.EXPIRY_SLACK_SECONDS, abs=5 )


def test_the_token_is_revoked_when_the_sweep_ends( monkeypatch, tmp_path, patched_voice, switch ):
    job   = _make_job( test_types=[ "unit" ] )
    holds = [ ]
    _sweep( monkeypatch, tmp_path, job, during=lambda j, s: holds.append( j._suite_token ) )
    assert holds[ 0 ] is not None
    assert not _is_live( job, holds[ 0 ] )
    assert job._suite_token is None and job.id_hash not in srt._store


def test_the_token_is_revoked_when_a_suite_raises( monkeypatch, tmp_path, patched_voice, switch ):
    job = _make_job( test_types=[ "unit", "e2e" ] )
    def boom( j, suite ): raise RuntimeError( "suite blew up" )
    with pytest.raises( RuntimeError ):
        _sweep( monkeypatch, tmp_path, job, during=boom )
    assert job.id_hash not in srt._store and job._suite_token is None


def test_the_token_is_revoked_when_the_sweep_is_cancelled( monkeypatch, tmp_path, patched_voice, switch ):
    job = _make_job( test_types=[ "unit" ] )
    job._cancel_requested = True
    _sweep( monkeypatch, tmp_path, job )
    assert switch[ "issued" ] != [ ], "issued before the cancel check, so the revoke has something to remove"
    assert job.id_hash not in srt._store and job._suite_token is None


def test_a_preflight_that_refuses_the_sweep_issues_nothing( monkeypatch, tmp_path, patched_voice, switch ):
    job = _make_job( test_types=[ "unit" ] )
    def refuse(): raise RuntimeError( "non-test job inflight" )
    monkeypatch.setattr( job, "_preflight_assert_exclusive_test_db", refuse )
    with pytest.raises( RuntimeError ):
        _sweep( monkeypatch, tmp_path, job )
    assert switch[ "issued" ] == [ ] and job.id_hash not in srt._store


# ── the switch is off: nothing is stored and nothing is injected ────────────

def test_with_the_switch_off_nothing_is_issued_and_no_child_sees_the_variable( monkeypatch, tmp_path, patched_voice, switch ):
    switch[ "on" ] = False
    job = _make_job( test_types=[ "unit" ] )
    seen = [ ]
    _sweep( monkeypatch, tmp_path, job, during=lambda j, s: seen.append( j._suite_token_env() ) )
    assert seen == [ { } ] and switch[ "issued" ] == [ ] and srt._store == { }


def test_a_dry_run_issues_nothing( monkeypatch, tmp_path, patched_voice, switch ):
    job = _make_job( test_types=[ "unit" ], dry_run=True )
    asyncio.run( job._execute() )
    assert switch[ "issued" ] == [ ]


def test_a_failure_to_issue_is_printed_and_the_sweep_still_runs( monkeypatch, tmp_path, patched_voice, switch, capsys ):
    def broken(): raise OSError( "ini unreadable" )
    monkeypatch.setattr( srt, "token_enabled", broken )
    job  = _make_job( test_types=[ "unit" ] )
    seen = [ ]
    summary = _sweep( monkeypatch, tmp_path, job, during=lambda j, s: seen.append( j._suite_token ) )
    assert "ALL PASSED" in summary and seen == [ None ]
    assert "suite token not issued (OSError)" in capsys.readouterr().out


# ── what the subprocess sees ────────────────────────────────────────────────

def _env_of_the_child( monkeypatch, job ):
    """The env dict _run_suite hands to Popen."""
    _patch_config_mgr( monkeypatch )
    monkeypatch.setattr( job_mod.os.path, "exists", lambda p: True )
    captured = { }
    def popen( cmd, **kwargs ):
        captured.update( kwargs )
        return _FakeProcess( lines=[ "x\n" ], returncode=0 )
    monkeypatch.setattr( job_mod.subprocess, "Popen", popen )
    job._run_suite( "unit", "/proj" )
    return captured[ "env" ]


def test_the_child_gets_the_token_under_the_pinned_name( monkeypatch, no_real_log ):
    job = _make_job( test_types=[ "unit" ] )
    job._suite_token = "the-issued-value"
    assert _env_of_the_child( monkeypatch, job )[ "LUPIN_TEST_MONOPOLIZE_PARENT_TOKEN" ] == "the-issued-value"


def test_a_caller_cannot_replace_the_token_the_child_sees( monkeypatch, no_real_log ):
    job = _make_job( test_types=[ "unit" ] )
    job._suite_token = "the-issued-value"
    job.env_vars     = { srt.TOKEN_ENV_NAME: "caller-chosen" }       # past the constructor filter, on purpose
    assert _env_of_the_child( monkeypatch, job )[ srt.TOKEN_ENV_NAME ] == "the-issued-value"


def test_with_no_token_the_child_env_has_no_such_variable( monkeypatch, no_real_log ):
    monkeypatch.delenv( srt.TOKEN_ENV_NAME, raising=False )
    job = _make_job( test_types=[ "unit" ] )
    assert srt.TOKEN_ENV_NAME not in _env_of_the_child( monkeypatch, job )


def test_the_constructor_drops_a_callers_token_variable_and_keeps_the_others( capsys ):
    job = _make_job( env_vars={ srt.TOKEN_ENV_NAME: "caller-chosen", "LUPIN_TEST_OTHER": "1" } )
    assert job.env_vars == { "LUPIN_TEST_OTHER": "1" }
    assert srt.TOKEN_ENV_NAME in capsys.readouterr().out


def test_the_injection_sits_after_the_callers_env_vars_in_the_source():
    source = ( Path( cu.get_project_root() ) / "src/cosa/agents/test_suite/job.py" ).read_text( encoding="utf-8" )
    assert source.count( "**self._suite_token_env()" ) == 1
    assert source.index( "**self.env_vars" ) < source.index( "**self._suite_token_env()" )


def test_the_variable_name_the_job_injects_is_the_one_the_redaction_layer_hunts():
    from cosa.utils.secret_redaction import credential_env_values
    job = _make_job()
    job._suite_token = "a-value-long-enough-to-be-hunted-by-redaction"
    assert job._suite_token in credential_env_values( job._suite_token_env() )
