#!/usr/bin/env python3
"""
Research-to-Presentation LIVE chain endpoint smoke test — Tier 5 validation.

Validates the full chain: Deep Research generates a report, then Presentation
Generator auto-chains to produce slides from that report. Real Claude API calls,
real orchestrator gates, real artifact generation.

Single-scenario test — one expensive chained job produces a research report AND
a slide deck, which are then validated against N post-completion assertions.

Scenarios:
    # ID                       Validates
    0 R2P_LIVE_FULL_CHAIN      job_id prefix, agent_type, cost envelope,
                               research report exists, slide_count > 0,
                               timestamps, no stack trace, response text

Usage:
    # Standard (~$5-10, ~30min)
    python src/tests/smoke/test_research_to_presentation_live_smoke.py --auto-proxy --cost-cap-usd 10.00

    # Schedule via test-suite endpoint:
    #   POST /api/test-suite/submit
    #   {
    #     "test_types"   : "smoke",
    #     "pytest_args"  : "src/tests/smoke/test_research_to_presentation_live_smoke.py --auto-proxy --cost-cap-usd 10.00",
    #     "scheduled_at" : "2026-04-07T23:00:00-04:00"
    #   }

Requires:
    - Server running on localhost:7999
    - Environment: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
    - PYTHONPATH includes src/
    - LUPIN_ROOT environment variable set

Cost envelope:
    - Deep Research (~$3-7) + Presentation (~$0.46-2.43) = ~$5-10 total
    - Default cap: $10.00
    - Budget param limits DR spend

Created: 2026-04-07 (E2E testing strategy, Session 5946362f)
"""

import argparse
import os
import sys

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

from tests.smoke.utilities.interactive_smoke_test import InteractiveSmokeTest


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_COST_CAP_USD = 10.00

PID_FILE         = "/tmp/r2p-live.pid"
E2E_UI_PID_FILE  = "/tmp/e2e-ui-tests.pid"


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

