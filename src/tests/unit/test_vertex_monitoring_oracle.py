"""
AC-D4 / AC-D4b / AC-D8 / AC-D9a — the §6a sound oracle.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md §6a

THE POINT OF THIS FILE, STATED PLAINLY: these four ACs would otherwise have been written
against `google.cloud.monitoring_v3`, WHICH IS NOT INSTALLED — behind an `importorskip`,
which SKIPS, which is invisible in a 9,289-test run. The pilot would have gone green with
its sound oracle never once consulted. So the oracle rides REST (google.auth + requests,
both present), and it is tested UNCONDITIONALLY here with an injected fake transport.

NO GCP CALL IS MADE BY THIS FILE. transport and clock are injected. The one function that
can reach GCP (build_google_auth_transport) is never called here — that is the seat holding
the authority to spend, and it is not this one.

Venue: :7999-eligible — pure in-memory. No network, no mutation, no spend.
"""

import pytest

from cosa.utils.vertex_monitoring_oracle import (
    INVOCATION_METRIC,
    TOKEN_METRICS,
    MonitoringOracle,
    OracleInadmissible,
    Verdict,
    _is_ok,
    _rfc3339,
    resolve_project_and_region,
)

PROJECT = "unit-test-project-0000"   # NEVER the real sandbox id: a tracked .py is an EXECUTABLE surface (my own guard caught this)
REGION  = "global"
MODEL   = "claude-opus-4-8"


def _series( location=REGION, model=MODEL, container=None, code="200", points=None ):
    """One PublisherModel time-series entry, shaped like the real API response."""
    return {
        "resource": { "type": "aiplatform.googleapis.com/PublisherModel",
                      "labels": { "location"           : location,
                                  "model_user_id"      : model,
                                  "resource_container" : container if container else f"projects/{PROJECT}" } },
        "metric"  : { "labels": { "response_code": code } },
        "points"  : points if points else [],
    }


def _oracle( payloads, now=None ):
    """
    An oracle whose transport replays canned payloads and whose clock is a list of ticks.
    Nothing here can reach the network.
    """
    calls = { "n": 0 }
    ticks = list( now ) if now else [ 0.0 ]

    def transport( url, params, token ):
        payload = payloads[ min( calls[ "n" ], len( payloads ) - 1 ) ]
        calls[ "n" ] += 1
        return payload

    def clock():
        return ticks.pop( 0 ) if len( ticks ) > 1 else ticks[ 0 ]

    return MonitoringOracle( PROJECT, transport, clock ), calls


# ── AC-D4 / AC-D4b ────────────────────────────────────────────────────────────────

def test_ac_d4_passes_when_traffic_ran_where_we_configured_it():
    oracle, _ = _oracle( [ { "timeSeries": [ _series() ] } ] )
    verdict, detail = oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )
    assert verdict == Verdict.PASS
    assert "global" in detail


def test_ac_d4b_FAILS_when_traffic_went_to_a_different_region_than_configured():
    """
    THE SINGLE MOST VALUABLE AC IN THE DOCUMENT — the only one that checks what HAPPENED
    rather than what we INTENDED. A per-model VERTEX_REGION_CLAUDE_* override routes Opus
    alone somewhere else, where it runs, bills, and logs nothing. Every other region guard
    checks our intent; this one checks reality, and reality is what three revisions of
    confident reasoning got wrong.
    """
    oracle, _ = _oracle( [ { "timeSeries": [ _series( location="us-east5" ) ] } ] )
    verdict, detail = oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )
    assert verdict == Verdict.FAIL
    assert "TRAFFIC WENT SOMEWHERE ELSE" in detail
    assert "us-east5" in detail


def test_ac_d4_FAILS_when_the_model_pin_was_defeated():
    oracle, _ = _oracle( [ { "timeSeries": [ _series( model="claude-opus-4-1" ) ] } ] )
    verdict, detail = oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )
    assert verdict == Verdict.FAIL
    assert "pin was defeated" in detail


def test_ac_d4_FAILS_when_another_project_is_being_billed():
    oracle, _ = _oracle( [ { "timeSeries": [ _series( container="projects/someone-else" ) ] } ] )
    verdict, detail = oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )
    assert verdict == Verdict.FAIL
    assert "someone else is being billed" in detail


def test_ac_d4_FAILS_when_the_call_ran_but_was_rejected():
    """It ran (so it may have cost something) but did not succeed — Gate-C data-sharing."""
    oracle, _ = _oracle( [ { "timeSeries": [ _series( code="400" ) ] } ] )
    verdict, detail = oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )
    assert verdict == Verdict.FAIL
    assert "REJECTED" in detail


