#!/usr/bin/env python3
"""
Base class for live pipeline smoke tests.

Extracts all duplicated infrastructure (authentication, session resolution,
submit-and-poll, answer validation, results table) from the calculator,
CRUD, and expeditor live pipeline tests into a single reusable base class.

Subclasses define a SCENARIOS list and override hooks for:
- get_scenario_indices( args ) — CLI-driven scenario selection
- get_mode_for_scenario( scenario ) — per-scenario mode switching
- validate_result( scenario, job_data ) — custom validation logic
- get_submit_payload( scenario, ws_id ) — custom request body
- get_submit_endpoint() — endpoint URL (default: /api/push)

Usage:
    class MyPipelineTest( LivePipelineTestBase ):
        TEST_NAME       = "My Agent"
        SCENARIOS       = [ { "id": "TEST_1", "query": "...", ... } ]
        DEFAULT_TIMEOUT = 120

        def get_scenario_indices( self, args ):
            return list( range( len( self.SCENARIOS ) ) )

    if __name__ == "__main__":
        test = MyPipelineTest()
        success = test.run( sys.argv[ 1: ] )
        sys.exit( 0 if success else 1 )

Created: 2026-02-13
"""

import argparse
import os
import sys
import time
import traceback

import requests

try:
    import cosa.utils.util as cu
except ImportError:
    cu = None

try:
    import pytest as _pytest
except ImportError:
    _pytest = None


