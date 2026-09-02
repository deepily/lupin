"""
The bounded-ClaudeCodeJob billing probe, covered without submitting a job or sleeping a minute.

`src/scripts/probe_cc_bounded_billing.py` — 141 statements + 40 branches at zero, the LARGEST
of the 22 stragglers. Ruled COVER by Rick on row `2b2f426e`, against the alternatives of a
whole-file pragma or dropping it from the frame; both of those move the coverage number MORE
than testing it does, which is the trade the row had already rejected by name for `delete`.

🔴 THREE HAZARDS, each patched at the module attribute so a miss raises instead of passing quietly:

1. `_run_one` and `_auth` POST to a live server — `SUBMIT_ENDPOINT` really submits a
   ClaudeCodeJob and the whole point of this script is that jobs cost money. Unpatched, a test
   run would queue real work against whatever `LUPIN_API_URL` resolves to.
2. `main()` sleeps `WAIT_BETWEEN_JOBS_S` (60s) between every job, eleven times. Unpatched that
   is eleven minutes of wall clock inside a unit suite.
3. `main()` writes `/tmp/{PROBE_RUN_ID}-raw.json`. Harmless but real; it is redirected so the
   suite leaves nothing behind.

⚠️ MODULE-LEVEL ENVIRONMENT READ. `EMAIL` and `PASSWORD` are bound at import (lines 80-81), so
`_auth`'s missing-credentials branch cannot be reached by setting the environment after import —
it has to be reached by rebinding the module attribute. A test that patched `os.environ` instead
would pass on a developer machine with the vars set and fail in CI, or the reverse. `PROBE_RUN_ID`
is likewise frozen at import from `time.time()`.

⚠️ `_extract_cost_usd` IS THE REAL SURFACE. Seven distinct lookup paths and a fallthrough, in a
fixed precedence, and the precedence is the part that matters: a job carrying cost in two places
must resolve to the FIRST. Tests that only checked "finds the cost" would pass with the order
reversed, so each precedence pair is asserted against the value it must NOT return.

Each test names the change that reddens it.
"""

import json
import os
import sys

import pytest