def test_ac_d4_is_INADMISSIBLE_on_zero_series_never_FAIL():
    """
    🔴 THE RULE THE WHOLE CASCADE WAS BUILT AROUND.

    Zero rows means BOTH "the toggle never engaged, $0 spent" AND "the toggle engaged, the
    region trap fired, real money burned silently." Two opposite outcomes, ONE observation.
    A team that reads zero as FAIL concludes "the toggle didn't work," rolls back, and NEVER
    LEARNS MONEY WAS SPENT. So it is INADMISSIBLE — never PASS, and never FAIL.
    """
    oracle, _ = _oracle( [ { "timeSeries": [] } ] )
    verdict, detail = oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )
    assert verdict == Verdict.INADMISSIBLE
    assert verdict != Verdict.FAIL
    assert "two opposite worlds" in detail.lower() or "opposite worlds" in detail.lower()


def test_ac_d4_tolerates_a_series_with_no_response_code_label():
    """A missing response_code is not a rejection — do not invent a failure from a silence."""
    entry = _series()
    entry[ "metric" ][ "labels" ].pop( "response_code" )
    oracle, _ = _oracle( [ { "timeSeries": [ entry ] } ] )
    assert oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )[ 0 ] == Verdict.PASS


def test_ac_d4_tolerates_a_series_with_no_resource_container():
    entry = _series()
    entry[ "resource" ][ "labels" ].pop( "resource_container" )
    oracle, _ = _oracle( [ { "timeSeries": [ entry ] } ] )
    assert oracle.verify_ran_on_vertex( REGION, MODEL, 0, 100 )[ 0 ] == Verdict.PASS


# ── AC-D8: the CANARY, not a clock ────────────────────────────────────────────────

def test_the_canary_lands_and_makes_the_oracles_silence_admissible():
    """Poll until the KNOWN row appears. Only then may silence about anything else be trusted."""
    payloads = [ { "timeSeries": [] },
                 { "timeSeries": [] },
                 { "timeSeries": [ _series( model="CANARY" ) ] } ]
    oracle, _ = _oracle( payloads, now=[ 0.0, 1.0, 2.0, 3.0, 4.0 ] )

    landed = oracle.await_canary(
        INVOCATION_METRIC, start_ts=0, deadline_ts=99,
        is_canary=lambda s: s[ "resource" ][ "labels" ][ "model_user_id" ] == "CANARY",
        poll=lambda: None,
    )
    assert landed[ "resource" ][ "labels" ][ "model_user_id" ] == "CANARY"


def test_a_canary_that_never_lands_is_INADMISSIBLE_and_FAILS_LOUD():
    """
    🔴 THE BUG REV. 2 COMMITTED INSIDE ITS OWN FIX.

    Cloud Monitoring has ingestion latency. "Assert the counter did not increment" PASSES
    BECAUSE THE DATA HAS NOT LANDED YET — not because nothing happened. Absence of output
    read as absence of the event: the founding bug of this document, re-committed in the AC
    written to replace a bad oracle.

    So a canary that never lands does NOT quietly pass. It raises. LOUDLY.
    """
    oracle, _ = _oracle( [ { "timeSeries": [] } ], now=[ 0.0, 5.0, 10.0, 99.0 ] )

    with pytest.raises( OracleInadmissible, match="INADMISSIBLE, not" ):
        oracle.await_canary(
            INVOCATION_METRIC, start_ts=0, deadline_ts=8,
            is_canary=lambda s: False,
            poll=lambda: None,
        )


def test_there_is_no_sleep_constant_anywhere_in_the_oracle():
    """
    NEVER SPEC A LATENCY. SPEC A CANARY. Google declares `ingestDelay: None`, so a hardcoded
    wait is an assumption wearing a constant's clothing — and it can be WRONG FOREVER,
    SILENTLY: Google changes the real delay and every negative test starts passing for the
    wrong reason, with nobody notified. The observed "~3 minutes" is TELEMETRY from a single
    observation. It must never enter the test.

    HOW THIS IS CHECKED, AND WHY IT CHANGED (row 122f07a1). This used to read the
    module's source text and assert that "time.sleep" and "import time" were absent.
    Two spellings walked straight past it — `from time import sleep` then a bare
    `sleep( 3 )`, and `import time as t` then `t.sleep( 3 )`. Neither contains
    either literal. The check below reads what the module ACTUALLY imported and
    what it ACTUALLY calls, so every spelling is covered and a rename of the
    surrounding code cannot false-alarm it.
    """
    import ast
    import inspect
    import cosa.utils.vertex_monitoring_oracle as mod

    # 1. Nothing named `time` or `sleep` is bound in the module namespace, however
    #    it was spelled on the import line.
    for name in ( "time", "sleep", "monotonic", "perf_counter" ):
        assert name not in vars( mod ), (
            f"the oracle bound `{name}` — it must not own a clock; the caller injects one"
        )

    # 2. No call anywhere in the module ends in .sleep() or is a bare sleep().
    tree  = ast.parse( inspect.getsource( mod ) )
    slept = [
        ast.unparse( n.func ) for n in ast.walk( tree )
        if isinstance( n, ast.Call ) and ast.unparse( n.func ).split( "." )[ -1 ] == "sleep"
    ]
    assert not slept, f"a sleep crept into the oracle — spec a canary, not a clock: {slept}"

    # 3. The import statements themselves name no clock module, under any alias.
    imported = set()
    for n in ast.walk( tree ):
        if isinstance( n, ast.Import ):
            for a in n.names: imported.add( a.name.split( "." )[ 0 ] )
        elif isinstance( n, ast.ImportFrom ) and n.module:
            imported.add( n.module.split( "." )[ 0 ] )
    assert "time" not in imported, (
        f"the oracle imports `time` — the bound is a caller deadline, not a constant; "
        f"imports were {sorted( imported )}"
    )


