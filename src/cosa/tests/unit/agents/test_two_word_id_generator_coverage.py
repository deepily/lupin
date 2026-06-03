#!/usr/bin/env python3
"""
Guard-free coverage companion for cosa.agents.two_word_id_generator.

Relocated 2026-06-03 (CoSA coverage campaign — Cheech 🌿, blessed by Tiberius 👑)
out of the legacy test_two_word_id_generator.py, whose module-level
pytest.skip( allow_module_level=True ) guard gates the ENTIRE file on legacy
test-infra importability. The campaign's finish-line branch must not be hostage
to that guard: a silent skip would let get_id():140->133 rot to uncovered with
NO red — exactly the regression the 100% mandate exists to prevent.

This companion has ZERO legacy-infra dependency (mirrors the
test_notifications_router_coverage.py companion pattern) so it always collects.

Drives two_word_id_generator.py to 100% line+branch FROM THIS FILE ALONE:
    - get_id() collision-retry arm  (140->133)
    - @singleton instance-reuse arm (61->63)
Hermetic: snapshots/restores the process-wide singleton's generated_ids and uses
ONLY real word-list entries, so no state leaks to other tests.
"""

import unittest
from unittest.mock import patch

from cosa.agents.two_word_id_generator import TwoWordIdGenerator


class TestTwoWordIdGeneratorCoverage( unittest.TestCase ):
    """Branch coverage for the singleton-decorated unique two-word ID generator."""

    def test_get_id_retries_on_duplicate_combination( self ):
        """
        Ensure get_id() re-loops when the chosen combination was already generated.

        Requires:
            - TwoWordIdGenerator is the @singleton-decorated generator

        Ensures:
            - A 2nd construction returns the same instance (drives the reuse arm 61->63)
            - A pre-seeded duplicate ("bright lion") chosen first is DISCARDED and the
              loop retries (drives the collision-retry arm 140->133), returning the next
              unique combination ("wise owl")
            - The singleton's generated_ids is restored afterward (hermetic)
        """
        gen       = TwoWordIdGenerator()
        gen_again = TwoWordIdGenerator()                       # 2nd construction -> singleton reuse arm (61->63)
        self.assertIs( gen_again, gen )                        # @singleton returns the same instance
        saved_ids = set( gen.generated_ids )
        try:
            gen.generated_ids.add( "bright lion" )             # pre-seed the collision (real words)
            # loop 1: ("bright","lion") -> "bright lion" (duplicate -> retry / 140->133)
            # loop 2: ("wise","owl")    -> "wise owl"    (unique -> return)
            with patch( "random.choice", side_effect=[ "bright", "lion", "wise", "owl" ] ):
                result = gen.get_id()
            self.assertEqual( result, "wise owl" )
            self.assertIn( "wise owl", gen.generated_ids )
        finally:
            gen.generated_ids.clear()
            gen.generated_ids.update( saved_ids )              # restore singleton state (hermetic)


if __name__ == "__main__":
    unittest.main()