class LivePipelineTestBase:
    """
    Base class for live pipeline smoke tests.

    Requires:
        - Subclass defines SCENARIOS (list of scenario dicts)
        - Subclass defines TEST_NAME (str) for display purposes
        - Server running on BASE_URL

    Ensures:
        - Provides common auth, session, mode, polling, validation, and reporting
        - Subclasses only need to define scenarios and override hooks
    """

    # ═══════════════════════════════════════════════════════════════════════
    # Subclass configuration — override these in your test class
    # ═══════════════════════════════════════════════════════════════════════

    TEST_NAME       = "Live Pipeline"
    SCENARIOS       = []
    BASE_URL        = "http://localhost:7999"
    DEFAULT_TIMEOUT = 120
    POLL_INTERVAL   = 2
    REQUEST_TIMEOUT = 60
    SUBMIT_ENDPOINT = "/api/push"

    # Credential env var prefix — override for tests using different accounts
    CREDENTIAL_ENV_PREFIX = "LUPIN_TEST_INTERACTIVE_MOCK_JOBS"

    # ═══════════════════════════════════════════════════════════════════════
    # Authentication
    # ═══════════════════════════════════════════════════════════════════════

    def _get_credentials( self ):
        """
        Get test credentials from environment.

        Requires:
            - Environment variables {CREDENTIAL_ENV_PREFIX}_EMAIL and _PASSWORD are set

        Ensures:
            - Returns ( email, password ) tuple
            - Returns ( None, None ) if no credentials found
        """
        email    = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_EMAIL" )
        password = os.environ.get( f"{self.CREDENTIAL_ENV_PREFIX}_PASSWORD" )

        if email and password:
            return email, password

        return None, None

    def _login( self, email, password ):
        """
        Authenticate and return ( token, headers ) tuple.

        Requires:
            - email and password are non-empty strings
            - Server running on BASE_URL

        Ensures:
            - Returns ( token_str, headers_dict ) on success
            - Returns ( None, None ) on failure with remediation instructions
        """
        login_resp = requests.post(
            f"{self.BASE_URL}/auth/login",
            json={ "email": email, "password": password },
            timeout=30
        )

        if login_resp.status_code != 200:
            print( f"  Login failed: {login_resp.status_code}" )
            print( f"  Response: {login_resp.text[ :200 ]}" )
            print()
            print( "  Possible fixes:" )
            print( "  1. Account may not exist. Register it:" )
            print( f'     curl -X POST "{self.BASE_URL}/auth/register" \\' )
            print( f'       -H "Content-Type: application/json" \\' )
            print( f'       -d \'{{"email": "{email}", "password": "<your-password>"}}\'' )
            print( "  2. Password may be wrong. Check your env vars:" )
            print( f"     {self.CREDENTIAL_ENV_PREFIX}_EMAIL / {self.CREDENTIAL_ENV_PREFIX}_PASSWORD" )
            return None, None

        token   = login_resp.json()[ "tokens" ][ "access_token" ]
        headers = { "Authorization": f"Bearer {token}" }
        return token, headers

    # ═══════════════════════════════════════════════════════════════════════
    # Session Resolution
    # ═══════════════════════════════════════════════════════════════════════

    def _get_websocket_session_id( self, headers ):
        """
        Get a valid WebSocket session ID for API calls.

        Requires:
            - headers contains valid auth token

        Ensures:
            - Returns session_id string on success
            - Returns "smoke-test-session" as fallback
        """
        resp = requests.get(
            f"{self.BASE_URL}/api/debug/websocket-state",
            headers=headers,
            timeout=10
        )

        if resp.status_code != 200:
            print( f"  WebSocket state endpoint failed: {resp.status_code}" )
            return "smoke-test-session"

        data     = resp.json()
        sessions = data.get( "sessions", {} )

        if sessions:
            session_id = list( sessions.keys() )[ 0 ]
            return session_id

        return "smoke-test-session"

    # ═══════════════════════════════════════════════════════════════════════
    # Mode Management
    # ═══════════════════════════════════════════════════════════════════════

    def _set_mode( self, headers, mode_name ):
        """
        Set user mode for direct routing.

        Requires:
            - headers contains valid auth token
            - mode_name is a valid mode string

        Ensures:
            - Returns True if mode set successfully
            - Returns False on failure
        """
        resp = requests.post(
            f"{self.BASE_URL}/api/mode/current",
            json={ "mode": mode_name },
            headers=headers,
            timeout=10
        )

        if resp.status_code != 200:
            print( f"  Set mode failed: {resp.status_code} - {resp.text[ :200 ]}" )
            return False

        data = resp.json()
        print( f"  Mode set to: {data.get( 'display_name', 'unknown' )} (was: {data.get( 'previous_mode', 'system' )})" )
        return True

    def _clear_mode( self, headers ):
        """
        Clear user mode back to system.

        Requires:
            - headers contains valid auth token

        Ensures:
            - Mode is cleared regardless of success/failure
        """
        try:
            requests.post(
                f"{self.BASE_URL}/api/mode/current",
                json={ "mode": None },
                headers=headers,
                timeout=10
            )
        except Exception:
            pass  # Best effort

    # ═══════════════════════════════════════════════════════════════════════
    # Similarity Confirmation Toggle
    # ═══════════════════════════════════════════════════════════════════════

    def _disable_similarity_confirmation( self, headers ):
        """
        Save current similarity_confirmation_enabled state and disable it.

        Requires:
            - headers contains valid auth token

        Ensures:
            - Returns True if successfully disabled (and saves original value)
            - Returns False on failure (original value unchanged)
        """
        try:
            # GET current value
            resp = requests.get(
                f"{self.BASE_URL}/api/config/similarity-confirmation",
                headers=headers,
                timeout=10
            )
            if resp.status_code != 200:
                print( f"  WARNING: Could not read similarity confirmation state: {resp.status_code}" )
                return False

            self._similarity_confirmation_original = resp.json().get( "enabled", True )

            # POST disable
            resp = requests.post(
                f"{self.BASE_URL}/api/config/similarity-confirmation",
                json={ "enabled": False },
                headers=headers,
                timeout=10
            )
            if resp.status_code != 200:
                print( f"  WARNING: Could not disable similarity confirmation: {resp.status_code}" )
                return False

            print( f"  Similarity confirmation disabled (was: {self._similarity_confirmation_original})" )
            return True

        except Exception as e:
            print( f"  WARNING: Failed to disable similarity confirmation: {e}" )
            return False

    def _restore_similarity_confirmation( self, headers ):
        """
        Restore similarity_confirmation_enabled to its original value.

        Requires:
            - headers contains valid auth token
            - _similarity_confirmation_original was set by _disable_similarity_confirmation

        Ensures:
            - Config key restored to its pre-test value
        """
        try:
            original = getattr( self, "_similarity_confirmation_original", True )
            requests.post(
                f"{self.BASE_URL}/api/config/similarity-confirmation",
                json={ "enabled": original },
                headers=headers,
                timeout=10
            )
            print( f"  Similarity confirmation restored to: {original}" )
        except Exception as e:
            print( f"  WARNING: Failed to restore similarity confirmation: {e}" )

    # ═══════════════════════════════════════════════════════════════════════
    # Submit and Poll
    # ═══════════════════════════════════════════════════════════════════════

    def get_submit_endpoint( self ):
        """
        Return the API endpoint for submitting scenarios.

        Ensures:
            - Returns URL string (default: /api/push)
        """
        return self.SUBMIT_ENDPOINT

    def get_submit_payload( self, scenario, ws_id ):
        """
        Build the JSON payload for submitting a scenario.

        Requires:
            - scenario is a dict from SCENARIOS
            - ws_id is a valid session ID

        Ensures:
            - Returns dict suitable for requests.post( json=... )

        Override this in subclasses with different payload shapes.
        """
        return {
            "question"     : scenario[ "query" ],
            "websocket_id" : ws_id,
        }

    def get_submit_headers( self, headers, ws_id ):
        """
        Build request headers for submit call.

        Requires:
            - headers contains valid auth token
            - ws_id is a valid session ID

        Ensures:
            - Returns headers dict with session ID
        """
        return { **headers, "X-Session-ID": ws_id }

    def _submit_and_wait( self, scenario, headers, ws_id, timeout=None ):
        """
        Submit a question and poll the done queue for completion.

        Requires:
            - scenario is a dict from SCENARIOS
            - headers contains valid auth token
            - ws_id is a valid session ID

        Ensures:
            - Returns ( job_metadata_dict, error_msg ) on completion
            - Returns ( None, error_msg ) on failure or timeout
        """
        if timeout is None:
            timeout = scenario.get( "timeout", self.DEFAULT_TIMEOUT )

        endpoint    = self.get_submit_endpoint()
        payload     = self.get_submit_payload( scenario, ws_id )
        req_headers = self.get_submit_headers( headers, ws_id )

        # Submit
        try:
            resp = requests.post(
                f"{self.BASE_URL}{endpoint}",
                json=payload,
                headers=req_headers,
                timeout=self.REQUEST_TIMEOUT
            )
        except requests.exceptions.Timeout:
            return None, f"Submit timed out after {self.REQUEST_TIMEOUT}s"
        except Exception as e:
            return None, f"Submit error: {e}"

        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[ :200 ]}"

        push_data = resp.json()
        job_id    = push_data.get( "job_id" )

        if not job_id:
            return None, f"No job_id in push response: {push_data}"

        print( f"    Submitted, job_id={job_id}, polling (timeout={timeout}s)..." )

        # Poll done queue
        elapsed = 0
        while elapsed < timeout:
            try:
                done_resp = requests.get(
                    f"{self.BASE_URL}/api/get-queue/done",
                    headers=headers,
                    timeout=30
                )

                if done_resp.status_code == 200:
                    done_data = done_resp.json()
                    jobs      = done_data.get( "done_jobs_metadata", [] )

                    for job in jobs:
                        if job.get( "job_id" ) == job_id:
                            return job, None

            except Exception as e:
                print( f"    Poll error: {e}" )

            time.sleep( self.POLL_INTERVAL )
            elapsed += self.POLL_INTERVAL

        return None, f"Timeout after {timeout}s waiting for job_id={job_id}"

    # ═══════════════════════════════════════════════════════════════════════
    # Validation
    # ═══════════════════════════════════════════════════════════════════════

    def _check_answer( self, answer_text, expected_keywords ):
        """
        Check if the answer contains any of the expected keywords.

        Requires:
            - answer_text is a string (may be None)
            - expected_keywords is a non-empty list of strings

        Ensures:
            - Returns ( True, matched_keyword ) if any keyword found
            - Returns ( False, None ) if no keyword found
        """
        if not answer_text:
            return False, None

        answer_lower = answer_text.lower()
        for keyword in expected_keywords:
            if keyword.lower() in answer_lower:
                return True, keyword

        return False, None

    # ═══════════════════════════════════════════════════════════════════════
    # Reporting
    # ═══════════════════════════════════════════════════════════════════════

    def get_table_columns( self ):
        """
        Return column definitions for the results table.

        Ensures:
            - Returns list of ( header, width, key ) tuples
        """
        return [
            ( "#",              4,  None ),
            ( "Test ID",        18, "id" ),
            ( "Status",         8,  "status" ),
            ( "Answer Preview", 36, "answer_preview" ),
            ( "Details",        0,  "details" ),
        ]

    def _print_results_table( self, results ):
        """
        Print a formatted summary table of all scenario results.

        Requires:
            - results is a list of dicts with keys matching get_table_columns()

        Ensures:
            - Prints tabular summary to console
        """
        columns   = self.get_table_columns()
        total_w   = max( 90, sum( c[ 1 ] for c in columns ) + 10 )
        header    = "  "
        separator = "-" * total_w

        for col_name, width, _ in columns:
            if width > 0:
                header += f"{col_name:<{width}} "
            else:
                header += col_name

        print( "\n" + "=" * total_w )
        print( header )
        print( separator )

        for i, r in enumerate( results, 1 ):
            status     = r.get( "status", "fail" )
            status_txt = "PASS" if status == "pass" else "FAIL" if status == "fail" else status.upper()
            icon       = "+" if status == "pass" else "-"

            row = f"  {icon} {i:<3} "
            for col_name, width, key in columns:
                if key is None:
                    continue
                val = str( r.get( key, "" ) )
                if key == "status":
                    val = status_txt
                if key == "answer_preview":
                    val = val[ :width - 2 ] if width > 2 else val
                if width > 0:
                    row += f"{val:<{width}} "
                else:
                    row += val

            print( row )

        print( "=" * total_w )

        passed = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed = sum( 1 for r in results if r[ "status" ] == "fail" )
        other  = len( results ) - passed - failed

        summary = f"\n  Total: {passed} passed, {failed} failed"
        if other > 0:
            summary += f", {other} other"
        summary += f" out of {len( results )}"
        print( summary )
        print( f"  Overall: {'PASS' if failed == 0 and other == 0 else 'FAIL'}" )

    # ═══════════════════════════════════════════════════════════════════════
    # Hooks — override in subclasses
    # ═══════════════════════════════════════════════════════════════════════

    def get_scenario_indices( self, args ):
        """
        Return list of scenario indices to run based on CLI args.

        Requires:
            - args is an argparse.Namespace

        Ensures:
            - Returns list of int indices into self.SCENARIOS

        Override in subclass for custom selection logic.
        """
        return list( range( len( self.SCENARIOS ) ) )

    def get_mode_for_scenario( self, scenario ):
        """
        Return the mode to set for this scenario, or None for no mode switching.

        Requires:
            - scenario is a dict from SCENARIOS

        Ensures:
            - Returns mode string or None

        Override in subclass for mode-switching tests.
        """
        return None

    def validate_result( self, scenario, job_data ):
        """
        Validate a completed job against scenario expectations.

        Requires:
            - scenario is a dict from SCENARIOS
            - job_data is a dict from the done queue

        Ensures:
            - Returns result dict with keys: status, answer_preview, details

        Default implementation uses keyword matching on response_text.
        Override in subclass for custom validation.
        """
        answer  = job_data.get( "response_text", "" ) or ""
        preview = answer[ :80 ]

        expected_keywords = scenario.get( "expected_keywords", [] )
        if expected_keywords:
            matched, keyword = self._check_answer( answer, expected_keywords )
            if matched:
                return {
                    "status"         : "pass",
                    "answer_preview" : preview,
                    "details"        : f"matched '{keyword}'",
                }
            else:
                return {
                    "status"         : "fail",
                    "answer_preview" : preview,
                    "details"        : "no keyword match in answer",
                }

        # No keywords defined — pass if we got any response
        if answer:
            return {
                "status"         : "pass",
                "answer_preview" : preview,
                "details"        : "response received",
            }

        return {
            "status"         : "fail",
            "answer_preview" : "",
            "details"        : "empty response",
        }

    def pre_run_hook( self, args, headers, ws_id ):
        """
        Hook called after auth but before scenarios. Return False to abort.

        Requires:
            - args is argparse.Namespace
            - headers contains valid auth token
            - ws_id is session ID string

        Ensures:
            - Returns True to continue, False to abort
        """
        return True

    def post_run_hook( self, args, headers, results ):
        """
        Hook called after all scenarios complete, before results table.

        Requires:
            - args is argparse.Namespace
            - headers contains valid auth token
            - results is list of result dicts
        """
        pass

    # ═══════════════════════════════════════════════════════════════════════
    # CLI
    # ═══════════════════════════════════════════════════════════════════════

    def build_argparser( self ):
        """
        Build the CLI argument parser.

        Ensures:
            - Returns argparse.ArgumentParser with common flags

        Override in subclass to add test-specific arguments.
        """
        parser = argparse.ArgumentParser(
            description=f"{self.TEST_NAME} live pipeline smoke test"
        )
        parser.add_argument(
            "--debug", "-d",
            action="store_true",
            default=False,
            help="Enable debug output"
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            default=False,
            help="Enable verbose output"
        )
        parser.add_argument(
            "--no-confirm", "-nc",
            action="store_true",
            default=False,
            help="Disable similarity confirmation prompts during test run"
        )
        return parser

    # ═══════════════════════════════════════════════════════════════════════
    # Main Orchestration
    # ═══════════════════════════════════════════════════════════════════════

    def _print_banner( self, label ):
        """
        Print a test banner.

        Requires:
            - label is a non-empty string

        Ensures:
            - Prints formatted banner to console
        """
        if cu:
            cu.print_banner( label, prepend_nl=True )
        else:
            print( f"\n{'=' * 70}" )
            print( f"  {label}" )
            print( f"{'=' * 70}" )

    def run_scenarios( self, args=None ):
        """
        Main test orchestrator — login, set mode, run scenarios, report results.

        Requires:
            - Server running on BASE_URL
            - Credentials available in environment

        Ensures:
            - Returns True if all scenarios pass
            - Returns False on any failure
        """
        if args is None:
            args = argparse.Namespace()

        scenario_indices = self.get_scenario_indices( args )
        scenarios        = [ self.SCENARIOS[ i ] for i in scenario_indices ]

        label = f"{self.TEST_NAME} Smoke Test ({len( scenarios )} scenarios)"
        self._print_banner( label )

        # Get credentials
        email, password = self._get_credentials()
        if not email or not password:
            msg = ( f"{self.CREDENTIAL_ENV_PREFIX}_{{EMAIL,PASSWORD}} not set; "
                    f"source ~/.lupin/test-env.sh before running this test." )
            if _pytest is not None:
                _pytest.skip( msg )
            print( f"Missing environment variables. Set:" )
            print( f"  export {self.CREDENTIAL_ENV_PREFIX}_EMAIL='your@email.com'" )
            print( f"  export {self.CREDENTIAL_ENV_PREFIX}_PASSWORD='<your-password>'" )
            return False

        try:
            # ═══════════════════════════════════════════════════════════
            # Step 1: Login
            # ═══════════════════════════════════════════════════════════
            print( f"\nStep 1: Logging in as {email}..." )
            token, headers = self._login( email, password )

            if not token:
                print( "Login failed." )
                return False

            print( f"  Login successful, token: {token[ :30 ]}..." )

            # ═══════════════════════════════════════════════════════════
            # Step 1b: Disable similarity confirmation if --no-confirm
            # ═══════════════════════════════════════════════════════════
            self._confirm_was_disabled = False
            if getattr( args, "no_confirm", False ):
                self._confirm_was_disabled = self._disable_similarity_confirmation( headers )

            # ═══════════════════════════════════════════════════════════
            # Step 2: Get WebSocket session ID
            # ═══════════════════════════════════════════════════════════
            print( "\nStep 2: Getting WebSocket session ID..." )
            ws_id = self._get_websocket_session_id( headers )
            print( f"  Using session ID: {ws_id}" )

            # ═══════════════════════════════════════════════════════════
            # Step 3: Pre-run hook
            # ═══════════════════════════════════════════════════════════
            if not self.pre_run_hook( args, headers, ws_id ):
                return False

            # ═══════════════════════════════════════════════════════════
            # Step 4: Run scenario matrix
            # ═══════════════════════════════════════════════════════════
            print( "\n" + "=" * 70 )
            print( f"  {self.TEST_NAME.upper()} SCENARIO MATRIX ({len( scenarios )} scenarios)" )
            print( f"  Each scenario is submitted via {self.get_submit_endpoint()} and polled." )
            print( f"  Default timeout: {self.DEFAULT_TIMEOUT}s per scenario." )
            print( "=" * 70 )

            results      = []
            current_mode = None

            for i, scenario in enumerate( scenarios, 1 ):
                print( f"\n{'─' * 70}" )
                print( f"  Scenario {i}/{len( scenarios )}: {scenario[ 'id' ]}" )
                self._print_scenario_header( scenario )
                print( f"{'─' * 70}" )

                # Switch mode if needed
                target_mode = self.get_mode_for_scenario( scenario )
                if target_mode != current_mode:
                    if target_mode:
                        print( f"  Switching mode to '{target_mode}'..." )
                        if not self._set_mode( headers, target_mode ):
                            print( f"  WARNING: Failed to set mode '{target_mode}', continuing." )
                    elif current_mode is not None:
                        print( "  Clearing mode..." )
                        self._clear_mode( headers )
                    current_mode = target_mode

                result = self._run_single_scenario( scenario, headers, ws_id )
                results.append( result )

            # ═══════════════════════════════════════════════════════════
            # Step 5: Cleanup mode
            # ═══════════════════════════════════════════════════════════
            if current_mode is not None:
                print( f"\n{'─' * 70}" )
                print( "Clearing mode..." )
                self._clear_mode( headers )
                print( "  Mode cleared." )

            # ═══════════════════════════════════════════════════════════
            # Step 6: Post-run hook + results
            # ═══════════════════════════════════════════════════════════
            self.post_run_hook( args, headers, results )
            self._print_results_table( results )

            passed = sum( 1 for r in results if r[ "status" ] == "pass" )
            failed = sum( 1 for r in results if r[ "status" ] != "pass" )

            print( f"\n{'=' * 70}" )
            if failed == 0:
                print( f"ALL {self.TEST_NAME.upper()} SMOKE TESTS PASSED ({passed}/{len( scenarios )})!" )
            else:
                print( f"{self.TEST_NAME.upper()} SMOKE TESTS: {passed} passed, {failed} failed" )
            print( "=" * 70 )

            return failed == 0

        except requests.exceptions.ConnectionError:
            if _pytest is not None:
                _pytest.skip( f"server unreachable at {self.BASE_URL}" )
            print( f"\nConnection failed - is the server running on {self.BASE_URL}?" )
            return False
        except Exception as e:
            print( f"\nSmoke test failed: {e}" )
            traceback.print_exc()
            return False
        finally:
            try:
                if "headers" in dir():
                    if getattr( self, "_confirm_was_disabled", False ):
                        self._restore_similarity_confirmation( headers )
                    self._clear_mode( headers )
            except Exception:
                pass

    def _print_scenario_header( self, scenario ):
        """
        Print scenario details before execution.

        Requires:
            - scenario is a dict from SCENARIOS

        Override for custom scenario display.
        """
        if "query" in scenario:
            print( f"  Query: \"{scenario[ 'query' ]}\"" )
        if "expected_keywords" in scenario:
            print( f"  Expected keywords: {scenario[ 'expected_keywords' ]}" )

    def _run_single_scenario( self, scenario, headers, ws_id ):
        """
        Execute a single scenario and return result dict.

        Requires:
            - scenario is a dict from SCENARIOS
            - headers contains valid auth token
            - ws_id is session ID

        Ensures:
            - Returns dict with keys: id, status, answer_preview, details
        """
        result = {
            "id"             : scenario[ "id" ],
            "status"         : "fail",
            "answer_preview" : "",
            "details"        : "",
        }

        job_data, error = self._submit_and_wait( scenario, headers, ws_id )

        if error:
            result[ "details" ] = error
            print( f"    FAIL: {error}" )
        elif job_data:
            validation = self.validate_result( scenario, job_data )
            result.update( validation )

            if result[ "status" ] == "pass":
                print( f"    PASS: {result[ 'details' ]}" )
                answer = job_data.get( "response_text", "" ) or ""
                if answer:
                    print( f"    Answer: {answer[ :120 ]}" )
            else:
                print( f"    FAIL: {result[ 'details' ]}" )
                answer = job_data.get( "response_text", "" ) or ""
                if answer:
                    print( f"    Got: {answer[ :200 ]}" )
        else:
            result[ "details" ] = "No job data returned"
            print( f"    FAIL: No job data" )

        return result

    def run( self, argv=None ):
        """
        Parse CLI args and run scenarios. Entry point for __main__ usage.

        Requires:
            - argv is list of CLI argument strings, or None for sys.argv

        Ensures:
            - Returns True if all tests pass, False otherwise
        """
        parser = self.build_argparser()
        args   = parser.parse_args( argv )
        return self.run_scenarios( args )