# The receipt await_canary() hands back: proof the oracle was AWAKE in this window.
LANDED_CANARY = { "resource": { "labels": { "model_user_id": "CANARY" } } }


def test_ac_d8_FAILS_when_a_max_session_carries_vertex_keys():
    """
    The tmux-server taint (OSQ-6, verified live). This is the INVERSE of the hole the toggle
    was built to close, and it is WORSE: the other mis-bills a session that already opted
    into billing; this one bills a session that NEVER ASKED.

    Note the canary is None here ON PURPOSE: a LEAK is a POSITIVE observation, and a
    positive needs no proof-of-liveness. Only a SILENCE does. The primary check must stay
    trustworthy on its own — that is the whole reason it is primary.
    """
    oracle, _ = _oracle( [ { "timeSeries": [] } ] )
    verdict, detail = oracle.verify_no_leak_into_default_path(
        env={ "CLAUDE_CODE_USE_VERTEX": "1" }, series_before=0, series_after=0, canary=None
    )
    assert verdict == Verdict.FAIL
    assert "NEVER ASKED" in detail


def test_ac_d8_is_INADMISSIBLE_when_no_canary_proved_the_oracle_awake():
    """
    🔴 THE DEFECT THIS ARGUMENT EXISTS TO KILL — and it SHIPPED in my own oracle, in the
    function written to stop exactly it.

    The first signature took no canary. Called on a clean env with a flat counter, it
    returned PASS — and its detail string SAID "(admissible ONLY because the canary landed
    first)" when NO CANARY HAD BEEN FIRED. It did not merely fail to check the
    precondition; IT MANUFACTURED AN ATTESTATION TO IT. The canary discipline was a
    COMMENT doing the work of a MECHANISM, in the AC whose entire subject is that a
    negative assertion against a lagging oracle is worthless without proof of liveness.

    A silence from an unproven instrument is INADMISSIBLE — a third verdict, and never a
    PASS. §6a: "Canary never lands within the bound ⇒ the test is INADMISSIBLE, not
    PASSING. FAIL LOUD."
    """
    oracle, _ = _oracle( [ { "timeSeries": [] } ] )
    verdict, detail = oracle.verify_no_leak_into_default_path(
        env={}, series_before=0, series_after=0, canary=None
    )
    assert verdict == Verdict.INADMISSIBLE, (
        "a clean env + a flat counter + NO CANARY returned a PASS. The oracle was never shown "
        "to be awake, so its silence proves nothing — this is the founding bug of the cascade."
    )
    assert "NO CANARY" in detail


def test_ac_d8_FAILS_when_the_windowed_counter_increments_during_a_max_session():
    oracle, _ = _oracle( [ { "timeSeries": [] } ] )
    verdict, detail = oracle.verify_no_leak_into_default_path(
        env={}, series_before=2, series_after=5, canary=LANDED_CANARY
    )
    assert verdict == Verdict.FAIL
    assert "leaked onto Vertex" in detail


def test_ac_d8_passes_on_a_clean_env_and_a_flat_counter_ONLY_WITH_A_LANDED_CANARY():
    """The ONLY route to a PASS on the negative: the oracle was proven awake in-window."""
    oracle, _ = _oracle( [ { "timeSeries": [] } ] )
    verdict, detail = oracle.verify_no_leak_into_default_path(
        env={}, series_before=7, series_after=7, canary=LANDED_CANARY
    )
    assert verdict == Verdict.PASS
    assert "proven awake" in detail


# ── AC-D9a ────────────────────────────────────────────────────────────────────────

