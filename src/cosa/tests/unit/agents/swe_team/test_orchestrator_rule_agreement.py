"""
The orchestrator keeps success and rule agreement apart.

The row it persists carries its own rule_agreement, which is NULL for a shadow row.
One test pins the open conflict: a human approval of a deployment scores as a rejection today.
Only the human and the database are faked.
"""
import asyncio
import contextlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.swe_team.proxy import EngineeringStrategy


def _orch( trust_mode="disabled" ):
    return SweTeamOrchestrator( task_description="Build X", config=SweTeamConfig( dry_run=True, trust_mode=trust_mode ), job_id="swe-1" )


def _team_io( confirm ):
    team_io = MagicMock()
    team_io.ask_confirmation = AsyncMock( return_value=confirm )
    return team_io


def _result( action, value ):
    return MagicMock( action=action, value=value, category="deployment", confidence=0.8, trust_level=1, reason="r" )


@contextlib.contextmanager
def _database():
    """Fake the session and the repository, and yield the repository."""
    repo = MagicMock()
    with patch( "cosa.rest.db.database.get_db" ) as get_db, \
         patch( "cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository", return_value=repo ):
        get_db.return_value.__enter__.return_value = MagicMock()
        yield repo


class TestSuccessAndRuleAgreementStayApart( unittest.TestCase ):

    # Measured 20 Nov 2026: the strategy forecasts "requires_review" for a deployment, so a human approval scores as a
    # rejection today. The plan's acceptance says it must compute as success, but changing the scoring changes what the
    # trust gate does, which decision 5 rules out. It is Rick's call (Mr. Radio, 20 Nov 2026). When Rick rules and the
    # scoring changes, this test starts passing, the expected failure breaks the suite, and the decorator comes off.
    @unittest.expectedFailure
    def test_a_human_approving_a_deployment_scores_as_success_through_the_real_strategy_and_tracker( self ):
        o       = _orch()
        tracker = TrustTracker()
        o.proxy = EngineeringStrategy( trust_tracker=tracker, trust_mode="shadow" )
        with patch.object( o, "_persist_trust_feedback" ), patch.object( o, "_persist_proxy_decision" ):
            approved = asyncio.run( o._gated_confirmation( "should we deploy the build to production?", "lead", "no", 60, None, _team_io( True ) ) )
        self.assertTrue( approved )
        recorded = [ c for c in tracker.get_stats().values() if c[ "total_decisions" ] ]
        self.assertEqual( len( recorded ), 1, recorded )
        self.assertEqual( ( recorded[ 0 ][ "total_successes" ], recorded[ 0 ][ "total_rejections" ] ), ( 1, 0 ), recorded[ 0 ] )

    def test_the_persisted_shadow_row_carries_no_rule_agreement_though_the_human_approved( self ):
        with _database() as repo:
            _orch()._persist_proxy_decision( "lead", "deploy?", _result( "shadow", "approved" ), True )
        repo.log_shadow.assert_called_once()
        self.assertIsNone( repo.log_shadow.call_args.kwargs[ "rule_agreement" ] )
        repo.log_decision.assert_not_called()

    def test_an_act_row_the_human_approved_is_rule_agreement_true_and_one_they_declined_is_false( self ):
        for answer, expected in ( ( True, True ), ( False, False ) ):
            with _database() as repo:
                _orch()._persist_proxy_decision( "lead", "deploy?", _result( "act", "approved" ), answer )
            self.assertIs( repo.log_decision.call_args.kwargs[ "rule_agreement" ], expected, answer )

    def test_an_auto_approved_act_row_nobody_answered_has_no_rule_agreement( self ):
        with _database() as repo:
            _orch()._persist_proxy_decision( "lead", "deploy?", _result( "act", "approved" ), None )
        self.assertIsNone( repo.log_decision.call_args.kwargs[ "rule_agreement" ] )

    def test_a_suggest_row_waits_for_ratification_and_still_records_its_rule_agreement( self ):
        with _database() as repo:
            _orch()._persist_proxy_decision( "lead", "deploy?", _result( "suggest", "approved" ), True )
        kwargs = repo.log_decision.call_args.kwargs
        self.assertTrue( kwargs[ "requires_ratification" ] )
        self.assertIs( kwargs[ "rule_agreement" ], True )


if __name__ == "__main__":
    unittest.main()
