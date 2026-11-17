"""
A live gated confirmation must leave an organic proxy_decisions row.

The insert sits in SweTeamOrchestrator._gated_confirmation: once on the auto-approve return
and once after the trust feedback is saved.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator


def _run( coro ):
    return asyncio.new_event_loop().run_until_complete( coro )


def _orch_with_proxy( action, value="approved" ):
    o = SweTeamOrchestrator(
        task_description="Build X", config=SweTeamConfig( dry_run=True, trust_mode="disabled" ),
        job_id="swe-1"
    )
    o._ask_before_act = False
    proxy = MagicMock()
    proxy.trust_mode = "active"
    proxy.evaluate.return_value = MagicMock(
        action=action, value=value, category="testing", confidence=0.9, trust_level=3, reason="r"
    )
    o.proxy = proxy
    return o


def _team_io( answer=True ):
    t = MagicMock()
    t.ask_confirmation = AsyncMock( return_value=answer )
    t.notify_progress  = AsyncMock()
    return t


class TestOrganicProxyDecisionRow( unittest.TestCase ):

    def _run_with_repo( self, o, t ):
        repo = MagicMock()
        with patch( "cosa.rest.db.database.get_db" ) as get_db, \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository", return_value=repo ), \
             patch.object( o, "_persist_trust_feedback" ), \
             patch.object( o, "_emit_proxy_summary_notification" ), \
             patch.object( o, "_notify", AsyncMock() ):
            get_db.return_value.__enter__.return_value = MagicMock()
            _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, t ) )
        return repo

    def test_suggest_asked_row_is_organic_and_pending( self ):
        repo = self._run_with_repo( _orch_with_proxy( "suggest" ), _team_io( True ) )
        kwargs = repo.log_decision.call_args.kwargs
        self.assertEqual( kwargs[ "data_origin" ], "organic" )
        self.assertTrue( kwargs[ "requires_ratification" ] )
        self.assertEqual( kwargs[ "action" ], "suggest" )

    def test_shadow_row_uses_log_shadow( self ):
        repo = self._run_with_repo( _orch_with_proxy( "shadow", value=None ), _team_io( True ) )
        self.assertEqual( repo.log_shadow.call_args.kwargs[ "data_origin" ], "organic" )

    def test_auto_approved_act_row_needs_no_ratification( self ):
        repo = self._run_with_repo( _orch_with_proxy( "act" ), _team_io( True ) )
        kwargs = repo.log_decision.call_args.kwargs
        self.assertFalse( kwargs[ "requires_ratification" ] )
        self.assertIsNone( kwargs[ "metadata_json" ][ "user_answer" ] )


    def test_row_carries_sender_job_and_user_answer( self ):
        repo = self._run_with_repo( _orch_with_proxy( "suggest" ), _team_io( False ) )
        kwargs = repo.log_decision.call_args.kwargs
        self.assertEqual( kwargs[ "domain" ], "swe" )
        self.assertEqual( kwargs[ "category" ], "testing" )
        self.assertEqual( kwargs[ "decision_value" ], "approved" )
        self.assertEqual( kwargs[ "metadata_json" ], { "job_id": "swe-1", "user_answer": False } )

    def test_db_failure_is_swallowed_and_answer_still_returned( self ):
        o = _orch_with_proxy( "suggest" )
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "db down" ) ), \
             patch.object( o, "_persist_trust_feedback" ), \
             patch.object( o, "_emit_proxy_summary_notification" ):
            out = _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, _team_io( True ) ) )
        self.assertTrue( out )

    def test_db_failure_on_auto_approve_return_is_swallowed( self ):
        # The auto-approve return sits outside the gate's outer try, so only the method's own except saves it.
        o = _orch_with_proxy( "act" )
        team_io = _team_io( False )
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "db down" ) ), \
             patch.object( o, "_notify", AsyncMock() ):
            out = _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, team_io ) )
        self.assertTrue( out )
        team_io.ask_confirmation.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