RATE_CARD = { TOKEN_METRICS[ 0 ]: 0.000015, TOKEN_METRICS[ 1 ]: 0.000075 }


def test_ac_d9a_derives_spend_from_token_metrics():
    payload = { "timeSeries": [ { "points": [ { "value": { "int64Value": "1000" } } ] } ] }
    oracle, _ = _oracle( [ payload, payload ] )
    verdict, usd, _d = oracle.derived_spend( 0, 100, RATE_CARD )
    assert verdict == Verdict.PASS
    assert usd == pytest.approx( 1000 * 0.000015 + 1000 * 0.000075 )


def test_ac_d9a_zero_tokens_is_INADMISSIBLE_not_zero_dollars():
    """
    "We measured zero spend" and "we cannot see the spend" are DIFFERENT CLAIMS, and only
    one of them is safe to hand to the person paying the bill. Reporting an unmeasured zero
    as $0.00 is how you tell Rick a metered pilot was free.
    """
    oracle, _ = _oracle( [ { "timeSeries": [] } ] )
    verdict, usd, detail = oracle.derived_spend( 0, 100, RATE_CARD )
    assert verdict == Verdict.INADMISSIBLE
    assert usd is None
    assert "cannot see the spend" in detail


# ── helpers ───────────────────────────────────────────────────────────────────────

def test_time_series_builds_a_publisher_model_filter():
    seen = {}

    def transport( url, params, token ):
        seen.update( { "url": url, "params": params } )
        return { "timeSeries": [] }

    oracle = MonitoringOracle( PROJECT, transport, lambda: 0.0 )
    assert oracle.time_series( INVOCATION_METRIC, 0, 60 ) == []
    assert PROJECT in seen[ "url" ]
    assert "PublisherModel" in seen[ "params" ][ "filter" ]
    assert INVOCATION_METRIC in seen[ "params" ][ "filter" ]


def test_token_provider_is_called_for_every_read():
    calls = []
    oracle = MonitoringOracle(
        PROJECT, lambda u, p, t: { "timeSeries": [] }, lambda: 0.0,
        token_provider=lambda: calls.append( 1 ) or "tok",
    )
    oracle.time_series( INVOCATION_METRIC, 0, 1 )
    assert calls == [ 1 ]


def test_default_token_provider_yields_none():
    oracle = MonitoringOracle( PROJECT, lambda u, p, t: { "timeSeries": [] }, lambda: 0.0 )
    assert oracle.token_provider() is None


@pytest.mark.parametrize( "code,ok", [ ( "200", True ), ( 200, True ), ( "429", False ), ( "400", False ) ] )
def test_is_ok_only_accepts_2xx( code, ok ):
    assert _is_ok( code ) is ok


def test_rfc3339_renders_utc():
    assert _rfc3339( 0 ) == "1970-01-01T00:00:00Z"


def test_resolve_project_and_region_reads_the_env():
    assert resolve_project_and_region(
        { "LUPIN_GCP_PROJECT_ID": PROJECT, "LUPIN_VERTEX_REGION": REGION }
    ) == ( PROJECT, REGION )


def test_resolve_refuses_to_guess_a_missing_variable():
    """
    No fallback. Guessing the project bills someone who never chose to be billed; guessing
    the region points the oracle at a region the model cannot serve — and then reports a
    confidently wrong verdict, which is worse than no verdict.
    """
    with pytest.raises( KeyError ):
        resolve_project_and_region( { "LUPIN_GCP_PROJECT_ID": PROJECT } )


def test_the_canary_is_found_among_OTHER_traffic_in_the_same_window():
    """
    The canary will NOT be alone. Rick already ran two real Opus calls on this project, so
    "no series exists" is FALSE BY CONSTRUCTION — the baseline is "the series as of pilot
    start," not "zero, forever." The poller must therefore SKIP PAST foreign series to find
    the row it fired itself; a matcher that only works on an empty window is a matcher that
    works only in the lab.
    """
    payload = { "timeSeries": [
        _series( model="claude-sonnet-4-6" ),      # somebody else's traffic
        _series( model="claude-opus-4-8" ),        # and more of it
        _series( model="CANARY" ),                 # ...ours, third in the list
    ] }
    oracle, _ = _oracle( [ payload ], now=[ 0.0, 1.0, 2.0 ] )

    landed = oracle.await_canary(
        INVOCATION_METRIC, start_ts=0, deadline_ts=99,
        is_canary=lambda s: s[ "resource" ][ "labels" ][ "model_user_id" ] == "CANARY",
        poll=lambda: None,
    )
    assert landed[ "resource" ][ "labels" ][ "model_user_id" ] == "CANARY"
