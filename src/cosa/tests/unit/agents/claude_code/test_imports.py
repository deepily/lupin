"""
Unit tests for cosa.agents.claude_code package __init__ + voice_io wrapper.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, claude_code lane). Both are
pure re-export glue covered on import; these assertions make the import coverage
meaningful. Importing the package pulls in job.py → SDK chain → run via run-sdk-cov.sh.
No network/spend.
"""

import unittest

import cosa.agents.claude_code as cc
import cosa.agents.claude_code.voice_io as vio
from cosa.agents.utils import voice_io as core


class TestPackageInit( unittest.TestCase ):

    def test_claude_code_job_reexported( self ):
        self.assertEqual( cc.__all__, [ "ClaudeCodeJob" ] )
        self.assertTrue( hasattr( cc, "ClaudeCodeJob" ) )


class TestVoiceIoWrapper( unittest.TestCase ):

    def test_reexports_are_core_identities( self ):
        self.assertIs( vio.notify, core.notify )
        self.assertIs( vio.ask_yes_no, core.ask_yes_no )
        self.assertIs( vio.get_input, core.get_input )
        self.assertIs( vio.choose, core.choose )

    def test_all_list( self ):
        self.assertEqual( vio.__all__, [ "notify", "ask_yes_no", "get_input", "choose" ] )


if __name__ == "__main__":
    unittest.main()