sys.path.insert(
    0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import probe_cc_bounded_billing as mod


# ──────────────────────────────────────────────────────────────────────────
# Doubles
# ──────────────────────────────────────────────────────────────────────────

class FakeResponse:
    """Minimal stand-in for requests.Response — only what the probe touches."""

    def __init__( self, status_code=200, payload=None, text="", raise_exc=None ):
        self.status_code = status_code
        self._payload    = payload if payload is not None else { }
        self.text        = text
        self._raise_exc  = raise_exc

    def json( self ):
        return self._payload

    def raise_for_status( self ):
        if self._raise_exc is not None: raise self._raise_exc


@pytest.fixture
def no_sleep( monkeypatch ):
    """
    Record sleeps instead of taking them, AND advance a fake clock by the slept amount.
    Hazard 2.

    🔴 SLEEP AND THE CLOCK ARE ONE SEAM, NOT TWO. Stubbing half of it is the trap, and I
    walked into it. `_run_one` polls `while time.time() < deadline`, so a no-op sleep does
    not make the loop finish — it makes it BUSY-WAIT at full speed for the real 240 seconds.
    Any code that sleeps toward a wall-clock deadline has to have both halves replaced
    together or neither; a fake for one and the real thing for the other is not a partial
    stub, it is a different program.

    ⚠️ MEASURED, AND STATE THE OUTCOME PRECISELY. The standing rule counts a kill only as
    rc 1 naming a PREVIOUSLY-PASSING test, so both halves are on the record here — the
    baseline, and the mutant — because a kill claim without its baseline is an assertion
    that the test was ever green:

        baseline, unmutated            rc 0    58 passed
        mutant, before this fix        rc 124  NO VERDICT — unreadable
        mutant, after this fix         rc 1    test_run_one_recognises_every_terminal_state[failed]

    The mutation is dropping "failed" from `_run_one`'s terminal-state tuple. Its first pass
    was **not a survival and not a kill** — the run never reported. rc 124 is a two-minute
    timeout, and reading it as either result would have been a fabricated verdict; the
    fabrication was available in both directions, since "the mutation survived, my test is
    weak" and "close enough, call it killed" are equally unsupported by a run that produced
    nothing.

    Advancing the clock by the slept amount makes the deadline reachable in 48 iterations of
    arithmetic, which is what turns the middle row into the bottom one. **A guard whose red
    is indistinguishable from a hung harness has not been shown to work** — it has been shown
    to be unmeasurable, which is a different and worse thing to ship.
    """
    calls = [ ]
    clock = { "t": 1_000.0 }

    def _sleep( seconds ):
        calls.append( seconds )
        clock[ "t" ] += seconds

    monkeypatch.setattr( mod.time, "time",  lambda: clock[ "t" ] )
    monkeypatch.setattr( mod.time, "sleep", _sleep )
    return calls


# ──────────────────────────────────────────────────────────────────────────
# _ts / _print
# ──────────────────────────────────────────────────────────────────────────

def test_ts_is_wall_clock_hhmmss():
    """Reddens if the format string loses a field or gains the date."""
    out = mod._ts()
    assert len( out ) == 8
    assert out[ 2 ] == ":" and out[ 5 ] == ":"
    assert out.replace( ":", "" ).isdigit()


def test_ts_is_read_from_the_clock_not_frozen( monkeypatch ):
    """
    Reddens if `_ts` ever caches. Freezing the clock at a known value and asserting the
    output proves the call reaches `datetime.now()` rather than a module constant.
    """
    class FrozenDatetime:
        @staticmethod
        def now(): return __import__( "datetime" ).datetime( 2026, 9, 1, 4, 5, 6 )

    monkeypatch.setattr( mod, "datetime", FrozenDatetime )
    assert mod._ts() == "04:05:06"


def test_print_prefixes_with_timestamp( capsys, monkeypatch ):
    """Reddens if the bracketed timestamp prefix is dropped."""
    monkeypatch.setattr( mod, "_ts", lambda: "11:22:33" )
    mod._print( "hello" )
    assert capsys.readouterr().out == "[11:22:33] hello\n"


def test_print_flushes( monkeypatch ):
    """
    Reddens if `flush=True` is removed. This script's whole value is a human watching a
    long-running probe, and an unflushed stream shows nothing until it ends.
    """
    seen = { }
    monkeypatch.setattr( mod, "print",
                         lambda *a, **k: seen.update( k ), raising=False )
    mod._print( "x" )
    assert seen.get( "flush" ) is True


# ──────────────────────────────────────────────────────────────────────────
# _extract_cost_usd — the seven paths, and the precedence between them
# ──────────────────────────────────────────────────────────────────────────

def test_cost_from_artifacts_cost_usd():
    assert mod._extract_cost_usd( { "artifacts": { "cost_usd": 1.5 } } ) == 1.5


def test_cost_from_artifacts_total_cost_usd():
    assert mod._extract_cost_usd( { "artifacts": { "total_cost_usd": 2.25 } } ) == 2.25


def test_cost_from_artifacts_cost_summary():
    job = { "artifacts": { "cost_summary": { "total_cost_usd": 3.5 } } }
    assert mod._extract_cost_usd( job ) == 3.5


def test_cost_from_top_level_cost_summary():
    assert mod._extract_cost_usd( { "cost_summary": { "total_cost_usd": 4.0 } } ) == 4.0


def test_cost_from_metadata_cost_usd():
    assert mod._extract_cost_usd( { "metadata_json": { "cost_usd": 5.0 } } ) == 5.0


def test_cost_from_metadata_cost_summary():
    job = { "metadata_json": { "cost_summary": { "total_cost_usd": 6.0 } } }
    assert mod._extract_cost_usd( job ) == 6.0


def test_cost_absent_returns_none():
    """Reddens if the fallthrough ever returns 0.0 — a job with no cost recorded is not a
    job that cost nothing, and the summary prints 'n/a' for exactly that distinction."""
    assert mod._extract_cost_usd( { "artifacts": { }, "metadata_json": { } } ) is None


def test_cost_empty_job_returns_none():
    assert mod._extract_cost_usd( { } ) is None


def test_artifacts_cost_usd_wins_over_total_cost_usd():
    """
    PRECEDENCE. Reddens if the two checks are reordered. Asserted against the value it must
    NOT return, so a test that merely 'finds a cost' cannot pass here.
    """
    job = { "artifacts": { "cost_usd": 1.0, "total_cost_usd": 99.0 } }
    assert mod._extract_cost_usd( job ) == 1.0


def test_artifacts_wins_over_top_level_cost_summary():
    """PRECEDENCE. Reddens if the top-level lookup moves above the artifacts block."""
    job = { "artifacts": { "cost_usd": 1.0 }, "cost_summary": { "total_cost_usd": 99.0 } }
    assert mod._extract_cost_usd( job ) == 1.0


def test_top_level_wins_over_metadata():
    """PRECEDENCE. Reddens if metadata is consulted before the top-level summary."""
    job = { "cost_summary"  : { "total_cost_usd": 4.0 },
            "metadata_json" : { "cost_usd": 99.0 } }
    assert mod._extract_cost_usd( job ) == 4.0


def test_non_dict_artifacts_does_not_raise():
    """
    Reddens if the `isinstance` guard is dropped. The API has returned a list here before,
    and an AttributeError inside the probe loses the whole run's results, not one job's.
    """
    assert mod._extract_cost_usd( { "artifacts": [ "a", "b" ] } ) is None


def test_null_artifacts_falls_through_to_metadata():
    """Reddens if `or {}` is removed — `artifacts: null` is what the API sends, not `{}`."""
    job = { "artifacts": None, "metadata_json": { "cost_usd": 7.0 } }
    assert mod._extract_cost_usd( job ) == 7.0


def test_non_dict_cost_summary_is_skipped():
    """Reddens if the cost_summary isinstance guard is dropped."""
    assert mod._extract_cost_usd( { "cost_summary": "not-a-dict" } ) is None


def test_non_dict_metadata_json_does_not_raise():
    """
    The last uncovered branch (`266->272`). Reddens if the metadata isinstance guard is
    dropped. Same failure as the artifacts guard one level up and worth its own test for
    the same reason: an AttributeError here loses the whole run's results, and this is the
    path taken only when the API returns metadata as something other than an object.
    """
    assert mod._extract_cost_usd( { "metadata_json": [ 1, 2 ] } ) is None


def test_cost_is_coerced_to_float():
    """Reddens if `float()` is dropped — the API sends cost as a string on some paths, and
    the summary's `:.4f` formatting raises on a str."""
    out = mod._extract_cost_usd( { "artifacts": { "cost_usd": "1.25" } } )
    assert isinstance( out, float ) and out == 1.25


# ──────────────────────────────────────────────────────────────────────────
# _auth
# ──────────────────────────────────────────────────────────────────────────

def test_auth_exits_when_email_missing( monkeypatch ):
    """
    Hazard: EMAIL is bound at IMPORT, so this branch is only reachable by rebinding the
    module attribute. Reddens if the credential check is removed — without it the probe
    posts `{"email": null}` and fails later with a confusing 422.
    """
    monkeypatch.setattr( mod, "EMAIL", None )
    monkeypatch.setattr( mod, "PASSWORD", "pw" )
    with pytest.raises( SystemExit ) as exc:
        mod._auth()
    assert exc.value.code == 1


def test_auth_exits_when_password_missing( monkeypatch ):
    monkeypatch.setattr( mod, "EMAIL", "a@b.c" )
    monkeypatch.setattr( mod, "PASSWORD", None )
    with pytest.raises( SystemExit ):
        mod._auth()


def test_auth_does_not_post_when_credentials_missing( monkeypatch ):
    """Reddens if the exit moves below the request — the point of the guard is to not
    reach the network at all."""
    monkeypatch.setattr( mod, "EMAIL", None )
    posted = [ ]
    monkeypatch.setattr( mod.requests, "post", lambda *a, **k: posted.append( 1 ) )
    with pytest.raises( SystemExit ):
        mod._auth()
    assert posted == [ ]


def test_auth_returns_bearer_header( monkeypatch ):
    monkeypatch.setattr( mod, "EMAIL", "a@b.c" )
    monkeypatch.setattr( mod, "PASSWORD", "pw" )
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "tokens": { "access_token": "T0K" } } ) )
    assert mod._auth() == { "Authorization": "Bearer T0K" }


