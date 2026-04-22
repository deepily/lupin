#!/usr/bin/env python3
"""
Presentation Generator RENDER-ONLY endpoint smoke test — Tier 2 validation.

Validates the render-only pipeline (Phases 6-8) by submitting an existing
YAML intermediate file. Skips content generation (Phases 1-5, $0 cost).
Tests Marp rendering, visual rendering (Mermaid/Matplotlib/D2), and delivery.

Single-scenario test — finds the latest YAML from a prior full run and
re-renders it. Gate 4 (rendered output review) still fires, so the proxy
is needed.

Scenarios:
    # ID                       Validates
    0 PR_RENDER_ONLY_FAST      job_id prefix, agent_type, fast completion,
                               low cost, slide_count > 0, no stack trace

Usage:
    # Standard (auto-finds latest YAML in test user's output dir)
    python src/tests/smoke/test_presentation_render_only_smoke.py --auto-proxy

    # Explicit YAML path
    python src/tests/smoke/test_presentation_render_only_smoke.py --auto-proxy \
        --yaml-path io/presentations/user@email/2026.04.07-at-16:33-EST-strategy-and-design.yaml

    # Schedule via test-suite endpoint:
    #   POST /api/test-suite/submit
    #   {
    #     "test_types"   : "smoke",
    #     "pytest_args"  : "src/tests/smoke/test_presentation_render_only_smoke.py --auto-proxy",
    #     "scheduled_at" : "2026-04-07T22:00:00-04:00"
    #   }

Requires:
    - Server running on localhost:7999
    - Environment: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
    - PYTHONPATH includes src/
    - LUPIN_ROOT environment variable set
    - At least one prior full-pipeline YAML in io/presentations/{test_user}/

Cost envelope:
    - Render-only: ~$0 (no LLM calls). Cap: $0.10
    - If NanoBanana/Veo fire, Gemini API costs could be non-zero

Created: 2026-04-07 (E2E testing strategy, Session 5946362f)
"""

import argparse
import glob
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

DEFAULT_COST_CAP_USD = 0.10

PID_FILE         = "/tmp/presentation-render-only.pid"
E2E_UI_PID_FILE  = "/tmp/e2e-ui-tests.pid"


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

