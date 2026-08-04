#!/usr/bin/env python3
"""
Presentation Generator LIVE-RUN endpoint smoke test — Phase D verification.

Validates the full HTTP submit-and-poll lifecycle against a running server
with REAL Claude API calls, the 4 orchestrator voice gates, and the full
visual rendering pipeline. Uses the scripted notification proxy (profile:
presentation-gates, strategy: llm_script) to auto-approve all 4 gates.

Single-scenario test — one expensive live job produces one completion record,
which is then validated against N post-completion assertions.

Scenarios:
    # ID                       Validates
    0 PR_LIVE_TIER1_FULL       job_id prefix, agent_type, cost envelope,
                               slide_count > 0, artifacts present, no stack trace,
                               gates fired

Usage:
    # Run with Sonnet (automated/CI default, ~$0.49/run)
    python src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --content-model claude-sonnet-4-6 --cost-cap-usd 2.00

    # Run with Opus (production default, ~$2.43/run)
    python src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --cost-cap-usd 5.00

    # With debug output
    python src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --cost-cap-usd 5.00 --debug --proxy-debug

    # With custom timeout (default 900s)
    python src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --timeout 1200

    # Schedule via test-suite endpoint (from Claude):
    #   POST /api/test-suite/submit
    #   {
    #     "test_types"   : "smoke",
    #     "pytest_args"  : "src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --cost-cap-usd 2.00",
    #     "dry_run"      : false,
    #     "scheduled_at" : "2026-04-05T18:30:00-04:00"
    #   }

Requires:
    - Server running on localhost:7999
    - Environment: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
    - PYTHONPATH includes src/
    - LUPIN_ROOT environment variable set
    - Gemini API key configured in INI (for NanoBanana/Veo if they fire)

Cost envelope (Tier 1 — Marp + Mermaid + Matplotlib + D2):
    - Opus: ~$2.43 per run with 4500-token source doc. Default cap: $5.00
    - Sonnet: ~$0.49 per run (estimated). Cap: $2.00
    - Haiku: DEPRECATED — produced 0 slides in Phase D testing (2026-04-06)
    - If NanoBanana/Veo fire organically from outline generation, cost may exceed cap
      (test will FAIL at PR_COST_ENVELOPE check — this is correct behavior)

Created: 2026-04-05 (Phase D automation, Session 389)
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

# Source research doc the presentation is built FROM. Overridable via env so a
# scheduled test-suite run can target a specific doc (e.g. a user's own research
# report) without editing this file. The env key uses the LUPIN_TEST_ prefix so
# it survives TestSuiteJob's env_vars allowlist (_ENV_VAR_ALLOWED_PREFIXES).
SOURCE_DOC = os.environ.get(
    "LUPIN_TEST_PRESENTATION_SOURCE_DOC",
    "/src/rnd/v0.1.6/2026.03.14-presentation-generator/01-strategy-and-design.md"
)

DEFAULT_COST_CAP_USD = 5.00

PID_FILE         = "/tmp/presentation-live.pid"
E2E_UI_PID_FILE  = "/tmp/e2e-ui-tests.pid"


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

PRESENTATION_LIVE_SCENARIOS = [
    {
        "id"                      : "PR_LIVE_TIER1_FULL",
        "source_path"             : SOURCE_DOC,
        "target_duration_minutes" : 15,
        "audience"                : "general",
        "dry_run"                 : False,
        "check"                   : "full_live",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Coordination / Lockout
# ═══════════════════════════════════════════════════════════════════════════════

def _is_pid_alive( pid ):
    """
    Check whether a PID is currently alive.

    Requires:
        - pid is an integer

    Ensures:
        - Returns True if process exists
        - Returns False if it doesn't or lookup fails
    """
    try:
        os.kill( pid, 0 )
        return True
    except ( OSError, ProcessLookupError ):
        return False


def _check_overlap_locks():
    """
    Check for concurrent test runs that would interfere with this one.

    Ensures:
        - Returns ( ok, message ) — ok=False blocks start
    """
    # Our own PID file
    if os.path.exists( PID_FILE ):
        try:
            with open( PID_FILE ) as f:
                existing_pid = int( f.read().strip() )
            if _is_pid_alive( existing_pid ):
                return False, f"Another presentation-live run is active (pid={existing_pid}). Remove {PID_FILE} if stale."
            else:
                # Stale, clean up
                os.remove( PID_FILE )
        except Exception:
            os.remove( PID_FILE )

    # E2E UI tests (hot-swap collision)
    if os.path.exists( E2E_UI_PID_FILE ):
        try:
            with open( E2E_UI_PID_FILE ) as f:
                e2e_pid = int( f.read().strip() )
            if _is_pid_alive( e2e_pid ):
                return False, f"E2E UI tests are running (pid={e2e_pid}). Hot-swap would collide with live pipeline."
        except Exception:
            pass  # File present but unreadable — warn but proceed

    return True, "OK"


def _write_pid_file():
    """Write current process PID to the lock file."""
    with open( PID_FILE, "w" ) as f:
        f.write( str( os.getpid() ) )


def _remove_pid_file():
    """Remove the lock file if present."""
    if os.path.exists( PID_FILE ):
        try:
            os.remove( PID_FILE )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class PresentationLiveSmokeTest( InteractiveSmokeTest ):
    """
    Live endpoint smoke test for Presentation Generator full pipeline with gates.

    Submits a single live (non-dry-run) presentation generation job, auto-approves
    all 4 orchestrator gates via the scripted notification proxy, then asserts
    on the completed job's metadata: job_id prefix, agent_type, cost envelope,
    required output fields, and clean termination (no stack trace).

    Requires:
        - Server running on port 7999
        - Valid test credentials in environment
        - presentation-gates.json notification proxy script file exists
        - Source document at SOURCE_DOC is readable by the server

    Ensures:
        - Single live job submitted, 4 gates auto-approved
        - All 8 post-completion sub-checks pass OR test fails with per-check detail
    """

    TEST_NAME       = "Presentation Generator Live E2E"
    SUBMIT_ENDPOINT = "/api/presentation-generator/submit"
    # 900s equalled the real ~15-min build time with ZERO margin, so a normal build
    # crossed the boundary and reported a false FAIL (bug e5473a72). Raised to 1800s
    # (2x margin). This number is a FLOOR, not an estimate: only ONE real completed
    # sample exists (job pr-bf7ac6f5, ~15 min, 15-slide deck). The real false-fail fix
    # is _resolve_job_state in live_pipeline_base — on timeout the harness now reports
    # the job's actual state (done/dead/run) instead of a bare "timeout".
    DEFAULT_TIMEOUT = 1800
    POLL_INTERVAL   = 3
    REQUEST_TIMEOUT = 600
    SCENARIOS       = PRESENTATION_LIVE_SCENARIOS
    PROXY_PROFILE   = "presentation_gates"  # underscore form (CLI arg)
    PROXY_STRATEGY  = "llm_script"

    def __init__( self, *args, **kwargs ):
        """Initialize with cost cap and model defaults."""
        super().__init__( *args, **kwargs )
        self._cost_cap_usd   = DEFAULT_COST_CAP_USD
        self._content_model  = None

    # ═══════════════════════════════════════════════════════════════════════
    # Scenario Selection
    # ═══════════════════════════════════════════════════════════════════════

    def get_scenario_indices( self, args ):
        """
        This test has exactly one scenario — always return [ 0 ].

        Requires:
            - args is argparse.Namespace

        Ensures:
            - Returns [ 0 ]
        """
        return [ 0 ]

    # ═══════════════════════════════════════════════════════════════════════
    # Payload Construction
    # ═══════════════════════════════════════════════════════════════════════

    def get_submit_payload( self, scenario, ws_id ):
        """
        Build the live presentation generation payload.

        Requires:
            - scenario is a dict from PRESENTATION_LIVE_SCENARIOS
            - ws_id is the session ID (unused — endpoint doesn't route by WS)

        Ensures:
            - Returns payload with dry_run=False and scenario's audience/duration
        """
        payload = {
            "source_path"             : scenario[ "source_path" ],
            "target_duration_minutes" : scenario.get( "target_duration_minutes", 15 ),
            "audience"                : scenario.get( "audience", "general" ),
            "dry_run"                 : False,
        }
        if self._content_model:
            payload[ "content_model" ] = self._content_model
        return payload

    def get_mode_for_scenario( self, scenario ):
        """
        Presentation Generator uses its own endpoint — no mode switching.

        Ensures:
            - Always returns None
        """
        return None

    def _print_scenario_header( self, scenario ):
        """Print scenario details before execution."""
        print( f"  Source:             {scenario[ 'source_path' ]}" )
        print( f"  Target duration:    {scenario.get( 'target_duration_minutes', 15 )} min" )
        print( f"  Audience:           {scenario.get( 'audience', 'general' )}" )
        print( f"  Mode:               LIVE (dry_run=False)" )
        print( f"  Content model:      {self._content_model or 'INI default (Opus)'}" )
        print( f"  Cost cap:           ${self._cost_cap_usd:.2f}" )
        print( f"  Proxy profile:      {self.PROXY_PROFILE}" )
        print( f"  Expected duration:  5-10 min (includes Claude API calls + 4 gates)" )

    # ═══════════════════════════════════════════════════════════════════════
    # Hooks
    # ═══════════════════════════════════════════════════════════════════════

    def build_argparser( self ):
        """
        Add --cost-cap-usd flag and proxy args to the base parser.

        Ensures:
            - Returns argparse.ArgumentParser with all standard + test-specific flags
        """
        # super().build_argparser() is InteractiveSmokeTest which already
        # calls self.add_proxy_args() — no need to add --auto-proxy ourselves.
        parser = super().build_argparser()
        parser.add_argument(
            "--cost-cap-usd",
            type=float,
            default=DEFAULT_COST_CAP_USD,
            help=f"Max cost (USD). Job FAILS test if exceeded. Default: ${DEFAULT_COST_CAP_USD:.2f}"
        )
        parser.add_argument(
            "--content-model",
            type=str,
            default=None,
            help="Override Claude model (e.g. claude-sonnet-4-6). Default: INI config (Opus)."
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=None,
            help="Override poll timeout in seconds. Default: 900 (15 min, includes test-suite overhead)."
        )
        return parser

    def pre_run_hook( self, args, headers, ws_id ):
        """
        Apply CLI args, acquire lock, start proxy.

        Requires:
            - args is argparse.Namespace with cost_cap_usd + auto_proxy fields

        Ensures:
            - PID lock acquired
            - Proxy subprocess launched
            - Returns True to proceed, False to abort
        """
        # Capture cost cap, model override, and timeout
        self._cost_cap_usd  = getattr( args, "cost_cap_usd", DEFAULT_COST_CAP_USD )
        self._content_model = getattr( args, "content_model", None )
        timeout_override    = getattr( args, "timeout", None )
        if timeout_override is not None:
            self.DEFAULT_TIMEOUT  = timeout_override
            self.REQUEST_TIMEOUT  = timeout_override

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
                print( f"\n  ABORT: Proxy startup failed — live gates would timeout (would 503-cascade)." )
                print( f"  {e}" )
                _remove_pid_file()
                return False
        else:
            # When running under pytest (i.e. scheduled :8000 invocation), there's
            # no human at the UI to approve the 4 gates — the test would burn its
            # full 900s timeout for nothing. Fail fast in <1s so the scheduling
            # bug is loud and visible. CLI dev mode still gets the warning + manual flow.
            if os.environ.get( "PYTEST_CURRENT_TEST" ):
                _remove_pid_file()
                raise RuntimeError(
                    "test_presentation_live_endpoint requires --auto-proxy when invoked under pytest. "
                    "The 4 presentation-gate approvals cannot complete without an auto-answer proxy. "
                    "Re-submit via /api/test-suite/submit with pytest_args including "
                    "'--auto-proxy --cost-cap-usd <N>' (e.g. '--auto-proxy --cost-cap-usd 5.00')."
                )
            print( "\n  WARNING: --auto-proxy not set. Gates will NOT be auto-answered." )
            print( "           Expect 4 manual approvals via notification UI or timeouts." )

        return True

    def post_run_hook( self, args, headers, results ):
        """
        Stop proxy, release PID lock.

        Requires:
            - results is list of result dicts
        """
        try:
            self._stop_proxy()
        finally:
            _remove_pid_file()
            print( f"\n  Lock released: {PID_FILE}" )

    # ═══════════════════════════════════════════════════════════════════════
    # Validation
    # ═══════════════════════════════════════════════════════════════════════

    def validate_result( self, scenario, job_data ):
        """
        Run all post-completion sub-checks against the done-queue job record.

        Requires:
            - scenario is a dict from PRESENTATION_LIVE_SCENARIOS
            - job_data is a dict from the done queue

        Ensures:
            - Returns aggregate PASS if ALL sub-checks pass
            - Returns FAIL with count + details if ANY sub-check fails
        """
        checks = [
            ( "job_id_prefix",   self._check_job_id_prefix( job_data ) ),
            ( "agent_type",      self._check_agent_type( job_data ) ),
            ( "cost_envelope",   self._check_cost_envelope( job_data ) ),
            ( "nonzero_cost",    self._check_nonzero_cost( job_data ) ),
            ( "slide_count",     self._check_slide_count( job_data ) ),
            ( "timestamps",      self._check_timestamps( job_data ) ),
            ( "no_stack_trace",  self._check_no_stack_trace( job_data ) ),
            ( "response_text",   self._check_response_text( job_data ) ),
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
        """Verify job_id starts with 'pr-'."""
        job_id = job_data.get( "job_id", "" )
        if job_id.startswith( "pr-" ):
            return { "ok": True, "detail": f"job_id={job_id[ :20 ]}..." }
        return { "ok": False, "detail": f"expected 'pr-' prefix, got '{job_id[ :10 ]}'" }

    def _check_agent_type( self, job_data ):
        """Verify agent_type == 'presentation'."""
        agent_type = job_data.get( "agent_type", "" )
        if agent_type == "presentation":
            return { "ok": True, "detail": f"agent_type={agent_type}" }
        return { "ok": False, "detail": f"expected 'presentation', got '{agent_type}'" }

    def _check_cost_envelope( self, job_data ):
        """Verify total_cost_usd <= cap."""
        cost_summary = job_data.get( "cost_summary" )
        if not isinstance( cost_summary, dict ):
            return { "ok": False, "detail": f"cost_summary not a dict: {type( cost_summary ).__name__}" }

        total = cost_summary.get( "total_cost_usd", -1 )
        if total <= self._cost_cap_usd:
            return { "ok": True, "detail": f"cost=${total:.4f} <= cap=${self._cost_cap_usd:.2f}" }
        return { "ok": False, "detail": f"cost=${total:.4f} EXCEEDS cap=${self._cost_cap_usd:.2f}" }

    def _check_nonzero_cost( self, job_data ):
        """Verify cost > 0 (proves real Claude calls were made, not silent dry_run)."""
        cost_summary = job_data.get( "cost_summary" ) or {}
        total = cost_summary.get( "total_cost_usd", 0 )
        if total > 0:
            return { "ok": True, "detail": f"cost=${total:.4f} (live API calls confirmed)" }
        return { "ok": False, "detail": f"cost=${total} — no Claude calls? (expected live, got zero-cost)" }

    def _check_slide_count( self, job_data ):
        """Verify slide_count > 0 — pipeline COMPLETED with 0 slides is a quality failure."""
        # Try response_text first (contains "N slides" in the conversational answer)
        response = job_data.get( "response_text" ) or ""
        artifacts = job_data.get( "artifacts" ) or {}

        # Check artifacts for explicit slide count
        slide_count = artifacts.get( "slide_count" )
        if slide_count is not None:
            if int( slide_count ) > 0:
                return { "ok": True, "detail": f"slide_count={slide_count} (from artifacts)" }
            return { "ok": False, "detail": f"slide_count={slide_count} — pipeline completed but generated 0 slides" }

        # Fallback: parse "N slides" from response_text
        import re
        match = re.search( r"(\d+)\s+slide", response )
        if match:
            count = int( match.group( 1 ) )
            if count > 0:
                return { "ok": True, "detail": f"slide_count={count} (parsed from response_text)" }
            return { "ok": False, "detail": f"slide_count=0 — pipeline completed but generated 0 slides" }

        # No slide count found anywhere — warn but don't fail (might be dry-run)
        return { "ok": False, "detail": "slide_count not found in artifacts or response_text" }

    def _check_timestamps( self, job_data ):
        """Verify started_at and completed_at are set."""
        started   = job_data.get( "started_at" )
        completed = job_data.get( "completed_at" )
        if started and completed:
            duration = job_data.get( "duration_seconds", "?" )
            return { "ok": True, "detail": f"started={started[ :19 ]}, duration={duration}s" }
        missing = [ k for k, v in [ ( "started_at", started ), ( "completed_at", completed ) ] if not v ]
        return { "ok": False, "detail": f"missing: {', '.join( missing )}" }

    def _check_no_stack_trace( self, job_data ):
        """Verify no stack_trace in job record (indicates silent exception)."""
        trace = job_data.get( "stack_trace" ) or job_data.get( "error" )
        if not trace:
            return { "ok": True, "detail": "no stack_trace in job record" }
        preview = str( trace )[ :80 ].replace( "\n", " " )
        return { "ok": False, "detail": f"stack_trace present: {preview}..." }

    def _check_response_text( self, job_data ):
        """Verify response_text is non-empty."""
        response = job_data.get( "response_text" ) or ""
        if response.strip():
            return { "ok": True, "detail": f"response_text: '{response[ :50 ]}...'" }
        return { "ok": False, "detail": "response_text is empty or None" }


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( argv=None ):
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - Server running on localhost:7999
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD set
        - presentation-gates.json script file exists

    Ensures:
        - Returns True if all sub-checks pass, False otherwise
    """
    test = PresentationLiveSmokeTest()
    return test.run( argv )


def test_presentation_live_endpoint():
    """
    Pytest entry point. Forwards any sys.argv beyond the script name to the
    argparser so `pytest_args` from the test-suite scheduling endpoint can
    pass --auto-proxy, --cost-cap-usd, etc.
    """
    # When invoked by the test-suite agentic job, pytest_args are passed as
    # sys.argv. Filter out pytest's own args (starting with the test file path).
    argv = sys.argv[ 1: ] if len( sys.argv ) > 1 else []
    assert quick_smoke_test( argv )


if __name__ == "__main__":
    success = quick_smoke_test( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
