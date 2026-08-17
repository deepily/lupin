#!/usr/bin/env python3
"""
Row 95924f2d step 4 + row e5a840c9 — the training corpus roster is single-sourced
from the registry, and its generated ROWS agree with the generated MENU.

EXECUTOR: AI — builds tiny (sample_size=1) training frames from real templates +
seed JSONs; no server, no LLM. :7999-class.

Step 4 points the training MENU (`agent_router_commands`, interpolated into every
instruction) at `speakable_commands()` instead of concatenating the three
agent-router JSON key sets. e5a840c9 drops the START key
("agent router go to test fix expediter") from agent-router-agentic-commands.json
— removing its training EXAMPLES, which is the point, not a side effect: START is
system-triggered with a non-speakable job-id argument and is not in the served
menu, so a retrain must stop being taught to emit it.

Together they close the 18-vs-19 disagreement BY CONSTRUCTION: the distinct
commands in the generated training rows equal the generated menu. This test is
that agreement — asserted, not claimed. Re-add START to the agentic JSON and
test_training_rows_equal_the_menu goes red (the manual control Rachel required).
"""

import unittest

from cosa.rest.v2.registry import REGISTRY
from cosa.rest.v2.router_prompt_generator import speakable_commands
from cosa.training.xml_coordinator import XmlCoordinator


class TestCorpusRosterMatchesMenu( unittest.TestCase ):
    """The generated training rows and the generated menu are the same set."""

    @classmethod
    def setUpClass( cls ):
        coordinator = XmlCoordinator( silent=True )
        row_commands = set()
        for builder in ( "build_compound_agent_router_training_prompts",
                         "build_simple_agent_router_training_prompts",
                         "build_agentic_job_training_prompts" ):
            frame = getattr( coordinator, builder )( sample_size_per_command=1 )
            row_commands |= set( frame[ "command" ].unique().tolist() )
        cls.row_commands = row_commands
        cls.menu         = set( speakable_commands() )

    def test_training_rows_equal_the_menu( self ):
        """The distinct commands trained equal the commands the menu lists."""
        self.assertEqual( self.row_commands, self.menu,
                          f"rows vs menu disagree: {sorted( self.row_commands ^ self.menu )}" )

    def test_menu_is_registry_sourced_not_json_keys( self ):
        """
        The menu comes from `registry.speakable`, not the JSON key sets — pinning
        the demotion (Krishna §2.4): the JSONs keep the phrasings, not the roster.
        """
        registry_speakable = { command for command, spec in REGISTRY.items() if spec.speakable }
        self.assertEqual( self.menu, registry_speakable )

    def test_start_is_absent_from_both( self ):
        """e5a840c9: START trains no examples and is not on the menu."""
        start = "agent router go to test fix expediter"
        self.assertNotIn( start, self.menu )
        self.assertNotIn( start, self.row_commands )

    def test_a_stray_row_command_would_break_the_pin( self ):
        """
        Control: the equality in test_training_rows_equal_the_menu must be able to
        fail. A single extra command in the row set must make it unequal to the
        menu — so a green pin means true agreement, not a check that cannot fail.
        """
        self.assertNotEqual( self.row_commands | { "agent router go to stray" }, self.menu )


if __name__ == "__main__":
    unittest.main()
