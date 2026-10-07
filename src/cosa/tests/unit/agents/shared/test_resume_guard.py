"""
Unit tests for cosa.agents.shared.resume_guard.

One guard decides whether a resumed run has already got past a phase. TFE and BFE both ask it,
so the two agents cannot drift into two readings of the same checkpoint ordinal.
"""

import unittest

from cosa.agents.shared.resume_guard import resume_covers
from cosa.agents.bug_fix_expediter.state import BFEPhase, BFE_PHASE_ORDINALS
from cosa.agents.test_fix_expediter.state import TFEPhase, TFE_PHASE_ORDINALS
import cosa.agents.bug_fix_expediter.orchestrator as bfe_orch
import cosa.agents.test_fix_expediter.orchestrator as tfe_orch


class TestResumeCovers( unittest.TestCase ):

    def test_no_resume_covers_nothing( self ):
        self.assertFalse( resume_covers( None, BFE_PHASE_ORDINALS, BFEPhase.PACKAGING ) )

    def test_ordinal_below_the_phase_does_not_cover_it( self ):
        self.assertFalse( resume_covers( 0, BFE_PHASE_ORDINALS, BFEPhase.DIAGNOSING ) )

    def test_ordinal_equal_to_the_phase_covers_it( self ):
        self.assertTrue( resume_covers( 1, BFE_PHASE_ORDINALS, BFEPhase.DIAGNOSING ) )

    def test_ordinal_above_the_phase_covers_it( self ):
        self.assertTrue( resume_covers( 2, BFE_PHASE_ORDINALS, BFEPhase.DIAGNOSING ) )

    def test_the_unusable_minus_one_ordinal_covers_nothing( self ):
        # A checkpoint taken while a gate waited used to record -1.
        for phase in BFEPhase:
            if phase in BFE_PHASE_ORDINALS:
                self.assertFalse( resume_covers( -1, BFE_PHASE_ORDINALS, phase ), phase )

    def test_works_with_the_tfe_table_too( self ):
        self.assertTrue( resume_covers( 3, TFE_PHASE_ORDINALS, TFEPhase.PROPOSING ) )
        self.assertFalse( resume_covers( 2, TFE_PHASE_ORDINALS, TFEPhase.PROPOSING ) )

    def test_both_orchestrators_use_this_one_function( self ):
        self.assertIs( bfe_orch.resume_covers, resume_covers )
        self.assertIs( tfe_orch.resume_covers, resume_covers )


if __name__ == "__main__":
    unittest.main()