def test_auth_sends_credentials_and_a_timeout( monkeypatch ):
    """
    Reddens if the timeout is dropped. A probe that hangs on login hangs forever with no
    output, which is the failure mode a manual operator can least diagnose.
    """
    seen = { }
    monkeypatch.setattr( mod, "EMAIL", "a@b.c" )
    monkeypatch.setattr( mod, "PASSWORD", "pw" )

    def fake_post( url, **kwargs ):
        seen[ "url" ] = url
        seen.update( kwargs )
        return FakeResponse( payload={ "tokens": { "access_token": "T" } } )

    monkeypatch.setattr( mod.requests, "post", fake_post )
    mod._auth()

    assert seen[ "url" ].endswith( "/auth/login" )
    assert seen[ "json" ] == { "email": "a@b.c", "password": "pw" }
    assert seen[ "timeout" ] == 10


def test_auth_propagates_http_error( monkeypatch ):
    """Reddens if `raise_for_status()` is dropped — a 401 would otherwise surface as a
    KeyError on `tokens`, blaming the payload for an auth failure."""
    monkeypatch.setattr( mod, "EMAIL", "a@b.c" )
    monkeypatch.setattr( mod, "PASSWORD", "pw" )
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( raise_exc=RuntimeError( "401" ) ) )
    with pytest.raises( RuntimeError ):
        mod._auth()