R2P_LIVE_SCENARIOS = [
    {
        "id"                      : "R2P_LIVE_FULL_CHAIN",
        "query"                   : "Explain the three-act narrative structure for technical presentations",
        "budget"                  : 3.0,
        "target_duration_minutes" : 10,
        "audience"                : "general",
        "dry_run"                 : False,
        "check"                   : "chain_complete",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Coordination / Lockout
# ═══════════════════════════════════════════════════════════════════════════════

def _is_pid_alive( pid ):
    try:
        os.kill( pid, 0 )
        return True
    except ( OSError, ProcessLookupError ):
        return False


def _check_overlap_locks():
    if os.path.exists( PID_FILE ):
        try:
            with open( PID_FILE ) as f:
                existing_pid = int( f.read().strip() )
            if _is_pid_alive( existing_pid ):
                return False, f"Another R2P run is active (pid={existing_pid}). Remove {PID_FILE} if stale."
            else:
                os.remove( PID_FILE )
        except Exception:
            os.remove( PID_FILE )

    if os.path.exists( E2E_UI_PID_FILE ):
        try:
            with open( E2E_UI_PID_FILE ) as f:
                e2e_pid = int( f.read().strip() )
            if _is_pid_alive( e2e_pid ):
                return False, f"E2E UI tests are running (pid={e2e_pid}). Hot-swap would collide."
        except Exception:
            pass

    return True, "OK"


def _write_pid_file():
    with open( PID_FILE, "w" ) as f:
        f.write( str( os.getpid() ) )


def _remove_pid_file():
    if os.path.exists( PID_FILE ):
        try:
            os.remove( PID_FILE )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class ResearchToPresentationLiveSmokeTest( InteractiveSmokeTest ):
    """
    Live chain test: Deep Research → Presentation Generator.

    Submits a chained R2P job with real API calls, auto-approves all DR and PR
    gates via proxy, then validates both research report and presentation output.

    Requires:
        - Server running on port 7999
        - Valid test credentials
        - research-to-presentation-gates.json proxy script

    Ensures:
        - Chained job submitted, all gates auto-approved
        - All 9 post-completion sub-checks pass OR test fails with per-check detail
    """

    TEST_NAME       = "Research to Presentation Live Chain"
    SUBMIT_ENDPOINT = "/api/deep-research-to-presentation/submit"
    DEFAULT_TIMEOUT = 2400  # 40 min (DR ~15min + PR ~8min + overhead)
    POLL_INTERVAL   = 5
    REQUEST_TIMEOUT = 2400
    SCENARIOS       = R2P_LIVE_SCENARIOS
    PROXY_PROFILE   = "research_to_presentation_gates"
    PROXY_STRATEGY  = "llm_script"

    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        self._cost_cap_usd = DEFAULT_COST_CAP_USD
        self._lead_model   = None

    # ═══════════════════════════════════════════════════════════════════════
    # Scenario Selection
    # ═══════════════════════════════════════════════════════════════════════

    def get_scenario_indices( self, args ):
        return [ 0 ]

    # ═══════════════════════════════════════════════════════════════════════
    # Payload Construction
    # ═══════════════════════════════════════════════════════════════════════

    def get_submit_payload( self, scenario, ws_id ):
        """Build the R2P chain payload."""
        payload = {
            "query"                   : scenario[ "query" ],
            "budget"                  : scenario.get( "budget", 3.0 ),
            "target_duration_minutes" : scenario.get( "target_duration_minutes", 10 ),
            "audience"                : scenario.get( "audience", "general" ),
            "dry_run"                 : False,
        }
        if self._lead_model:
            payload[ "lead_model" ] = self._lead_model
        return payload

    def get_mode_for_scenario( self, scenario ):
        return None

    def _print_scenario_header( self, scenario ):
        print( f"  Query:              {scenario[ 'query' ]}" )
        print( f"  DR Budget:          ${scenario.get( 'budget', 3.0 ):.2f}" )
        print( f"  Target duration:    {scenario.get( 'target_duration_minutes', 10 )} min" )
        print( f"  Audience:           {scenario.get( 'audience', 'general' )}" )
        print( f"  Mode:               LIVE CHAIN (DR → PR)" )
        print( f"  DR lead model:      {self._lead_model or 'INI default'}" )
        print( f"  Cost cap:           ${self._cost_cap_usd:.2f}" )
        print( f"  Proxy profile:      {self.PROXY_PROFILE}" )
        print( f"  Expected duration:  20-35 min" )

    # ═══════════════════════════════════════════════════════════════════════
    # Hooks
    # ═══════════════════════════════════════════════════════════════════════

    def build_argparser( self ):
        parser = super().build_argparser()
        parser.add_argument(
            "--cost-cap-usd",
            type=float,
            default=DEFAULT_COST_CAP_USD,
            help=f"Max total cost (USD) for DR + PR combined. Default: ${DEFAULT_COST_CAP_USD:.2f}"
        )
        parser.add_argument(
            "--lead-model",
            type=str,
            default=None,
            help="Override DR lead model (e.g. claude-haiku-4-5 for cheap testing). Default: INI config."
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=None,
            help="Override poll timeout in seconds. Default: 2400 (40 min)."
        )
        return parser

    def pre_run_hook( self, args, headers, ws_id ):
        self._cost_cap_usd = getattr( args, "cost_cap_usd", DEFAULT_COST_CAP_USD )
        self._lead_model   = getattr( args, "lead_model", None )
        timeout_override   = getattr( args, "timeout", None )
        if timeout_override is not None:
            self.DEFAULT_TIMEOUT = timeout_override
            self.REQUEST_TIMEOUT = timeout_override

        # Overlap guard
        ok, msg = _check_overlap_locks()
        if not ok:
            print( f"\n  ABORT: {msg}" )
            return False

        _write_pid_file()
        print( f"\n  Lock acquired: {PID_FILE} (pid={os.getpid()})" )

        # Start proxy
        if getattr( args, "auto_proxy", False ):
            debug    = getattr( args, "proxy_debug", False )
            email    = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_EMAIL" )
            password = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_PASSWORD" )
            try:
                self._start_proxy( debug=debug, email=email, password=password )
            except RuntimeError as e:
                print( f"\n  ABORT: Proxy startup failed — DR/PR gates would timeout (would 503-cascade)." )
                print( f"  {e}" )
                _remove_pid_file()
                return False
        else:
            # When running under pytest (i.e. scheduled :8000 invocation), there's
            # no human at the UI to approve the gates — the test would burn its
            # full 2400s timeout for nothing. Fail fast in <1s so the scheduling
            # bug is loud and visible. CLI dev mode still gets the warning + manual flow.
            if os.environ.get( "PYTEST_CURRENT_TEST" ):
                _remove_pid_file()
                raise RuntimeError(
                    "test_research_to_presentation_live requires --auto-proxy when invoked under pytest. "
                    "The DR + PR gate approvals cannot complete without an auto-answer proxy. "
                    "Re-submit via /api/test-suite/submit with pytest_args including "
                    "'--auto-proxy --cost-cap-usd <N>' (e.g. '--auto-proxy --cost-cap-usd 10.00')."
                )
            print( "\n  WARNING: --auto-proxy not set. Gates will NOT be auto-answered." )

        return True

    def post_run_hook( self, args, headers, results ):
        try:
            self._stop_proxy()
        finally:
            _remove_pid_file()
            print( f"\n  Lock released: {PID_FILE}" )

    # ═══════════════════════════════════════════════════════════════════════
    # Validation
    # ═══════════════════════════════════════════════════════════════════════

    def validate_result( self, scenario, job_data ):
        """Run all 9 post-completion sub-checks for the R2P chain."""
        checks = [
            ( "job_id_prefix",    self._check_job_id_prefix( job_data ) ),
            ( "agent_type",       self._check_agent_type( job_data ) ),
            ( "cost_envelope",    self._check_cost_envelope( job_data ) ),
            ( "nonzero_cost",     self._check_nonzero_cost( job_data ) ),
            ( "research_report",  self._check_research_report( job_data ) ),
            ( "slide_count",      self._check_slide_count( job_data ) ),
            ( "timestamps",       self._check_timestamps( job_data ) ),
            ( "no_stack_trace",   self._check_no_stack_trace( job_data ) ),
            ( "response_text",    self._check_response_text( job_data ) ),
        ]

        print( "" )
        print( "  Sub-checks:" )
        for name, result in checks:
            status_marker = "PASS" if result[ "ok" ] else "FAIL"
            print( f"    [{status_marker}] {name:20s} {result[ 'detail' ]}" )

        failures = [ ( name, r ) for name, r in checks if not r[ "ok" ] ]
        response_preview = ( job_data.get( "response_text" ) or "" )[ :80 ]

        if failures:
            details = "; ".join( f"{name}: {r[ 'detail' ]}" for name, r in failures )
            return {
                "status"         : "fail",
                "answer_preview" : response_preview,
                "details"        : f"{len( failures )}/{len( checks )} checks failed: {details}",
            }

        return {
            "status"         : "pass",
            "answer_preview" : response_preview,
            "details"        : f"All {len( checks )} sub-checks passed",
        }

    def _check_job_id_prefix( self, job_data ):
        job_id = job_data.get( "job_id", "" )
        if job_id.startswith( "rx-" ):
            return { "ok": True, "detail": f"job_id={job_id[ :20 ]}..." }
        return { "ok": False, "detail": f"expected 'rx-' prefix, got '{job_id[ :10 ]}'" }

    def _check_agent_type( self, job_data ):
        agent_type = job_data.get( "agent_type", "" )
        if agent_type == "research_to_presentation":
            return { "ok": True, "detail": f"agent_type={agent_type}" }
        return { "ok": False, "detail": f"expected 'research_to_presentation', got '{agent_type}'" }

    def _check_cost_envelope( self, job_data ):
        cost_summary = job_data.get( "cost_summary" )
        if not isinstance( cost_summary, dict ):
            return { "ok": False, "detail": f"cost_summary not a dict: {type( cost_summary ).__name__}" }
        total = cost_summary.get( "total_cost_usd", -1 )
        if total <= self._cost_cap_usd:
            return { "ok": True, "detail": f"cost=${total:.4f} <= cap=${self._cost_cap_usd:.2f}" }
        return { "ok": False, "detail": f"cost=${total:.4f} EXCEEDS cap=${self._cost_cap_usd:.2f}" }

    def _check_nonzero_cost( self, job_data ):
        cost_summary = job_data.get( "cost_summary" ) or {}
        total = cost_summary.get( "total_cost_usd", 0 )
        if total > 0:
            return { "ok": True, "detail": f"cost=${total:.4f} (live API calls confirmed)" }
        return { "ok": False, "detail": f"cost=${total} — no API calls? (expected live chain)" }

    def _check_research_report( self, job_data ):
        """Verify deep research report was generated."""
        artifacts = job_data.get( "artifacts" ) or {}
        report_path = artifacts.get( "research_report_path" ) or artifacts.get( "report_path" )
        if report_path:
            return { "ok": True, "detail": f"report_path={os.path.basename( str( report_path ) )}" }
        # Fallback: check response_text for research keywords
        response = job_data.get( "response_text" ) or ""
        if "research" in response.lower() and "presentation" in response.lower():
            return { "ok": True, "detail": "research + presentation keywords in response_text" }
        return { "ok": False, "detail": "no research_report_path in artifacts" }

    def _check_slide_count( self, job_data ):
        response = job_data.get( "response_text" ) or ""
        artifacts = job_data.get( "artifacts" ) or {}
        slide_count = artifacts.get( "slide_count" )
        if slide_count is not None:
            if int( slide_count ) > 0:
                return { "ok": True, "detail": f"slide_count={slide_count} (from artifacts)" }
            return { "ok": False, "detail": f"slide_count={slide_count} — chain produced 0 slides" }
        import re
        match = re.search( r"(\d+)\s+slide", response )
        if match:
            count = int( match.group( 1 ) )
            if count > 0:
                return { "ok": True, "detail": f"slide_count={count} (parsed from response_text)" }
            return { "ok": False, "detail": "slide_count=0 in response_text" }
        return { "ok": False, "detail": "slide_count not found in artifacts or response_text" }

    def _check_timestamps( self, job_data ):
        started   = job_data.get( "started_at" )
        completed = job_data.get( "completed_at" )
        if started and completed:
            duration = job_data.get( "duration_seconds", "?" )
            return { "ok": True, "detail": f"started={started[ :19 ]}, duration={duration}s" }
        missing = [ k for k, v in [ ( "started_at", started ), ( "completed_at", completed ) ] if not v ]
        return { "ok": False, "detail": f"missing: {', '.join( missing )}" }

    def _check_no_stack_trace( self, job_data ):
        trace = job_data.get( "stack_trace" ) or job_data.get( "error" )
        if not trace:
            return { "ok": True, "detail": "no stack_trace in job record" }
        preview = str( trace )[ :80 ].replace( "\n", " " )
        return { "ok": False, "detail": f"stack_trace present: {preview}..." }

    def _check_response_text( self, job_data ):
        response = job_data.get( "response_text" ) or ""
        if response.strip():
            return { "ok": True, "detail": f"response_text: '{response[ :50 ]}...'" }
        return { "ok": False, "detail": "response_text is empty or None" }


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( argv=None ):
    test = ResearchToPresentationLiveSmokeTest()
    return test.run( argv )


def test_research_to_presentation_live():
    """Pytest entry point."""
    argv = sys.argv[ 1: ] if len( sys.argv ) > 1 else []
    assert quick_smoke_test( argv )


if __name__ == "__main__":
    success = quick_smoke_test( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
