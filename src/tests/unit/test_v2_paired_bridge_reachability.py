"""Unit test: the paired bridge's VALIDITY call is REACHED and FIRES (not dead code).

VENUE: :7999 — pure, all live boundaries patched, no server, no DB.

WHY THIS EXISTS. `require_arms_distinct_and_clean` (the VALIDITY check) had no caller
outside its own unit tests — the exact shape of row d8d019f6 (a check wired into nothing)
recurring inside the fix for it. The bridge test_v2_paired_live.py now calls it at
precondition 3, but that call sits BEHIND preconditions 1 (SAFETY) and 2 (v1 seam), both
of which refuse on today's shared checkout. A caller that can never be reached is the same
as no caller. Rachel's ruling: the paired run must not proceed until the VALIDITY check has
a real caller AND a test proves the call happens. These two tests are that proof.

  · test_bridge_reaches_and_fires_validity_check — patches preconditions 1+2 to PASS and the
    live rowcount to 0/0, then asserts the bridge actually invokes require_arms_distinct_and_clean
    with the two resolved arm targets and reaches past it (control-flow proof).
  · test_bridge_never_reaches_validity_when_safety_refuses — the negative control: with
    precondition 1 refusing (today's shipped state), the VALIDITY check is NEVER called. This
    is what makes the positive test non-tautological — it proves the call is gated, not free.
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from _pytest.outcomes import Failed

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import eval_isolation_guard as guard                          # noqa: E402
from tests.integration import test_v2_paired_live as bridge   # noqa: E402


_V2_STORE = "lupin_db_test.solution_snapshots"           # SAFETY-blessed v2 destination (patched precondition 1)
_V1_STORE = "lupin_db_v1baseline.solution_snapshots"     # distinct v1 destination (patched _resolve_v1_paired_store)


def test_bridge_reaches_and_fires_validity_check():
    """Preconditions 1+2 pass and both stores read empty -> the bridge MUST invoke
    require_arms_distinct_and_clean with the two resolved targets, then run past it."""
    spy = MagicMock( wraps=guard.require_arms_distinct_and_clean )   # records the call, delegates to the real check
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.object( guard, "require_arms_distinct_and_clean", spy ):
        # All preconditions satisfied, so control reaches the terminal "unreachable" guard —
        # that raise IS the proof the VALIDITY line was passed, not skipped.
        with pytest.raises( Failed ) as exc:
            bridge.test_v2_paired_go_no_go_live()
        assert "unreachable" in str( exc.value )

    # The VALIDITY check fired exactly once, on the two REAL resolved arm targets, with the
    # live-queried (here patched-to-0) clean-start counts. This is the caller it lacked.
    spy.assert_called_once_with(
        _V1_STORE, _V2_STORE, v1_rowcount=0, v2_rowcount=0,
    )


def test_bridge_never_reaches_validity_when_safety_refuses():
    """Negative control: precondition 1 (SAFETY) refuses -> the VALIDITY check is never called.
    Proves the positive test above is gated behind the preconditions, not a free-standing pass."""
    spy = MagicMock( wraps=guard.require_arms_distinct_and_clean )
    refuse = guard.IsolationNotConfigured( "SAFETY refuses (simulated precondition 1)" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch.object( guard, "require_isolated_snapshot_table", side_effect=refuse ), \
         patch.object( guard, "require_arms_distinct_and_clean", spy ):
        with pytest.raises( guard.IsolationNotConfigured ):
            bridge.test_v2_paired_go_no_go_live()

    spy.assert_not_called()
