#!/usr/bin/env python3
"""
Mixin for auto-launching the notification proxy as a subprocess.

Eliminates the need to manually start the notification proxy in a separate
terminal. The proxy is launched before interactive scenarios and stopped
after the last scenario completes.

Usage:
    class MyInteractiveTest( LivePipelineTestBase, EmbeddedProxyMixin ):
        PROXY_PROFILE  = "expeditor_smoke"
        PROXY_STRATEGY = "llm_script"

        def pre_run_hook( self, args, headers, ws_id ):
            if getattr( args, "auto_proxy", False ):
                self._start_proxy()
            return True

        def post_run_hook( self, args, headers, results ):
            self._stop_proxy()

Created: 2026-02-13
"""

import os
import signal
import subprocess
import sys
import threading
import time

import requests


class EmbeddedProxyMixin:
    """
    Mixin that auto-launches notification proxy as a subprocess.

    Requires:
        - Subclass defines PROXY_PROFILE (str) — notification proxy profile name
        - cosa.agents.notification_proxy package is importable
        - Credential env vars are set for the proxy account

    Ensures:
        - Proxy subprocess is launched with correct profile and strategy
        - Proxy is gracefully stopped on cleanup
        - Stats from proxy stdout are captured
    """

    # ═══════════════════════════════════════════════════════════════════════
    # Subclass configuration — override these in your test class
    # ═══════════════════════════════════════════════════════════════════════

    PROXY_PROFILE    = "deep_research"
    PROXY_STRATEGY   = "llm_script"
    PROXY_STARTUP_WAIT          = 1    # seconds — brief settle for subprocess launch before WS-auth poll begins
    PROXY_WS_AUTH_TIMEOUT       = 30   # seconds — hard cap on WS-auth poll (login + handshake + subscribe)
    PROXY_WS_AUTH_POLL_INTERVAL = 0.5  # seconds — gap between WS-state polls
    PROXY_EXPECTED_SESSION_ID   = "auto proxy"  # matches DEFAULT_SESSION_ID in notification_proxy/config.py

    def __init__( self, *args, **kwargs ):
        """Initialize proxy state."""
        super().__init__( *args, **kwargs )
        self._proxy_process = None
        self._proxy_debug   = False
        self._reader_thread = None

    @property
    def proxy_running( self ):
        """
        Check if the proxy subprocess is still running.

        Ensures:
            - Returns True if proxy is alive
            - Returns False otherwise
        """
        return self._proxy_process is not None and self._proxy_process.poll() is None

    def _proxy_log_reader( self ):
        """
        Read proxy stdout line-by-line and print to console in real time.

        Requires:
            - self._proxy_process is a running Popen with stdout=PIPE
            - Called from a daemon thread

        Ensures:
            - Each line from proxy stdout is printed with [proxy] prefix
            - Loop exits on EOF (process termination closes pipe)
        """
        try:
            for line in iter( self._proxy_process.stdout.readline, b"" ):
                text = line.decode( "utf-8", errors="replace" ).rstrip( "\n" )
                if text:
                    print( f"  [proxy] {text}" )
        except Exception:
            pass  # Process died or pipe closed

    def _start_proxy( self, profile=None, strategy=None, debug=False, email=None, password=None ):
        """
        Launch notification proxy as a subprocess and wait for WS-auth to complete.

        Requires:
            - No proxy is currently running (will skip if already active)
            - PYTHONPATH includes src/ directory
            - Lupin REST server reachable at LUPIN_API_URL (default http://localhost:7999)

        Ensures:
            - Proxy subprocess is launched
            - Polls /api/debug/websocket-state until proxy registers a WS session
            - Returns normally once proxy is verified WS-authenticated
            - On any failure: best-effort kills the subprocess, clears self._proxy_process,
              and raises RuntimeError with diagnostics

        Raises:
            RuntimeError: When the proxy subprocess fails to launch, dies during startup,
                or fails to register a WS session within PROXY_WS_AUTH_TIMEOUT seconds.
        """
        if self.proxy_running:
            print( "  Proxy already running, skipping launch." )
            return

        profile           = profile or self.PROXY_PROFILE
        strategy          = strategy or self.PROXY_STRATEGY
        self._proxy_debug = debug

        # Build the command
        cmd = [
            sys.executable, "-m", "cosa.agents.notification_proxy",
            "--profile", profile,
            "--strategy", strategy,
        ]
        if debug:
            cmd.append( "--debug" )
        if email:
            cmd.extend( [ "--email", email ] )
        if password:
            cmd.extend( [ "--password", password ] )

        # Ensure PYTHONPATH includes src/
        env = os.environ.copy()
        lupin_root = env.get( "LUPIN_ROOT", "" )
        src_path   = os.path.join( lupin_root, "src" ) if lupin_root else ""

        if src_path and src_path not in env.get( "PYTHONPATH", "" ):
            env[ "PYTHONPATH" ] = src_path + ":" + env.get( "PYTHONPATH", "" )

        # Force line-buffered stdout so the reader thread gets lines in real time
        if debug:
            env[ "PYTHONUNBUFFERED" ] = "1"

        print( f"\n  Starting notification proxy (profile={profile}, strategy={strategy})..." )

        try:
            self._proxy_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                # Start in new process group so we can signal it cleanly
                preexec_fn=os.setsid if hasattr( os, "setsid" ) else None
            )
        except Exception as e:
            self._proxy_process = None
            raise RuntimeError( f"Failed to launch proxy subprocess: {e}" )

        # Brief settle so the subprocess can attempt login + WS handshake
        print( f"  Waiting {self.PROXY_STARTUP_WAIT}s for subprocess to settle..." )
        time.sleep( self.PROXY_STARTUP_WAIT )

        if self._proxy_process.poll() is not None:
            # Proxy exited during settle — surface stdout in the exception
            stdout      = self._proxy_process.stdout.read().decode( "utf-8", errors="replace" )
            return_code = self._proxy_process.returncode
            self._proxy_process = None
            raise RuntimeError(
                f"Proxy subprocess exited during settle (code={return_code}).\n"
                f"  Last stdout:\n{stdout[ :2000 ]}"
            )

        print( f"  Proxy subprocess alive (pid={self._proxy_process.pid}). Polling for WS-auth..." )

        # Spawn reader thread before the poll so stdout doesn't fill the pipe
        if debug:
            self._reader_thread = threading.Thread(
                target = self._proxy_log_reader,
                name   = "proxy-log-reader",
                daemon = True,
            )
            self._reader_thread.start()
            print( "  Real-time proxy log streaming enabled." )

        # Poll for WS-auth completion — raises RuntimeError on timeout
        self._wait_for_proxy_ws_auth( email )

        print( f"  Proxy WS-auth verified — proxy is registered with the server." )

    def _wait_for_proxy_ws_auth( self, expected_email ):
        """
        Poll /api/debug/websocket-state until the proxy's WS session appears.

        Requires:
            - self._proxy_process is alive at call time
            - Lupin REST server reachable at LUPIN_API_URL (default http://localhost:7999)

        Ensures:
            - Returns normally when PROXY_EXPECTED_SESSION_ID appears in active_connections
              with a non-empty session_to_user mapping
            - Raises RuntimeError on PROXY_WS_AUTH_TIMEOUT (after killing subprocess)
            - Raises RuntimeError if subprocess dies during the poll (with stdout)

        Raises:
            RuntimeError: On poll timeout or subprocess death.
        """
        base_url   = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
        poll_url   = f"{base_url}/api/debug/websocket-state"
        deadline   = time.time() + self.PROXY_WS_AUTH_TIMEOUT
        last_state = None
        expected   = self.PROXY_EXPECTED_SESSION_ID

        while time.time() < deadline:
            # If subprocess died during poll, abort with diagnostics
            if self._proxy_process.poll() is not None:
                stdout      = self._proxy_process.stdout.read().decode( "utf-8", errors="replace" )
                return_code = self._proxy_process.returncode
                self._proxy_process = None
                raise RuntimeError(
                    f"Proxy subprocess died during WS-auth poll (code={return_code}).\n"
                    f"  Last stdout:\n{stdout[ :2000 ]}"
                )

            try:
                resp = requests.get( poll_url, timeout=5 )
                if resp.status_code == 200:
                    state           = resp.json()
                    last_state      = state
                    active          = state.get( "active_connections", [] )
                    session_to_user = state.get( "session_to_user", {} )

                    if expected in active and session_to_user.get( expected ):
                        user_uuid = session_to_user[ expected ]
                        print( f"  WS-auth confirmed: session '{expected}' → user UUID {user_uuid}" )
                        return
            except requests.exceptions.RequestException as e:
                if self._proxy_debug: print( f"  Poll exception (will retry): {e}" )

            time.sleep( self.PROXY_WS_AUTH_POLL_INTERVAL )

        # Timeout — kill proxy and raise with diagnostics
        last_users  = list( ( last_state or {} ).get( "user_sessions", {} ).keys() )
        last_active = ( last_state or {} ).get( "active_connections", [] )
        self._kill_proxy_subprocess()

        raise RuntimeError(
            f"Proxy WS-auth did not complete within {self.PROXY_WS_AUTH_TIMEOUT}s.\n"
            f"  Expected session ID:  '{expected}'\n"
            f"  Expected user email:  {expected_email or '(env-var fallback — set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL)'}\n"
            f"  Last observed active_connections: {last_active}\n"
            f"  Last observed user_sessions keys: {last_users}\n"
            f"  Possible causes:\n"
            f"    - Login 401 (account doesn't exist in target DB)\n"
            f"    - Env vars LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD unset\n"
            f"    - Server unreachable at {base_url}\n"
            f"    - Proxy crashed silently (check {poll_url} for current state)"
        )

    def _kill_proxy_subprocess( self ):
        """
        Best-effort SIGINT then SIGKILL the proxy subprocess.

        Ensures:
            - Sends SIGINT (graceful), waits up to 5s
            - Falls back to SIGKILL if still alive, waits up to 2s
            - Sets self._proxy_process = None after best-effort cleanup
            - Swallows all exceptions (called from error paths)
        """
        if not self._proxy_process:
            return
        try:
            if hasattr( os, "setsid" ):
                os.killpg( os.getpgid( self._proxy_process.pid ), signal.SIGINT )
            else:
                self._proxy_process.send_signal( signal.SIGINT )
            try:
                self._proxy_process.wait( timeout=5 )
            except subprocess.TimeoutExpired:
                self._proxy_process.kill()
                try: self._proxy_process.wait( timeout=2 )
                except subprocess.TimeoutExpired: pass
        except Exception:
            pass
        self._proxy_process = None

    def _stop_proxy( self ):
        """
        Gracefully stop the notification proxy subprocess.

        Ensures:
            - Sends SIGINT for graceful shutdown
            - Falls back to SIGTERM after timeout
            - Captures and prints proxy stdout (stats)
        """
        if not self._proxy_process:
            return

        if self._proxy_process.poll() is not None:
            # Already exited
            self._drain_proxy_output()
            self._proxy_process = None
            return

        print( f"\n  Stopping notification proxy (pid={self._proxy_process.pid})..." )

        try:
            # Send SIGINT for graceful shutdown (prints stats)
            if hasattr( os, "setsid" ):
                os.killpg( os.getpgid( self._proxy_process.pid ), signal.SIGINT )
            else:
                self._proxy_process.send_signal( signal.SIGINT )

            try:
                self._proxy_process.wait( timeout=10 )
                print( "  Proxy stopped gracefully." )
            except subprocess.TimeoutExpired:
                print( "  Proxy didn't stop after SIGINT, sending SIGTERM..." )
                self._proxy_process.terminate()
                try:
                    self._proxy_process.wait( timeout=5 )
                except subprocess.TimeoutExpired:
                    self._proxy_process.kill()
                    self._proxy_process.wait()
                    print( "  Proxy killed." )

        except ProcessLookupError:
            pass  # Already dead

        # Join reader thread to ensure all output is captured
        if self._reader_thread is not None:
            self._reader_thread.join( timeout=5 )
            self._reader_thread = None

        self._drain_proxy_output()
        self._proxy_process = None

    def _drain_proxy_output( self ):
        """
        Read and display any remaining proxy stdout.

        Ensures:
            - If proxy_debug was active, skips (output already streamed)
            - Otherwise reads all buffered output and prints stats lines
        """
        if self._proxy_debug:
            print( "  [proxy] (output was streamed in real-time above)" )
            return

        if not self._proxy_process or not self._proxy_process.stdout:
            return

        try:
            remaining = self._proxy_process.stdout.read()
            if remaining:
                output = remaining.decode( "utf-8", errors="replace" )
                # Show the stats section if present
                lines = output.strip().split( "\n" )
                in_stats = False
                for line in lines:
                    if "Statistics" in line or "stats" in line.lower() or "Notifications" in line:
                        in_stats = True
                    if in_stats:
                        print( f"  [proxy] {line}" )
        except Exception:
            pass

    @staticmethod
    def add_proxy_args( parser ):
        """
        Add --auto-proxy CLI flag to an argument parser.

        Requires:
            - parser is an argparse.ArgumentParser

        Ensures:
            - Adds --auto-proxy flag with default False
        """
        parser.add_argument(
            "--auto-proxy",
            action="store_true",
            default=False,
            help="Auto-launch notification proxy for interactive scenarios"
        )
        parser.add_argument(
            "--proxy-debug",
            action="store_true",
            default=False,
            help="Enable debug output and real-time log streaming for the auto-launched proxy"
        )
        return parser
