"""
Unit tests for the deep_research package __init__ and its placeholder subpackages.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). The package `__init__` is pure re-export glue (no branches); `nodes/__init__`
and `tools/__init__` are Phase-2 placeholders that declare `__all__ = []`. All three
are fully covered on import; these tests assert the public surface is bound so the
import coverage is meaningful rather than incidental.

Importing the package transitively pulls in the SDK chain (orchestrator → api_client →
anthropic), so this file MUST be measured via run-sdk-cov.sh. No network/LLM/voice I/O.
"""

import unittest

import cosa.agents.deep_research as dr
import cosa.agents.deep_research.nodes as dr_nodes
import cosa.agents.deep_research.tools as dr_tools


class TestPackageInit( unittest.TestCase ):
    """The package __init__ re-exports config / state / orchestrator / interface /
    cost / api / voice / narrowing symbols and pins a version."""

    def test_version_pinned( self ):
        self.assertEqual( dr.__version__, "0.2.2" )

    def test_key_config_constants_reexported( self ):
        # Firewalled-key constant names are part of the public contract.
        self.assertEqual( dr.ENV_VAR_NAME, "ANTHROPIC_API_KEY_FIREWALLED" )
        self.assertEqual( dr.KEY_FILE_NAME, "anthropic-api-key-firewalled" )

    def test_core_symbols_are_bound( self ):
        for name in (
            "ResearchConfig", "OrchestratorState", "JobSubState", "ResearchState",
            "ResearchOrchestratorAgent", "ResearchAPIClient", "APIResponse",
            "CostTracker", "BudgetExceededError", "NarrowingHarness",
            "MockResearchAPIClient", "create_initial_state",
        ):
            with self.subTest( name=name ):
                self.assertTrue( hasattr( dr, name ), f"{name} not re-exported" )

    def test_all_lists_every_documented_symbol( self ):
        # __all__ entries must each resolve to a real bound attribute.
        for name in dr.__all__:
            with self.subTest( name=name ):
                self.assertTrue( hasattr( dr, name ), f"__all__ names missing attr {name}" )


class TestPlaceholderSubpackages( unittest.TestCase ):
    """nodes/ and tools/ are Phase-2 placeholders — empty public surface."""

    def test_nodes_all_is_empty( self ):
        self.assertEqual( dr_nodes.__all__, [ ] )

    def test_tools_all_is_empty( self ):
        self.assertEqual( dr_tools.__all__, [ ] )


if __name__ == "__main__":
    unittest.main()