# ──────────────────────────────────────────────────────────────────────────
# _run_one
# ──────────────────────────────────────────────────────────────────────────

ITEM = { "label": "L1", "prompt": "p", "max_turns": 3 }


def test_run_one_submit_non_200_returns_submit_error( monkeypatch ):
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( status_code=500, text="boom" ) )
    out = mod._run_one( { }, ITEM )
    assert out[ "state" ] == "submit_error"
    assert out[ "job_id" ] is None
    assert out[ "cost_usd" ] is None
    assert "boom" in out[ "error" ]


def test_run_one_does_not_poll_after_submit_failure( monkeypatch ):
    """Reddens if the early return is removed — polling a job that was never created
    burns the full 240s timeout for nothing."""
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( status_code=500, text="x" ) )
    gets = [ ]
    monkeypatch.setattr( mod.requests, "get", lambda *a, **k: gets.append( 1 ) )
    mod._run_one( { }, ITEM )
    assert gets == [ ]


def test_run_one_submits_bounded_task_type( monkeypatch ):
    """
    Reddens if `task_type` or `max_turns` stops being sent. This probe exists to measure
    what a BOUNDED job costs; an unbounded submission measures a different thing and would
    still look like a successful run.
    """
    seen = { }

    def fake_post( url, **kwargs ):
        seen.update( kwargs )
        return FakeResponse( payload={ "job_id": "J1" } )

    monkeypatch.setattr( mod.requests, "post", fake_post )
    monkeypatch.setattr( mod.requests, "get",
                         lambda *a, **k: FakeResponse( payload={ "state": "done" } ) )
    mod._run_one( { "Authorization": "Bearer T" }, ITEM )

    args = seen[ "json" ][ "args" ]
    assert args[ "task_type" ] == "BOUNDED"
    assert args[ "max_turns" ] == 3
    assert args[ "dry_run" ] is False
    assert seen[ "json" ][ "command" ] == mod.ROUTING_COMMAND
    assert seen[ "timeout" ] == 15


def test_run_one_returns_terminal_state_and_cost( monkeypatch ):
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J9" } ) )
    monkeypatch.setattr( mod.requests, "get",
                         lambda *a, **k: FakeResponse( payload={ "state": "done",
                                                                 "artifacts": { "cost_usd": 0.5 } } ) )
    out = mod._run_one( { }, ITEM )
    assert out[ "job_id" ]  == "J9"
    assert out[ "state" ]   == "done"
    assert out[ "cost_usd" ] == 0.5
    assert out[ "raw" ][ "state" ] == "done"


@pytest.mark.parametrize( "state", [ "done", "complete", "completed", "finished",
                                     "dead", "failed", "error" ] )
