"""
The §6a SOUND ORACLE — Cloud Monitoring `PublisherModel`, over REST.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md §6a
Serves: AC-D4, AC-D4b, AC-D8, AC-D9a.

WHY REST AND NOT `google.cloud.monitoring_v3`
---------------------------------------------
THE CLIENT LIBRARY IS NOT INSTALLED ON THIS HOST. Verified 2026-07-13. §6a rests the
entire pilot on this oracle, and the idiomatic way to write a test against a missing
library is `pytest.importorskip(...)` — which turns AC-D4, AC-D4b, AC-D8 and AC-D9a into
SKIPS. A skip is invisible in a 9,289-test run. We would have certified a METERED-BILLING
pilot with four assertions that never executed: `modules.bats` reincarnated inside the
acceptance criteria, in the cascade convened to kill that disease.

`google.auth` and `requests` ARE installed. The Monitoring v3 REST surface is therefore
reachable with ZERO new dependencies, and the ACs can be written UNCONDITIONALLY — so a
missing instrument fails LOUD instead of vanishing into a skip.

WHY THIS ORACLE AT ALL (§6a)
----------------------------
It is emitted by the Vertex SERVING PATH ITSELF: no setPublisherModelConfig, no BigQuery,
no logging config, no dataset. It shares ZERO failure modes with the thing it verifies.
The BigQuery row cannot be given that property — and the BQ oracle FAILS TOWARD "nothing
happened" while money burns (toggle-never-engaged and region-trap-burned-real-money produce
an IDENTICAL zero-row reading). An oracle that cannot distinguish two opposite worlds is
not an oracle.

THE THREE RULES THIS MODULE REFUSES TO BREAK
--------------------------------------------
1. ZERO ROWS IS NOT A VERDICT. It means BOTH "nothing ran" AND "it ran and we are blind."
   So there are THREE verdicts, not two: PASS, FAIL, and INADMISSIBLE. Reporting a blind
   instrument as a negative result is how a team "learns" something false and rolls back
   the wrong thing (F-D18).

2. NEVER SPEC A LATENCY. SPEC A CANARY. Arnold fetched the metric descriptor: Google
   declares `ingestDelay: None`. So ANY hardcoded wait is an assumption wearing a
   constant's clothing — and a fixed wait can be WRONG FOREVER, SILENTLY: Google changes
   the real delay and every negative test starts passing for the wrong reason, with nobody
   notified. There is NO sleep constant in this file. The bound is a deadline supplied by
   the caller, and the clock is injected.

3. A NEGATIVE ASSERTION IS ADMISSIBLE ONLY INSIDE A WINDOW WHERE THE INSTRUMENT HAS BEEN
   PROVEN AWAKE. Fire a known canary, poll until THAT lands, and only then may you trust
   the oracle's SILENCE about anything else. The canary makes the oracle prove it is awake
   in the same window in which you trust its silence.

NO GCP CALL IS MADE BY IMPORTING OR UNIT-TESTING THIS MODULE. `transport` and `clock` are
injected; the tests supply fakes. The real transport is built only when a caller explicitly
asks for it, which is the seat that holds the authority to spend.
"""

import os


MONITORING_HOST = "https://monitoring.googleapis.com"

# The metric §6a designates. DELTA/INT64, emitted by the serving path.
INVOCATION_METRIC = "aiplatform.googleapis.com/publisher/online_serving/model_invocation_count"
TOKEN_METRICS     = (
    "aiplatform.googleapis.com/publisher/online_serving/input_token_size",
    "aiplatform.googleapis.com/publisher/online_serving/output_token_size",
)

RESOURCE_TYPE = "aiplatform.googleapis.com/PublisherModel"


class Verdict:
    """
    THREE verdicts. The third one is the whole point.

    PASS / FAIL are what everyone writes. INADMISSIBLE is what this cascade cost four
    revisions to learn: an observation that cannot distinguish two opposite worlds is not
    an observation, and reporting it as FAIL teaches the team something false.

        "Search didn't fire" and "we cannot see" are different claims.  (F-D18)
    """
    PASS         = "PASS"
    FAIL         = "FAIL"
    INADMISSIBLE = "INADMISSIBLE"


class OracleInadmissible( RuntimeError ):
    """The instrument could not be shown to be awake. NOT a failure of the thing under test."""


