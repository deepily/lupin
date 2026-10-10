"""
The measurement driver builds each arm's context with the arm's own budget.

Stage one hands the budget to the sweep and to the transport, so the context's `run_budget` was never read.
It is pinned here so an ask that goes through the context and not the sweeper draws on the arm's ceiling.
Every transport is a stand-in. Nothing reaches Jev.
"""
import pytest

from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as st
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_stage1_driver import ENTRIES, LIMIT, NEED, Standin


@pytest.fixture
def made( tmp_path, monkeypatch ):
    """Ensures: ( env, contexts ), every ReuseContext the driver builds in order."""
    contexts = []

    class Recording( rt.ReuseContext ):
        def __init__( self, *args, **kw ):
            super().__init__( *args, **kw )
            contexts.append( self )

    monkeypatch.setattr( st.rt, "ReuseContext", Recording )
    ledger = rl.AccountLedger.create( tmp_path / "ledger.jsonl", LIMIT, "test", "scratch" )
    stands = []

    def factory( budget, **kw ):
        stands.append( Standin( budget, **kw ) )
        return stands[ -1 ]

    env = st.Stage1Env( root=tmp_path, data=tmp_path / "data", ledger=ledger, transport_factory=factory, entries_in_index=len( ENTRIES ) )
    env.stands = stands
    return env, contexts


def test_the_arms_context_carries_the_budget_the_arm_runs_on( made ):
    env, contexts = made
    out = st.run_arm( env, 1, "single1", NEED, ENTRIES[ :3 ], 1_000_000 )
    assert len( contexts ) == 1
    budget = contexts[ 0 ].run_budget
    assert isinstance( budget, rc.TokenBudget ) and budget is env.stands[ 0 ].budget       # the transport's budget, one object
    assert budget.spent_tokens == out[ "totals" ][ "spent_tokens" ] > 0                    # the sweep drew on it
