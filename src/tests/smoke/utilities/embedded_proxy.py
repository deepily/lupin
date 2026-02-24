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
    PROXY_STARTUP_WAIT = 5  # seconds to wait for proxy to connect

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

    def _start_proxy( self, profile=None, strategy=None, debug=False ):
        """
        Launch notification proxy as a subprocess.

        Requires:
            - No proxy is currently running (will skip if already active)
            - PYTHONPATH includes src/ directory

        Ensures:
            - Proxy subprocess is started and given time to connect
            - self._proxy_process holds the Popen handle
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

            # Give the proxy time to authenticate and subscribe
            print( f"  Waiting {self.PROXY_STARTUP_WAIT}s for proxy to connect..." )
            time.sleep( self.PROXY_STARTUP_WAIT )

            if self._proxy_process.poll() is not None:
                # Proxy exited prematurely
                stdout = self._proxy_process.stdout.read().decode( "utf-8", errors="replace" )
                print( f"  WARNING: Proxy exited prematurely (code={self._proxy_process.returncode})" )
                print( f"  Output: {stdout[ :2000 ]}" )
                self._proxy_process = None
            else:
                print( f"  Proxy started (pid={self._proxy_process.pid})" )

                # Spawn reader thread for real-time log streaming
                if debug:
                    self._reader_thread = threading.Thread(
                        target = self._proxy_log_reader,
                        name   = "proxy-log-reader",
                        daemon = True,
                    )
                    self._reader_thread.start()
                    print( "  Real-time proxy log streaming enabled." )

        except Exception as e:
            print( f"  WARNING: Failed to start proxy: {e}" )
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
