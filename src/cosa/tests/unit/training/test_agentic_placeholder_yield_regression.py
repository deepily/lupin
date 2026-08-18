#!/usr/bin/env python3
"""
The two thin agentic router commands must no longer be seed-line limited.

EXECUTOR: AI — builds the agentic training sample from real templates + seed
files (no server, no LLM). :7999-class.

The defect: `agent router go to test suite` and `agent router go to test fix
expediter resume` both declared `"placeholders": {}` in
src/conf/training/agent-router-agentic-commands.json. With no placeholder to
cross-multiply against, the agentic builder emits exactly one row per seed
line, so each command's row count was pinned to its file length regardless of
sample_size_per_command. Measured at BOTH cap 400 and cap 1500: test suite
stuck at 154, test-fix-expediter-resume stuck at 35, while its sibling
commands reached the cap. That put the corpus imbalance at 56.3x.

The fix wires TEST_TYPE -> test_types (a new getter) and PLAN_PATH ->
document_paths (already registered), and adds template lines carrying those
tokens. This regression pins it: both commands now reach the requested cap.
Empty either `placeholders` block and both assertions go red — that is the
control.
"""

import re
import unittest

from cosa.training.xml_coordinator import XmlCoordinator


SAMPLE_SIZE = 400

TFE_COMMAND = "agent router go to test fix expediter resume"

# The pre-fix ceilings, kept as literals so a shrinking seed file cannot
# quietly turn a regression into a pass.
OLD_CEILING = {
    "agent router go to test suite"                 : 154,
    "agent router go to test fix expediter resume"  :  35,
}


class TestAgenticPlaceholderYield( unittest.TestCase ):
    """The two thin agentic commands reach the cap, not their seed-line count."""

    @classmethod
    def setUpClass( cls ):
        # Real coordinator: the bug lives in config + placeholder dispatch, so
        # nothing may be mocked away.
        coordinator = XmlCoordinator( silent=True )
        cls.frame   = coordinator.build_agentic_job_training_prompts( sample_size_per_command=SAMPLE_SIZE )
        cls.counts  = cls.frame[ "command" ].value_counts().to_dict()

    def test_both_thin_commands_reach_the_cap( self ):
        for command in OLD_CEILING:
            with self.subTest( command=command ):
                self.assertEqual( self.counts.get( command, 0 ), SAMPLE_SIZE )

    def test_both_thin_commands_clear_their_old_seed_ceiling( self ):
        for command, ceiling in OLD_CEILING.items():
            with self.subTest( command=command ):
                self.assertGreater( self.counts.get( command, 0 ), ceiling )

    def test_the_placeholder_getters_resolve( self ):
        coordinator = XmlCoordinator( silent=True )
        self.assertGreater( len( coordinator._get_placeholder_values_by_name( "test_types" ) ), 0 )
        self.assertGreater( len( coordinator._get_placeholder_values_by_name( "tfe_plan_paths" ) ), 0 )

    def test_every_tfe_resume_arg_hits_an_implemented_resolver_branch( self ):
        """
        resume_resolver.resolve_resume_target implements exactly two branches —
        a tfe-* job ID and a plan doc path ("-plan.md" or "/plans/"). Its
        natural-language branch is a Phase 2 stub. PLAN_PATH first borrowed the
        document_paths list, 51 of whose 179 values are not paths at all
        ("my research on quantum computing"), so ~29% of generated resume
        targets trained the model to emit an argument the resolver cannot
        resolve. Point PLAN_PATH back at document_paths and this goes red.
        """
        args = []
        for output in self.frame[ self.frame[ "command" ] == TFE_COMMAND ][ "output" ]:
            match = re.search( r'resume_from="([^"]*)"', output )
            if match is not None and match.group( 1 ).strip(): args.append( match.group( 1 ) )

        self.assertGreater( len( args ), 0, "no resume_from arguments were emitted at all" )

        unresolvable = [ a for a in args if not ( a.startswith( "tfe-" ) or a.endswith( "-plan.md" ) or "/plans/" in a ) ]
        self.assertEqual( unresolvable, [], f"{len( unresolvable )} of {len( args )} resume targets hit the unimplemented fuzzy branch" )


if __name__ == "__main__":
    unittest.main()