class MonitoringOracle:
    """
    Read-only Cloud Monitoring client over REST. Makes no call it is not asked to make.

    Requires:
        - project_id is a non-empty string
        - transport( url, params, token ) -> dict, injected (tests pass a fake)
        - clock() -> float seconds, injected (NO module-level time import in the hot path)

    Ensures:
        - every method is read-only; this class cannot write, configure, or predict
    """

    def __init__( self, project_id, transport, clock, token_provider=None ):
        self.project_id     = project_id
        self.transport      = transport
        self.clock          = clock
        self.token_provider = token_provider if token_provider else ( lambda: None )

    # ── raw read ──────────────────────────────────────────────────────────────────

    def time_series( self, metric, start_ts, end_ts ):
        """
        Fetch PublisherModel series for `metric` in [start_ts, end_ts].

        Ensures:
            - returns a list of series dicts (possibly EMPTY — and empty is NOT a verdict)
        """
        url    = f"{MONITORING_HOST}/v3/projects/{self.project_id}/timeSeries"
        params = {
            "filter"               : (
                f'metric.type="{metric}" AND resource.type="{RESOURCE_TYPE}"'
            ),
            "interval.startTime"   : _rfc3339( start_ts ),
            "interval.endTime"     : _rfc3339( end_ts ),
        }
        payload = self.transport( url, params, self.token_provider() )
        return payload.get( "timeSeries", [] )

    # ── AC-D8 rule 2: the CANARY. Never a clock. ─────────────────────────────────

    def await_canary( self, metric, start_ts, deadline_ts, is_canary, poll ):
        """
        Poll until a KNOWN-POSITIVE row lands, proving the oracle is AWAKE in this window.

        This is the mechanism that makes a NEGATIVE assertion trustworthy. Until the canary
        is visible, the oracle's silence means nothing, and any "the counter did not
        increment" claim is INADMISSIBLE rather than passing.

        There is deliberately NO default deadline and NO sleep constant. Google declares no
        ingest delay, so a hardcoded wait would be an assumption wearing a constant's
        clothing — wrong forever, silently, the day Google changes the real latency.

        Requires:
            - is_canary( series ) -> bool identifies the known row we fired ourselves
            - poll() advances the caller's own waiting strategy (injected; may be a no-op)
            - deadline_ts is an absolute bound supplied by the CALLER

        Ensures:
            - returns the observed canary series when it lands

        Raises:
            - OracleInadmissible if the canary never lands within the bound. FAIL LOUD.
              The test is INADMISSIBLE, not PASSING — the instrument was never shown to
              speak, so its silence about everything else is worthless.
        """
        while self.clock() < deadline_ts:
            for series in self.time_series( metric, start_ts, self.clock() ):
                if is_canary( series ):
                    return series
            poll()

        raise OracleInadmissible(
            "THE CANARY NEVER LANDED within the bound. This test is INADMISSIBLE, not "
            "PASSING. The oracle was never shown to be awake in this window, so its SILENCE "
            "about the session under test proves NOTHING — 'nothing ran' and 'it ran and we "
            "are blind' are the same observation here. Do NOT read this as a green. "
            "(Record the observed delay as telemetry; NEVER let a test depend on it.)"
        )

    # ── AC-D4 / AC-D4b ────────────────────────────────────────────────────────────

    def verify_ran_on_vertex( self, expected_region, expected_model, start_ts, end_ts ):
        """
        AC-D4 + AC-D4b — did it run on Vertex, in the region we CONFIGURED, on the pinned
        model, billed to our project, and SUCCEED?

        AC-D4b is the only assertion in the entire design that checks what HAPPENED rather
        than what we INTENDED — and "what happened" is exactly what three revisions of
        confident reasoning got wrong. If a per-model region override fired, the invocation
        appears under a DIFFERENT `location` and this NAMES THE BUG.

        Ensures:
            - returns ( Verdict, detail ) — INADMISSIBLE on zero series, never FAIL
        """
        series = self.time_series( INVOCATION_METRIC, start_ts, end_ts )

        if not series:
            return ( Verdict.INADMISSIBLE,
                     "ZERO SERIES. This does NOT mean 'the toggle did not engage' — it equally "
                     "means 'it engaged, burned metered Opus, and we are blind to it.' Two "
                     "opposite worlds, one observation. Land a canary first (await_canary); "
                     "only then is this oracle's silence admissible." )

        for entry in series:
            labels    = entry.get( "resource", {} ).get( "labels", {} )
            metric_ls = entry.get( "metric", {} ).get( "labels", {} )

            location  = labels.get( "location" )
            container = labels.get( "resource_container" )
            model     = labels.get( "model_user_id" )
            code      = metric_ls.get( "response_code" )

            if location != expected_region:
                return ( Verdict.FAIL,
                         f"AC-D4b — TRAFFIC WENT SOMEWHERE ELSE. Configured region "
                         f"'{expected_region}', but the serving path reports location "
                         f"'{location}'. A per-model VERTEX_REGION_CLAUDE_* override fired, or "
                         f"the region SSOT is wrong. This is the ONLY guard that checks what "
                         f"HAPPENED rather than what we intended." )

            if model != expected_model:
                return ( Verdict.FAIL,
                         f"model_user_id is '{model}', expected '{expected_model}' — the pin was "
                         f"defeated and a different model was billed." )

            if container and self.project_id not in container:
                return ( Verdict.FAIL,
                         f"resource_container '{container}' is not our project "
                         f"'{self.project_id}' — the project guard was bypassed and someone "
                         f"else is being billed." )

            if code is not None and not _is_ok( code ):
                return ( Verdict.FAIL,
                         f"the invocation was REJECTED (response_code={code}) — it ran but did "
                         f"not succeed. Likely the Gate-C dataSharingEnabledProvider check." )

        return ( Verdict.PASS,
                 f"{len( series )} series on Vertex at '{expected_region}', model "
                 f"'{expected_model}', our project, response OK." )

    # ── AC-D8 ─────────────────────────────────────────────────────────────────────

    def verify_no_leak_into_default_path( self, env, series_before, series_after, canary ):
        """
        AC-D8 — zero leakage into the Max path. The document's most dangerous assertion,
        because it is a NEGATIVE against a LAGGING oracle.

        PRIMARY, and the only part trustworthy on its own: a PROCESS-ENV check. It has no
        ingestion lag and cannot false-pass. Rev. 2's version asserted "the counter did not
        increment" against a LAGGING oracle — so it passed BECAUSE THE DATA HAD NOT LANDED
        YET, not because nothing happened. That is the founding bug of this whole cascade,
        re-committed inside the AC written to fix a bad oracle.

        SECONDARY: the counter comparison is WINDOW-SCOPED, and is admissible ONLY after a
        canary has proven the oracle awake in THIS window.

        🔴 `canary` IS REQUIRED, AND THAT IS THE WHOLE POINT — IT IS THE FIX FOR A DEFECT
        THIS FUNCTION SHIPPED WITH.

        The first version took no canary at all. It ENDED with the words "(admissible ONLY
        because the canary landed first)" — in a PASS it would hand back having verified no
        such thing. Called with `series_before=0, series_after=0` and no canary ever fired,
        it returned PASS and TESTIFIED, in its own detail string, to a precondition nobody
        had established:

            >>> oracle.verify_no_leak_into_default_path( env={}, series_before=0, series_after=0 )
            ( PASS, "...the windowed counter did not increment (admissible ONLY because the
                     canary landed first)." )        # <- NO CANARY WAS EVER FIRED

        The canary discipline was a COMMENT, and the comment was doing the work of a
        MECHANISM. Worse than absent: the function MANUFACTURED AN ATTESTATION. §6a's
        protocol says "ONLY once the canary is visible may you assert the count did not
        increment" — so that ordering is now enforced by the SIGNATURE. You cannot reach a
        PASS on the negative without the receipt that `await_canary()` returns.

        Requires:
            - canary is the series returned by await_canary() — the PROOF the oracle was
              awake in this window. Falsy => the silence is INADMISSIBLE, never PASS.

        Ensures:
            - returns ( Verdict, detail )
            - a tainted process env FAILS with or without a canary: a leak is a POSITIVE
              observation, and a positive needs no proof-of-liveness. Only the SILENCE does.
        """
        leaked = [ key for key in ( "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION",
                                    "ANTHROPIC_VERTEX_PROJECT_ID" ) if env.get( key ) ]
        if leaked:
            return ( Verdict.FAIL,
                     f"a Max session's process env carries {', '.join( leaked )} — the tmux "
                     f"server is TAINTED. This bills a session that NEVER ASKED to be billed, "
                     f"which is worse than mis-billing one that opted in." )

        if not canary:
            return ( Verdict.INADMISSIBLE,
                     "NO CANARY. You are about to read this oracle's SILENCE as proof that no "
                     "Vertex traffic occurred — from an instrument nobody has shown to be AWAKE "
                     "in this window. Cloud Monitoring declares NO ingestDelay, so the counter "
                     "may simply not have landed yet: absence of output read as absence of the "
                     "event. Fire a known call, await_canary() until it appears, and pass the "
                     "series it returns. A null is not evidence until the instrument is proven." )

        if series_after > series_before:
            return ( Verdict.FAIL,
                     f"invocation count rose {series_before} -> {series_after} during a Max "
                     f"session — traffic leaked onto Vertex." )

        return ( Verdict.PASS,
                 "process env is clean of all three Vertex keys, and the windowed counter did "
                 "not increment — admissible BECAUSE a canary landed in this window and the "
                 "oracle was therefore proven awake while it stayed silent." )

    # ── AC-D9a ────────────────────────────────────────────────────────────────────

    def derived_spend( self, start_ts, end_ts, rate_card ):
        """
        AC-D9a — derived spend from token-size metrics x rate card.

        Ensures:
            - returns ( Verdict, usd, detail ). Zero token series is INADMISSIBLE, not $0.00
              — "we measured zero spend" and "we cannot see the spend" are different claims,
              and only one of them is safe to report to the person paying.
        """
        totals = {}
        for metric in TOKEN_METRICS:
            series = self.time_series( metric, start_ts, end_ts )
            totals[ metric ] = sum(
                int( point.get( "value", {} ).get( "int64Value", 0 ) )
                for entry in series for point in entry.get( "points", [] )
            )

        if not any( totals.values() ):
            return ( Verdict.INADMISSIBLE, None,
                     "ZERO token series. That is NOT '$0.00 spent' — it is 'we cannot see the "
                     "spend.' Never report an unmeasured zero as a cost to the person paying "
                     "the bill." )

        usd = sum( totals[ m ] * rate_card[ m ] for m in TOKEN_METRICS )
        return ( Verdict.PASS, usd, f"derived from {totals} x rate card" )