def test_run_one_recognises_every_terminal_state( monkeypatch, no_sleep, state ):
    """
    Reddens if any terminal state is dropped from the tuple. A missing one does not fail —
    it polls that job for the full 240s and reports `poll_timeout` for a job that finished,
    which is a wrong measurement rather than a visible error.

    ⚠️ `no_sleep` is REQUIRED here even though the happy path never sleeps. Without it the
    mutation this test exists to catch does not fail — it HANGS, for the real 240-second
    poll timeout, once per parameter. Measured: dropping "failed" from the tuple turned a
    0.5s suite into a 2-minute wall-clock timeout with no verdict. A test whose red is
    indistinguishable from a hung suite is not a usable guard.
    """
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J" } ) )
    monkeypatch.setattr( mod.requests, "get",
                         lambda *a, **k: FakeResponse( payload={ "state": state } ) )
    assert mod._run_one( { }, ITEM )[ "state" ] == state


def test_run_one_accepts_status_when_state_absent( monkeypatch ):
    """Reddens if the `state or status` fallback is dropped — the job API has used both."""
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J" } ) )
    monkeypatch.setattr( mod.requests, "get",
                         lambda *a, **k: FakeResponse( payload={ "status": "COMPLETED" } ) )
    assert mod._run_one( { }, ITEM )[ "state" ] == "completed"


def test_run_one_lowercases_state( monkeypatch ):
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J" } ) )
    monkeypatch.setattr( mod.requests, "get",
                         lambda *a, **k: FakeResponse( payload={ "state": "DONE" } ) )
    assert mod._run_one( { }, ITEM )[ "state" ] == "done"


def test_run_one_times_out_when_never_terminal( monkeypatch, no_sleep ):
    """
    Reddens if the deadline check is removed — the loop would never exit. The clock is
    advanced by the fake rather than waited on, so this asserts the timeout logic without
    spending 240 seconds proving it.
    """
    clock = { "t": 1000.0 }
    monkeypatch.setattr( mod.time, "time", lambda: clock[ "t" ] )
    monkeypatch.setattr( mod.time, "sleep",
                         lambda s: clock.__setitem__( "t", clock[ "t" ] + 100 ) )
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J" } ) )
    monkeypatch.setattr( mod.requests, "get",
                         lambda *a, **k: FakeResponse( payload={ "state": "running" } ) )

    out = mod._run_one( { }, ITEM )
    assert out[ "state" ]    == "poll_timeout"
    assert out[ "cost_usd" ] is None
    assert out[ "job_id" ]   == "J"
    assert out[ "elapsed_s" ] >= mod.POLL_TIMEOUT_S


def test_run_one_survives_a_polling_exception( monkeypatch, no_sleep ):
    """
    Reddens if the bare `except` around the poll is narrowed or removed. A transient
    connection error mid-probe would abort a run that has already spent minutes and real
    money; the loop is deliberately tolerant and retries until the deadline.
    """
    clock = { "t": 0.0 }
    calls = { "n": 0 }
    monkeypatch.setattr( mod.time, "time", lambda: clock[ "t" ] )
    monkeypatch.setattr( mod.time, "sleep",
                         lambda s: clock.__setitem__( "t", clock[ "t" ] + 5 ) )
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J" } ) )

    def flaky_get( *a, **k ):
        calls[ "n" ] += 1
        if calls[ "n" ] == 1: raise ConnectionError( "transient" )
        return FakeResponse( payload={ "state": "done" } )

    monkeypatch.setattr( mod.requests, "get", flaky_get )
    assert mod._run_one( { }, ITEM )[ "state" ] == "done"
    assert calls[ "n" ] == 2


def test_run_one_ignores_non_200_poll_responses( monkeypatch, no_sleep ):
    """Reddens if the `status_code == 200` check is dropped — a 404 body would be parsed
    as a job and could satisfy the terminal-state test with garbage."""
    clock = { "t": 0.0 }
    calls = { "n": 0 }
    monkeypatch.setattr( mod.time, "time", lambda: clock[ "t" ] )
    monkeypatch.setattr( mod.time, "sleep",
                         lambda s: clock.__setitem__( "t", clock[ "t" ] + 5 ) )
    monkeypatch.setattr( mod.requests, "post",
                         lambda *a, **k: FakeResponse( payload={ "job_id": "J" } ) )

    def get( *a, **k ):
        calls[ "n" ] += 1
        if calls[ "n" ] == 1: return FakeResponse( status_code=404, payload={ "state": "done" } )
        return FakeResponse( payload={ "state": "done" } )

    monkeypatch.setattr( mod.requests, "get", get )
    mod._run_one( { }, ITEM )
    assert calls[ "n" ] == 2


