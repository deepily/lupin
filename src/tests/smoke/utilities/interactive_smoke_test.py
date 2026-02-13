#!/usr/bin/env python3
"""
Combined base class for interactive (voice-enabled) smoke tests.

Merges LivePipelineTestBase with EmbeddedProxyMixin so that tests needing
the notification proxy can auto-launch it with --auto-proxy.

Usage:
    class MyInteractiveTest( InteractiveSmokeTest ):
        TEST_NAME      = "CRUD"
        SCENARIOS      = [ ... ]
        PROXY_PROFILE  = "crud"

    if __name__ == "__main__":
        test = MyInteractiveTest()
        success = test.run( sys.argv[ 1: ] )
        sys.exit( 0 if success else 1 )

Created: 2026-02-13
"""

from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase
from tests.smoke.utilities.embedded_proxy import EmbeddedProxyMixin


class InteractiveSmokeTest( LivePipelineTestBase, EmbeddedProxyMixin ):
    """
    Base class for smoke tests that need notification proxy support.

    Requires:
        - Subclass defines PROXY_PROFILE for proxy auto-launch
        - Subclass defines SCENARIOS with optional "interactive" flag

    Ensures:
        - --auto-proxy flag is available on CLI
        - Proxy is auto-started before scenarios if --auto-proxy is set
        - Proxy is auto-stopped after scenarios complete
    """

    def __init__( self ):
        """Initialize with both base class and mixin state."""
        super().__init__()

    def build_argparser( self ):
        """
        Build CLI parser with proxy arguments added.

        Ensures:
            - Returns parser with --auto-proxy and --proxy-debug flags
        """
        parser = super().build_argparser()
        self.add_proxy_args( parser )
        return parser

    def pre_run_hook( self, args, headers, ws_id ):
        """
        Start proxy before scenarios if --auto-proxy is set.

        Requires:
            - args may have auto_proxy and proxy_debug attributes

        Ensures:
            - Proxy is launched if --auto-proxy flag is present
            - Returns True to continue test execution
        """
        if getattr( args, "auto_proxy", False ):
            debug = getattr( args, "proxy_debug", False )
            self._start_proxy( debug=debug )

            if not self.proxy_running:
                print( "  WARNING: Proxy failed to start. Interactive scenarios may timeout." )
                print( "  You can run the proxy manually in a separate terminal:" )
                print( f"    python -m cosa.agents.notification_proxy --profile {self.PROXY_PROFILE} --debug" )

        return True

    def post_run_hook( self, args, headers, results ):
        """
        Stop proxy after scenarios complete.

        Ensures:
            - Proxy subprocess is stopped gracefully
        """
        self._stop_proxy()
