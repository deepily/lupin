"""
Unit tests for the cosa.agents.shared package __init__.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, shared/ lane). The package
__init__ is pure re-export glue (PlanWriter / GitStrategist / FixExecutor +
FIX_PROMPT_BUILDERS + register_fix_prompts), covered on import; these assertions make
the import coverage meaningful. Importing pulls in fix_executor → ClaudeAgentOptions →
SDK chain, so this runs via run-sdk-cov.sh. No network/spend.
"""

import unittest

import cosa.agents.shared as shared


class TestSharedInit( unittest.TestCase ):

    def test_version_pinned( self ):
        self.assertEqual( shared.__version__, "0.1.0" )

    def test_all_symbols_bound( self ):
        for name in shared.__all__:
            with self.subTest( name=name ):
                self.assertTrue( hasattr( shared, name ), f"{name} not re-exported" )

    def test_expected_exports_present( self ):
        from cosa.agents.shared.plan_writer import PlanWriter
        from cosa.agents.shared.git_strategist import GitStrategist
        from cosa.agents.shared.fix_executor import FixExecutor, register_fix_prompts
        self.assertIs( shared.PlanWriter, PlanWriter )
        self.assertIs( shared.GitStrategist, GitStrategist )
        self.assertIs( shared.FixExecutor, FixExecutor )
        self.assertIs( shared.register_fix_prompts, register_fix_prompts )
        self.assertIsInstance( shared.FIX_PROMPT_BUILDERS, dict )


if __name__ == "__main__":
    unittest.main()
