"""
The shipped tutor prompt must keep telling the model to keep the subject.

Row `20026f56` Part D. Three `Requirement:` lines were added to
`/src/conf/prompts/agents/dm-tutor.txt` on 2026-08-26, and they are not a style
preference — they are the surviving half of a measured A/B against the live model:

    220 real DM bodies, paired, both arms scored by the same frozen detector
    arm A (the prompt without these lines)  subject lost 110/220 = 50.0%
    arm B (the prompt with them)            subject lost  85/220 = 38.6%
    discordant 48 fixed / 23 broken, McNemar exact two-sided p = 0.004

Write-up: `src/rnd/v0.2.0/2026.08.26-dm-condenser-drops-sentence-subjects.md` §3.1.

🔴 WHY A TEST AND NOT JUST A COMMENT IN THE PROMPT. A prompt file is prose in a config
directory. Anybody tidying it can drop a line without a single test going red, and the
cost of that would not show up as a failure — it would show up as an eleven-point rise
in DMs whose reader cannot tell who did what, weeks later, with nothing pointing back
here. This is the only thing standing between that measurement and a quiet revert.

⚠️ IT PINS THE INSTRUCTIONS, NOT THE WORDING. Each check below looks for the operative
phrase, so the prose around it can be improved. What cannot happen silently is a whole
rule going missing. If you deliberately change one, re-run the A/B — the p-value quoted
above belongs to the lines as measured, not to whatever replaces them.
"""
import os
import unittest

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager


def _prompt_text():
    """
    The prompt as the agent reads it — via the INI key, not a hardcoded path.

    Reading the literal path would keep this test green on the day somebody points the
    tutor at a different file, which is exactly the day it should go red.
    """
    cm       = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    relative = cm.get( "prompt template for dm tutor rewrite" )
    path     = cu.get_project_root() + relative
    with open( path, encoding="utf-8" ) as handle:
        return handle.read()


class TestTheKeepTheSubjectRulesAreStillShipped( unittest.TestCase ):

    def setUp( self ):
        self.prompt = _prompt_text()

    def test_the_prompt_file_the_ini_names_exists( self ):
        """A missing prompt is a broken tutor, and the other checks would be vacuous."""
        cm       = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        relative = cm.get( "prompt template for dm tutor rewrite" )
        self.assertTrue( os.path.isfile( cu.get_project_root() + relative ),
                         f"the tutor prompt named by the INI is not on disk: {relative}" )

    def test_it_still_orders_the_model_to_keep_the_subject( self ):
        """Rule 1 of 3 — the one the 11-point cut is mostly made of."""
        self.assertIn( "keep the SUBJECT of every claim", self.prompt,
                       "the keep-the-subject rule left the prompt — subject loss measured "
                       "at 50.0% without it against 38.6% with it, p = 0.004" )

    def test_it_still_forbids_swapping_a_person_for_a_role_noun( self ):
        """
        Rule 2 of 3. This is the one aimed at the reported harm: "the developer has
        completed a review" in place of the name the sender wrote is what put Cheech one
        step from calling a scope violation on the wrong person, 2026-08-13.
        """
        self.assertIn( "MUST NOT replace a person with a role noun", self.prompt )
        for role_noun in ( "the sender", "the author", "the reviewer" ):
            with self.subTest( role_noun=role_noun ):
                self.assertIn( f'"{role_noun}"', self.prompt,
                               "the banned-role-noun list lost an entry" )

    def test_it_still_forbids_turning_a_report_into_an_order( self ):
        """
        Rule 3 of 3, and the least obvious. A condensed DM that turns "I re-ran it" into
        "re-run it" has not lost information, it has invented an instruction — which is
        why it sits with the subject rules rather than with the fabrication guard.
        """
        self.assertIn( "MUST NOT turn a statement into an order", self.prompt )

    def test_the_rules_are_read_before_the_think_out_loud_instruction( self ):
        """
        Position, not just presence. The A/B inserted them immediately above
        "MOST IMPORTANT:", and a Requirement pushed below that line is being read after
        the model has been told to start reasoning. Cheap to pin, and the measurement
        only ever covered this placement.
        """
        rule   = self.prompt.index( "keep the SUBJECT of every claim" )
        anchor = self.prompt.index( "MOST IMPORTANT:" )
        self.assertLess( rule, anchor,
                         "the keep-the-subject rules moved below MOST IMPORTANT: — that "
                         "is not the arrangement the A/B measured" )


if __name__ == "__main__":
    unittest.main()