# ──────────────────────────────────────────────────────────────────────────
# _print_summary
# ──────────────────────────────────────────────────────────────────────────

def _row( label="L", state="done", cost=1.0, elapsed=2.0 ):
    return { "label": label, "state": state, "cost_usd": cost, "elapsed_s": elapsed }


def test_summary_totals_each_cluster_separately( capsys ):
    """Reddens if the two totals are summed into one — separating in-repo from web-synth
    cost IS the experiment this script runs."""
    mod._print_summary( [ _row( cost=1.0 ), _row( cost=2.0 ) ], [ _row( cost=4.0 ) ] )
    out = capsys.readouterr().out
    assert "Cluster A total (in-repo)       : $3.0000" in out
    assert "Cluster B total (web synth)     : $4.0000" in out


def test_summary_grand_total_is_the_sum( capsys ):
    mod._print_summary( [ _row( cost=1.5 ) ], [ _row( cost=2.25 ) ] )
    assert "GRAND TOTAL (reported by jobs)  : $3.7500" in capsys.readouterr().out


def test_summary_renders_missing_cost_as_na( capsys ):
    """Reddens if None is formatted as $0.0000 — that would report a job whose cost was
    never recorded as a job that was free, which is the exact claim this probe tests."""
    mod._print_summary( [ _row( cost=None ) ], [ ] )
    out = capsys.readouterr().out
    assert "n/a" in out
    assert "$0.0000" not in out.split( "Cluster A total" )[ 0 ]


def test_summary_treats_missing_cost_as_zero_in_the_total( capsys ):
    """The `or 0` coalesce: an unknown cost must not poison the total with a TypeError."""
    mod._print_summary( [ _row( cost=None ), _row( cost=2.0 ) ], [ ] )
    assert "Cluster A total (in-repo)       : $2.0000" in capsys.readouterr().out


def test_summary_handles_two_empty_clusters( capsys ):
    """Reddens if the totals are seeded from the first row rather than 0.0."""
    mod._print_summary( [ ], [ ] )
    assert "GRAND TOTAL (reported by jobs)  : $0.0000" in capsys.readouterr().out


def test_summary_lists_every_label( capsys ):
    mod._print_summary( [ _row( label="alpha" ) ], [ _row( label="beta" ) ] )
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out


def test_summary_states_the_theory_being_tested( capsys ):
    """
    Reddens if the closing lines are dropped. The operator reads this summary against the
    Anthropic console by hand; without the comparison instruction the numbers are inert.
    """
    mod._print_summary( [ ], [ ] )
    out = capsys.readouterr().out
    assert "console credit-balance" in out
    assert "Max-subscription auth" in out


# ──────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def wired_main( monkeypatch, tmp_path ):
    """Neutralise all three hazards, and record what main() would have done."""
    submitted = [ ]
    monkeypatch.setattr( mod, "_auth", lambda: { "Authorization": "Bearer T" } )
    monkeypatch.setattr( mod, "_run_one",
                         lambda h, item: submitted.append( item[ "label" ] ) or
                                         _row( label=item[ "label" ], cost=1.0 ) )
    monkeypatch.setattr( mod, "PROBE_RUN_ID", "probe-test" )
    monkeypatch.chdir( tmp_path )
    return submitted


def test_main_runs_every_job_in_both_clusters( wired_main, no_sleep, capsys, monkeypatch ):
    monkeypatch.setattr( mod, "open", lambda *a, **k: __import__( "io" ).StringIO(), raising=False )
    mod.main()
    expected = [ i[ "label" ] for i in mod.CLUSTER_A_IN_REPO ] + \
               [ i[ "label" ] for i in mod.CLUSTER_B_WEB_SYNTH ]
    assert wired_main == expected