RENDER_ONLY_SCENARIOS = [
    {
        "id"          : "PR_RENDER_ONLY_FAST",
        "render_only" : True,
        "dry_run"     : False,
        "check"       : "render_quality",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# YAML Auto-Discovery
# ═══════════════════════════════════════════════════════════════════════════════

def _find_latest_yaml( user_email ):
    """
    Find the most recent presentation YAML in the test user's output directory.

    Requires:
        - user_email is a non-empty string
        - LUPIN_ROOT environment variable is set

    Ensures:
        - Returns absolute path to latest .yaml file, or None if none found
    """
    project_root = os.environ.get( "LUPIN_ROOT", "/var/lupin" )
    presentations_dir = os.path.join( project_root, "io", "presentations", user_email )

    if not os.path.isdir( presentations_dir ):
        return None

    yaml_files = glob.glob( os.path.join( presentations_dir, "*.yaml" ) )
    yaml_files += glob.glob( os.path.join( presentations_dir, "*.yml" ) )

    if not yaml_files:
        return None

    # Sort by modification time, newest first
    yaml_files.sort( key=os.path.getmtime, reverse=True )

    return yaml_files[ 0 ]


def _to_relative_path( abs_path ):
    """Convert absolute path to io-relative path for the submit endpoint."""
    project_root = os.environ.get( "LUPIN_ROOT", "/var/lupin" )
    io_prefix = os.path.join( project_root, "io" ) + "/"
    if abs_path.startswith( io_prefix ):
        return abs_path[ len( io_prefix ): ]
    return abs_path


# ═══════════════════════════════════════════════════════════════════════════════
# Coordination / Lockout
# ═══════════════════════════════════════════════════════════════════════════════

def _is_pid_alive( pid ):
    """Check whether a PID is currently alive."""
    try:
        os.kill( pid, 0 )
        return True
    except ( OSError, ProcessLookupError ):
        return False


def _check_overlap_locks():
    """Check for concurrent test runs that would interfere."""
    if os.path.exists( PID_FILE ):
        try:
            with open( PID_FILE ) as f:
                existing_pid = int( f.read().strip() )
            if _is_pid_alive( existing_pid ):
                return False, f"Another render-only run is active (pid={existing_pid}). Remove {PID_FILE} if stale."
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

class PresentationRenderOnlySmokeTest( InteractiveSmokeTest ):
    """
    Render-only endpoint smoke test for Presentation Generator Phases 6-8.

    Submits a render-only job using a pre-existing YAML intermediate, auto-approves
    Gate 4 via proxy, then asserts on the completed job's metadata.

    Requires:
        - Server running on port 7999
        - Valid test credentials in environment
        - Pre-existing YAML in io/presentations/{test_user}/ (or explicit --yaml-path)

    Ensures:
        - Render-only job submitted, Gate 4 auto-approved
        - All 6 post-completion sub-checks pass OR test fails with per-check detail
    """

    TEST_NAME       = "Presentation Generator Render Only"
    SUBMIT_ENDPOINT = "/api/presentation-generator/submit"
    DEFAULT_TIMEOUT = 120  # 2 min — render is fast
    POLL_INTERVAL   = 2
    REQUEST_TIMEOUT = 120
    SCENARIOS       = RENDER_ONLY_SCENARIOS
    PROXY_PROFILE   = "presentation_gates"
    PROXY_STRATEGY  = "llm_script"

    def __init__( self, *args, **kwargs ):
        """Initialize with cost cap and YAML path defaults."""
        super().__init__( *args, **kwargs )
        self._cost_cap_usd = DEFAULT_COST_CAP_USD
        self._yaml_path    = None  # Resolved in pre_run_hook

    # ═══════════════════════════════════════════════════════════════════════
    # Scenario Selection
    # ═══════════════════════════════════════════════════════════════════════

    def get_scenario_indices( self, args ):
        """Always return [ 0 ] — single scenario."""
        return [ 0 ]

    # ═══════════════════════════════════════════════════════════════════════
    # Payload Construction
    # ═══════════════════════════════════════════════════════════════════════

    def get_submit_payload( self, scenario, ws_id ):
        """
        Build the render-only presentation payload.

        Requires:
            - self._yaml_path is resolved (set in pre_run_hook)

        Ensures:
            - Returns payload with render_only=True and YAML source path
        """
        return {
            "source_path" : self._yaml_path,
            "render_only" : True,
            "dry_run"     : False,
        }

    def get_mode_for_scenario( self, scenario ):
        """No mode switching needed."""
        return None

    def _print_scenario_header( self, scenario ):
        """Print scenario details before execution."""
        print( f"  YAML source:        {self._yaml_path}" )
        print( f"  Mode:               RENDER ONLY (Phases 6-8)" )
        print( f"  Cost cap:           ${self._cost_cap_usd:.2f}" )
        print( f"  Proxy profile:      {self.PROXY_PROFILE}" )
        print( f"  Expected duration:  30-60s" )

    # ═══════════════════════════════════════════════════════════════════════
    # Hooks
    # ═══════════════════════════════════════════════════════════════════════

    def build_argparser( self ):
        """Add --yaml-path and --cost-cap-usd flags."""
        parser = super().build_argparser()
        parser.add_argument(
            "--cost-cap-usd",
            type=float,
            default=DEFAULT_COST_CAP_USD,
            help=f"Max cost (USD). Default: ${DEFAULT_COST_CAP_USD:.2f}"
        )
        parser.add_argument(
            "--yaml-path",
            type=str,
            default=None,
            help="Explicit path to YAML intermediate. Default: auto-discover latest."
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=None,
            help="Override poll timeout in seconds. Default: 120."
        )
        return parser

    def pre_run_hook( self, args, headers, ws_id ):
        """
        Resolve YAML path, acquire lock, start proxy.

        Requires:
            - args has yaml_path, cost_cap_usd, auto_proxy fields

        Ensures:
            - self._yaml_path is set to a valid YAML path
            - PID lock acquired
            - Proxy started if --auto-proxy
            - Returns True to proceed, False to abort
        """
        self._cost_cap_usd = getattr( args, "cost_cap_usd", DEFAULT_COST_CAP_USD )
        timeout_override   = getattr( args, "timeout", None )
        if timeout_override is not None:
            self.DEFAULT_TIMEOUT = timeout_override
            self.REQUEST_TIMEOUT = timeout_override

        # Resolve YAML path
        explicit_path = getattr( args, "yaml_path", None )
        if explicit_path:
            self._yaml_path = explicit_path
        else:
            email = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_EMAIL" )
            if email:
                latest = _find_latest_yaml( email )
                if latest:
                    self._yaml_path = latest
                    print( f"\n  Auto-discovered YAML: {os.path.basename( latest )}" )
                else:
                    print( f"\n  ABORT: No YAML files found in io/presentations/{email}/" )
                    print( "  Run a full pipeline test (Tier 3) first to generate a YAML fixture." )
                    return False
            else:
                print( "\n  ABORT: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL not set" )
                return False

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
            self._start_proxy( debug=debug, email=email, password=password )

            if not self.proxy_running:
                print( "  ABORT: Proxy failed to start. Gate 4 would timeout." )
                _remove_pid_file()
                return False
        else:
            print( "\n  WARNING: --auto-proxy not set. Gate 4 will NOT be auto-answered." )

        return True

    def post_run_hook( self, args, headers, results ):
        """Stop proxy, release PID lock."""
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
        Run all post-completion sub-checks for render-only mode.

        Ensures:
            - Returns aggregate PASS if ALL 6 sub-checks pass
            - Returns FAIL with count + details if ANY fail
        """
        checks = [
            ( "job_id_prefix",   self._check_job_id_prefix( job_data ) ),
            ( "agent_type",      self._check_agent_type( job_data ) ),
            ( "fast_completion", self._check_fast_completion( job_data ) ),
            ( "low_cost",        self._check_low_cost( job_data ) ),
            ( "slide_count",     self._check_slide_count( job_data ) ),
            ( "no_stack_trace",  self._check_no_stack_trace( job_data ) ),
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

    def _check_fast_completion( self, job_data ):
        """Verify render completed in under 120 seconds."""
        duration = job_data.get( "duration_seconds" )
        if duration is not None and duration < 120:
            return { "ok": True, "detail": f"duration={duration:.1f}s (fast)" }
        if duration is not None:
            return { "ok": False, "detail": f"duration={duration:.1f}s — render should be <120s" }
        return { "ok": False, "detail": "duration_seconds not set" }

    def _check_low_cost( self, job_data ):
        """Verify cost is near-zero (no LLM content generation)."""
        cost_summary = job_data.get( "cost_summary" )
        if not isinstance( cost_summary, dict ):
            # Render-only may have no cost_summary at all — that's OK
            return { "ok": True, "detail": "no cost_summary (expected for render-only)" }

        total = cost_summary.get( "total_cost_usd", 0 )
        if total <= self._cost_cap_usd:
            return { "ok": True, "detail": f"cost=${total:.4f} <= cap=${self._cost_cap_usd:.2f}" }
        return { "ok": False, "detail": f"cost=${total:.4f} EXCEEDS cap=${self._cost_cap_usd:.2f}" }

    def _check_slide_count( self, job_data ):
        """Verify slide_count > 0 — YAML had slides, render should too."""
        response = job_data.get( "response_text" ) or ""
        artifacts = job_data.get( "artifacts" ) or {}

        slide_count = artifacts.get( "slide_count" )
        if slide_count is not None:
            if int( slide_count ) > 0:
                return { "ok": True, "detail": f"slide_count={slide_count} (from artifacts)" }
            return { "ok": False, "detail": f"slide_count={slide_count} — render produced 0 slides" }

        import re
        match = re.search( r"(\d+)\s+slide", response )
        if match:
            count = int( match.group( 1 ) )
            if count > 0:
                return { "ok": True, "detail": f"slide_count={count} (parsed from response_text)" }
            return { "ok": False, "detail": "slide_count=0 — render produced 0 slides" }

        return { "ok": False, "detail": "slide_count not found in artifacts or response_text" }

    def _check_no_stack_trace( self, job_data ):
        """Verify no stack_trace in job record."""
        trace = job_data.get( "stack_trace" ) or job_data.get( "error" )
        if not trace:
            return { "ok": True, "detail": "no stack_trace in job record" }
        preview = str( trace )[ :80 ].replace( "\n", " " )
        return { "ok": False, "detail": f"stack_trace present: {preview}..." }


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( argv=None ):
    """Backward-compatible entry point for direct invocation."""
    test = PresentationRenderOnlySmokeTest()
    return test.run( argv )


def test_presentation_render_only():
    """Pytest entry point."""
    argv = sys.argv[ 1: ] if len( sys.argv ) > 1 else []
    assert quick_smoke_test( argv )


if __name__ == "__main__":
    success = quick_smoke_test( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
