#!/usr/bin/env python3
"""
Row 14ba1437 — the simple-command builder must train under the AGENT-ROUTER
instruction wrapper, not the BROWSER wrapper.

EXECUTOR: AI — builds a tiny training sample from real templates + seed JSONs
(no server, no LLM, ~0.1s). :7999-class.

The defect: build_simple_agent_router_training_prompts (xml_coordinator.py:634)
filled the BROWSER instruction template (`vox_cmd_instruction_template` —
"a browser on your computer would understand", <browser-commands>) with router
commands, while its two sibling builders — compound (:387) and agentic (:805) —
correctly use `agent_router_instruction_template` ("an agent routing command that
another LLM would understand"). Five commands (todo/math/calculator/automatic/none,
`none` being the router's fallback) trained under the wrong wrapper.

This regression pins the fix: every simple-command training row carries the router
wrapper and none carries the browser wrapper. Revert line 634 to
`vox_cmd_instruction_template` and both assertions go red — that is the control.
"""

import unittest

from cosa.training.xml_coordinator import XmlCoordinator


ROUTER_PHRASE  = "agent routing command that another LLM would understand"
BROWSER_PHRASE = "a browser on your computer would understand"


class TestSimpleBuilderWrapperRegression( unittest.TestCase ):
    """The simple builder trains under the agent-router wrapper (14ba1437)."""

    @classmethod
    def setUpClass( cls ):
        # Real coordinator: the bug lives in which template attribute is read, so
        # the templates must be genuinely initialized (not mocked away).
        coordinator = XmlCoordinator( silent=True )
        cls.frame   = coordinator.build_simple_agent_router_training_prompts(
            sample_size_per_command=1
        )
        cls.generator = coordinator.prompt_generator

    def test_every_simple_row_uses_the_router_wrapper( self ):
        contains_router = self.frame[ "instruction" ].str.contains( ROUTER_PHRASE, regex=False )
        self.assertTrue( contains_router.all(),
                         "a simple-command training row is missing the agent-router wrapper" )

    def test_no_simple_row_uses_the_browser_wrapper( self ):
        contains_browser = self.frame[ "instruction" ].str.contains( BROWSER_PHRASE, regex=False )
        self.assertEqual( int( contains_browser.sum() ), 0,
                          "a simple-command training row still carries the BROWSER wrapper" )

    def test_the_two_wrappers_are_genuinely_distinct( self ):
        """
        Control: the two assertions above only mean something if the wrappers
        differ. Confirm the browser phrase belongs to the vox-cmd template and the
        router phrase to the agent-router template — so a build under the wrong one
        WOULD carry the browser phrase.
        """
        self.assertIn( BROWSER_PHRASE, self.generator.vox_cmd_instruction_template )
        self.assertIn( ROUTER_PHRASE,  self.generator.agent_router_instruction_template )
        self.assertNotEqual( self.generator.vox_cmd_instruction_template,
                             self.generator.agent_router_instruction_template )


if __name__ == "__main__":
    unittest.main()