def test_main_does_not_sleep_before_the_first_job( wired_main, no_sleep, monkeypatch ):
    """
    Reddens if the `idx > 0` guard is dropped. The waits exist to space billing events; a
    leading sleep adds a minute of dead time to every run and measures nothing.
    """
    monkeypatch.setattr( mod, "open", lambda *a, **k: __import__( "io" ).StringIO(), raising=False )
    mod.main()
    n_jobs = len( mod.CLUSTER_A_IN_REPO ) + len( mod.CLUSTER_B_WEB_SYNTH )
    # one gap inside each cluster, plus exactly one between them
    assert len( no_sleep ) == ( n_jobs - 2 ) + 1
    assert set( no_sleep ) == { mod.WAIT_BETWEEN_JOBS_S }


def test_main_waits_between_the_two_clusters( wired_main, no_sleep, capsys, monkeypatch ):
    """Reddens if the inter-cluster sleep is removed — the script's own banner promises the
    wait is uniform including between clusters."""
    monkeypatch.setattr( mod, "open", lambda *a, **k: __import__( "io" ).StringIO(), raising=False )
    mod.main()
    assert "end Cluster A" in capsys.readouterr().out


def test_main_persists_raw_results( wired_main, no_sleep, tmp_path, monkeypatch ):
    """
    Reddens if the raw dump is dropped or its keys are renamed. The JSON is the forensic
    record; the printed summary is not re-parseable and a probe run costs real money to
    repeat.
    """
    written = { }

    class Sink:
        def __enter__( self ): return self
        def __exit__( self, *a ): return False
        def write( self, s ): written[ "buf" ] = written.get( "buf", "" ) + s

    monkeypatch.setattr( mod, "open", lambda *a, **k: Sink(), raising=False )
    mod.main()

    payload = json.loads( written[ "buf" ] )
    assert payload[ "probe_run_id" ] == "probe-test"
    assert payload[ "base_url" ]     == mod.BASE_URL
    assert len( payload[ "cluster_a" ] ) == len( mod.CLUSTER_A_IN_REPO )
    assert len( payload[ "cluster_b" ] ) == len( mod.CLUSTER_B_WEB_SYNTH )


def test_main_authenticates_before_submitting( monkeypatch, no_sleep, tmp_path ):
    """Reddens if the auth call moves below the first submission — every job would then be
    posted unauthenticated and fail, after the operator had already committed to the run."""
    order = [ ]
    monkeypatch.setattr( mod, "_auth", lambda: order.append( "auth" ) or { } )
    monkeypatch.setattr( mod, "_run_one",
                         lambda h, item: order.append( "run" ) or _row() )
    monkeypatch.setattr( mod, "open", lambda *a, **k: __import__( "io" ).StringIO(), raising=False )
    monkeypatch.chdir( tmp_path )
    mod.main()
    assert order[ 0 ] == "auth"


# ──────────────────────────────────────────────────────────────────────────
# Module configuration
# ──────────────────────────────────────────────────────────────────────────

def test_submit_endpoint_is_v2():
    """
    Reddens if the endpoint regresses to `/api/claude-code/submit`, which is a retired
    tombstone. Rick ruled this on 2026-08-21 and the row records it as the reason the
    script counts as actively maintained rather than an abandoned throwaway.
    """
    assert mod.SUBMIT_ENDPOINT.endswith( "/api/v2/submit" )


def test_probe_run_id_is_unique_per_import():
    """Reddens if PROBE_RUN_ID becomes a constant — two runs would overwrite each other's
    raw JSON, and the second would silently look like the first."""
    assert mod.PROBE_RUN_ID.startswith( "probe-" )
    assert mod.PROBE_RUN_ID[ 6: ].isdigit()


def test_both_clusters_are_populated_and_well_formed():
    """Reddens if a cluster is emptied or an item loses a key — `_run_one` indexes all
    three directly, so a missing key is a KeyError mid-run rather than at startup."""
    assert mod.CLUSTER_A_IN_REPO and mod.CLUSTER_B_WEB_SYNTH
    for item in mod.CLUSTER_A_IN_REPO + mod.CLUSTER_B_WEB_SYNTH:
        assert { "label", "prompt", "max_turns" } <= set( item )


def test_poll_timeout_exceeds_poll_interval():
    """A timeout shorter than one interval would report poll_timeout on every job without
    ever having polled."""
    assert mod.POLL_TIMEOUT_S > mod.POLL_INTERVAL_S
