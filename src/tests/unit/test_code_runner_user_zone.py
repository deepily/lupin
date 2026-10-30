"""
Unit tests: generated code runs in the configured user zone, never the host clock's zone.

The defect: on the VM ( us-central1 ) a typed "what time is it" answered "It is 12:25 PM." in
Central. The date-and-time prompt names `app timezone`, but a model can still emit a bare
`datetime.now()`, and the child process inherited the host zone. These tests run a real child
process with the host pinned to Chicago and expect Eastern.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import cosa.utils.util_code_runner as ucr


class _StubConfig:
    """A ConfigurationManager answering only the two keys the runner reads."""

    def __init__( self, zone="America/New_York" ):
        self.zone = zone

    def get( self, key, **kwargs ):
        return { "path to code execution file": "/io/code.py", "app timezone": self.zone }[ key ]


# A bare local-clock read: its answer is whatever zone the child process runs in.
BARE_CLOCK_CODE = [ "import datetime", "def whats_the_zone():", "    return datetime.datetime.now().astimezone().tzname()" ]
EXAMPLE         = "solution = whats_the_zone()"


class TestChildRunsInConfiguredZone( unittest.TestCase ):

    def _run( self, host_tz, configured_zone="America/New_York", code=None ):
        with tempfile.TemporaryDirectory() as root, \
             patch.dict( os.environ, { "TZ": host_tz } ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=_StubConfig( configured_zone ) ), \
             patch( "cosa.utils.util.get_project_root", return_value=root ):
            os.makedirs( root + "/io" )
            return ucr.assemble_and_run_solution( code or BARE_CLOCK_CODE, EXAMPLE )

    def test_bare_clock_read_answers_eastern_on_a_chicago_host( self ):
        result = self._run( "America/Chicago" )
        self.assertEqual( 0, result[ "return_code" ], result[ "output" ] )
        self.assertIn( result[ "output" ], ( "EST", "EDT" ), "child ran in the host zone, not the configured one" )

    def test_a_different_configured_zone_is_honoured( self ):
        result = self._run( "America/Chicago", configured_zone="America/Los_Angeles" )
        self.assertIn( result[ "output" ], ( "PST", "PDT" ) )

    def test_fallback_without_configuration_is_eastern( self ):
        with tempfile.TemporaryDirectory() as root, \
             patch.dict( os.environ, { "TZ": "America/Chicago" } ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=ValueError( "no env var" ) ), \
             patch( "cosa.utils.util.get_project_root", return_value=root ):
            os.makedirs( root + "/io" )
            result = ucr.assemble_and_run_solution( BARE_CLOCK_CODE, EXAMPLE )
        self.assertIn( result[ "output" ], ( "EST", "EDT" ) )