# ── the real transport — built ONLY on explicit request ───────────────────────────

def build_google_auth_transport():                      # pragma: no cover - constructs a live GCP client; unit tests inject a fake transport and never touch the network
    """
    The production transport. Deliberately NOT the default: constructing it acquires ADC.

    Kept out of the unit path entirely — this is the ONE function in this module that can
    reach GCP, and the seat that calls it is the seat holding the authority to spend.
    """
    import google.auth
    import google.auth.transport.requests
    import requests

    credentials, _ = google.auth.default(
        scopes=[ "https://www.googleapis.com/auth/monitoring.read" ]
    )

    def transport( url, params, token ):
        credentials.refresh( google.auth.transport.requests.Request() )
        response = requests.get(
            url, params=params,
            headers={ "Authorization": f"Bearer {credentials.token}" },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    return transport


def _rfc3339( ts ):
    """Seconds-since-epoch -> RFC3339 UTC, the interval format Monitoring expects."""
    import datetime
    return datetime.datetime.fromtimestamp(
        ts, tz=datetime.timezone.utc
    ).strftime( "%Y-%m-%dT%H:%M:%SZ" )


def _is_ok( code ):
    """A Monitoring response_code label is OK when it is a 2xx."""
    return str( code ).startswith( "2" )


def resolve_project_and_region( env=None ):
    """
    Read the project + Vertex region the pilot is configured for. NO fallbacks, no guessing.

    Ensures:
        - returns ( project_id, region )

    Raises:
        - KeyError naming the missing variable — guessing either one would point the oracle
          at the wrong project or the wrong region and produce a confidently wrong verdict
    """
    env = env if env is not None else os.environ
    return ( env[ "LUPIN_GCP_PROJECT_ID" ], env[ "LUPIN_VERTEX_REGION" ] )
