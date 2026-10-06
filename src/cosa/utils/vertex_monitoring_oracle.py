"""
Cloud Monitoring `PublisherModel` oracle over REST, verifying what Vertex really served.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md §6a
It backs four acceptance checks: region and model, no leak into the default path, and derived spend.

Why REST and not `google.cloud.monitoring_v3`
---------------------------------------------
The client library is not installed on this host. The usual way to test against a missing
library is `pytest.importorskip(...)`, which would turn those four checks into skips. A skip is
invisible in a run of thousands of tests, so a metered-billing pilot would be certified by
assertions that never ran. `google.auth` and `requests` are installed, so the Monitoring v3 REST
surface needs no new dependency. The checks can be written unconditionally, and a missing
instrument fails loudly instead of vanishing into a skip.

Why this oracle at all
----------------------
The Vertex serving path emits it. It needs no setPublisherModelConfig, no BigQuery, no logging
config and no dataset. So it shares no failure mode with the thing it verifies. The BigQuery
oracle fails toward "nothing happened" while money burns. "The toggle never engaged" and "a
region trap burned real money" give the same zero-row reading. An oracle that cannot tell two
opposite worlds apart is not an oracle.

Three rules this module refuses to break
-----------------------------------------
1. Zero rows is not a verdict. It means both "nothing ran" and "it ran and we are blind".
   So there are three verdicts: `PASS`, `FAIL` and `INADMISSIBLE`. Reporting a blind instrument
   as a negative result teaches the team something false.
2. Never spec a latency; spec a canary. Google declares `ingestDelay: None` in the metric
   descriptor, so any fixed wait is an assumption that can go silently wrong when Google changes
   the real delay. There is no sleep constant here. The caller supplies a deadline and the clock
   is injected.
3. A negative assertion is admissible only inside a window where the instrument has been proven
   awake. Fire a known canary, poll until it lands, and only then trust the oracle's silence.

Importing or unit-testing this module makes no GCP call. `transport` and `clock` are injected
and the tests supply fakes. The real transport is built only on explicit request.
"""

import os

# Bound on the Cloud Monitoring read GET (row f6ce66f1).
_MONITORING_READ_TIMEOUT_SECONDS = 30


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
    The three outcomes of a check: `PASS`, `FAIL` and `INADMISSIBLE`.

    `INADMISSIBLE` means the observation cannot tell two opposite worlds apart, so it is not
    an observation. Reporting it as `FAIL` would teach the team something false.
    "Search did not fire" and "we cannot see" are different claims.
    """
    PASS         = "PASS"
    FAIL         = "FAIL"
    INADMISSIBLE = "INADMISSIBLE"


class OracleInadmissible( RuntimeError ):
    """The instrument could not be shown to be awake. Not a failure of the thing under test."""


class MonitoringOracle:
    """
    Read-only Cloud Monitoring client over REST. Makes no call it is not asked to make.

    Requires:
        - project_id is a non-empty string
        - transport( url, params, token ) -> dict, injected (tests pass a fake)
        - clock() -> float seconds, injected (no module-level time import in the hot path)

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
            - returns a list of series dicts (possibly empty, and empty is not a verdict)
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
        Poll until a known-positive series lands, proving the oracle is awake in this window.

        Until the canary is visible the oracle's silence means nothing, so a negative claim is inadmissible.
        There is no default deadline and no sleep constant. Google declares no ingest delay, so a fixed
        wait would go silently wrong the day the real latency changes.

        Requires:
            - is_canary( series ) -> bool identifies the known row we fired ourselves
            - poll() advances the caller's own waiting strategy (injected; may be a no-op)
            - deadline_ts is an absolute bound supplied by the caller

        Ensures:
            - returns the observed canary series when it lands

        Raises:
            - OracleInadmissible if the canary never lands within the bound. Fails loudly.
              The test is inadmissible, not passing: the instrument was never shown to
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
        Check the invocation ran on Vertex in the configured region, on the pinned model.

        This is the only assertion in the design that checks what happened rather than what we
        intended. If a per-model region override fired, the invocation appears under a different
        `location` and this check names the bug. A rejected response code also fails it.

        Ensures:
            - returns ( Verdict, detail ); `INADMISSIBLE` on zero series, never `FAIL`
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
        Check that no Vertex traffic leaked into the default Max path.

        Primary check: the process environment, which has no ingestion lag and cannot false-pass.
        Secondary check: the windowed counter, admissible only with a canary receipt from await_canary().
        The signature requires it because a canary-less version returned `PASS` having verified nothing.

        Requires:
            - canary is the series returned by await_canary(), the proof the oracle was
              awake in this window. Falsy => the silence is `INADMISSIBLE`, never `PASS`.

        Ensures:
            - returns ( Verdict, detail )
            - a tainted process env fails with or without a canary: a leak is a positive
              observation, and a positive needs no proof of liveness. Only the silence does.
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
        Derive spend from the token-size metrics and a rate card.

        Ensures:
            - returns ( Verdict, usd, detail ). Zero token series is `INADMISSIBLE`, not $0.00:
              "we measured zero spend" and "we cannot see the spend" are different claims,
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
    Build the production transport, which acquires Google application default credentials.

    It is not the default, and it is the one function in this module that can reach GCP.
    The seat that calls it is the seat holding the authority to spend.
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
            timeout=_MONITORING_READ_TIMEOUT_SECONDS,
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
    Read the pilot's project and Vertex region from the environment, with no fallbacks.

    Ensures:
        - returns ( project_id, region )

    Raises:
        - KeyError naming the missing variable. Guessing either one would point the oracle
          at the wrong project or region and produce a confidently wrong verdict
    """
    env = env if env is not None else os.environ
    return ( env[ "LUPIN_GCP_PROJECT_ID" ], env[ "LUPIN_VERTEX_REGION" ] )
