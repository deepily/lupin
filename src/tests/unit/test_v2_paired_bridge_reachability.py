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

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import eval_isolation_guard as guard                          # noqa: E402
from tests.integration import test_v2_paired_live as bridge   # noqa: E402


_V2_STORE = "lupin_db_test.solution_snapshots"           # SAFETY-blessed v2 destination (patched precondition 1)
_V1_STORE = "lupin_db_v1baseline.solution_snapshots"     # distinct v1 destination (patched _resolve_v1_paired_store)

_PAIRS = [ ( "u1", "c1" ), ( "u2", "c2" ), ( "u3", "c3" ) ]


def _canned_artifact( arm, *, spans, pairs=_PAIRS ):
    """A mocked arm {metrics, provenance} artifact — a REAL provenance stamp (so the paired
    provenance check runs for real, not a fake pass) over `pairs`, plus per-utterance client spans."""
    import paired_eval
    return {
        "metrics"    : { "n_ok": len( spans ), "spans_by_utterance": dict( spans ) },
        "provenance" : paired_eval.make_provenance( arm, "simple", 1024, 60, pairs ),
    }


# Matching-provenance artifacts (same pairs → same sample_signature); v1 slower than v2 so the
# median-Δ gate has a positive delta to render.
_V1_ART = _canned_artifact( "v1", spans={ "u1": 120.0, "u2": 130.0, "u3": 140.0 } )
_V2_ART = _canned_artifact( "v2", spans={ "u1":  40.0, "u2":  50.0, "u3":  60.0 } )


def test_bridge_reaches_and_fires_validity_check():
    """Preconditions 1+2 pass and both stores read empty -> the bridge MUST invoke
    require_arms_distinct_and_clean with the two resolved targets, then run past it."""
    spy = MagicMock( wraps=guard.require_arms_distinct_and_clean )   # records the call, delegates to the real check
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997" } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=_V2_ART ), \
         patch.object( guard, "require_arms_distinct_and_clean", spy ):
        # All preconditions satisfied and both arms mocked -> the bridge runs a–d to completion
        # and returns a verdict; reaching here at all proves the VALIDITY line was passed.
        bridge.test_v2_paired_go_no_go_live()

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
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", side_effect=refuse ), \
         patch.object( guard, "require_arms_distinct_and_clean", spy ):
        with pytest.raises( guard.IsolationNotConfigured ):
            bridge.test_v2_paired_go_no_go_live()

    spy.assert_not_called()


def test_bridge_refuses_a_leaky_corpus_at_precondition_0_before_safety():
    """Precondition 0 (CORPUS) runs BEFORE SAFETY: a corpus routing to an arg-extracting command
    refuses at the leak check, and SAFETY is never even consulted. This is what makes the guard
    a real precondition and not a note — it fires first, on the shipped default path."""
    safety_spy = MagicMock( return_value=_V2_STORE )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to deep research" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", safety_spy ):
        with pytest.raises( guard.PairedCorpusExercisesLeak ) as exc:
            bridge.test_v2_paired_go_no_go_live()
        assert "agent router go to deep research" in str( exc.value )

    safety_spy.assert_not_called()   # precondition 0 refused before SAFETY was reached


# ---------------------------------------------------------------------------
# Per-arm CLEAN-step wiring — clean_v2_snapshot_store is REACHED and FIRES (bug 080821da).
#
# WHY THIS EXISTS. clean_v2_snapshot_store had no caller outside its own unit tests — its own
# docstring flagged the orphan and named this the recurrence of row d8d019f6 (a check wired into
# nothing) inside the fix for it. The bridge now calls it via _clean_v2_arm_store, between
# precondition 2 and the VALIDITY clean-start check. These two tests prove the call happens on the
# REAL fn (not a stub) and is GATED behind the preconditions — with NO live TRUNCATE on :7999
# (the connection is injected, the real fn's execute lands on a MagicMock).
# ---------------------------------------------------------------------------
def test_bridge_reaches_and_fires_v2_clean_step():
    """Preconditions 0-2 pass -> the bridge MUST invoke the REAL v2_eval.clean_v2_snapshot_store
    with the v2 arm's connection + config, running its two guards through to the TRUNCATE. The
    connection is injected (fake), so the real fn's TRUNCATE lands on a MagicMock — no live DB."""
    import v2_eval

    fake_conn = MagicMock()
    fake_conn.engine.url = "postgresql://u:p@h/lupin_db_test"   # a measurement db -> assert_measurement_db passes
    cfg = MagicMock()
    cfg.get.return_value = "solution_snapshots"                 # == ORM __tablename__ -> config cross-check passes
    spy = MagicMock( wraps=v2_eval.clean_v2_snapshot_store )    # the REAL fn, delegated to (not a stub)

    with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_open_v2_arm_connection", return_value=fake_conn ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997" } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=_V2_ART ), \
         patch.object( v2_eval, "clean_v2_snapshot_store", spy ):
        # Preconditions satisfied and both arms mocked -> the bridge runs a–d to completion; the
        # clean-step fired on the way past, which is what this test proves.
        bridge.test_v2_paired_go_no_go_live()

    # The clean-step fired exactly once, on the injected connection + config.
    spy.assert_called_once_with( fake_conn, cfg )
    # The REAL fn ran through BOTH guards to the TRUNCATE on the injected connection (no live DB) —
    # proving it is the real primitive, not a mock that always passes.
    fake_conn.execute.assert_called_once()
    # The TRUNCATE must be a SQLAlchemy *executable* (a `text()` clause), NOT a bare str — a raw
    # string passes a MagicMock silently but SQLAlchemy 2.x rejects it with AttributeError on the
    # live :8000 run (bug: 'str' object has no attribute '_execute_on_connection'). Asserting the
    # arg type here is the control that goes RED on the pre-fix raw-string code.
    ( truncate_stmt, ), _kwargs = fake_conn.execute.call_args
    from sqlalchemy.sql.elements import TextClause
    assert isinstance( truncate_stmt, TextClause ), f"TRUNCATE must be a text() clause, got {type( truncate_stmt )}"
    assert str( truncate_stmt ) == "TRUNCATE TABLE solution_snapshots"
    # The TRUNCATE must be COMMITTED — SQLAlchemy 2.x is commit-as-you-go, so without an explicit
    # commit the truncate rolls back on close and the live store stays dirty (the VALIDITY guard
    # then refuses the run). A MagicMock swallows the omission; asserting commit here is the control
    # that goes RED on the pre-fix no-commit code.
    fake_conn.commit.assert_called_once()
    fake_conn.close.assert_called_once()


def test_bridge_never_reaches_v2_clean_when_safety_refuses():
    """Negative control: precondition 1 (SAFETY) refuses -> the v2 clean-step is NEVER called (no
    TRUNCATE). Proves the positive test above is gated behind the preconditions, not free-standing."""
    import v2_eval

    spy = MagicMock( wraps=v2_eval.clean_v2_snapshot_store )
    refuse = guard.IsolationNotConfigured( "SAFETY refuses (simulated precondition 1)" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", side_effect=refuse ), \
         patch.object( v2_eval, "clean_v2_snapshot_store", spy ):
        with pytest.raises( guard.IsolationNotConfigured ):
            bridge.test_v2_paired_go_no_go_live()

    spy.assert_not_called()


# ---------------------------------------------------------------------------
# a-d ARM-RUNNING wiring — the PROVENANCE-GATED paired verdict is REACHED and FIRES (row d8d019f6).
#
# WHY THIS EXISTS. build_paired_verdict (provenance-check -> median-delta gate) was wired into
# nothing: the bridge ended at a pytest.fail("unreachable") stub, so two arms that measured
# DIFFERENT samples would never have met a real caller. The bridge now runs both arms (injected,
# mocked here -> no live push/inference on :7999) and hands their artifacts to build_paired_verdict.
# These tests prove the verdict step is REACHED and that the provenance check genuinely GATES
# (binds the arms by sample signature), not a shape-only pass.
# ---------------------------------------------------------------------------
def test_bridge_runs_both_arms_and_builds_provenance_gated_verdict():
    """Preconditions pass, both arms mocked with MATCHING provenance -> the bridge MUST call the
    REAL build_paired_verdict with the two artifacts and complete with provenance_ok True. Reverting
    the a-d wiring to the stub makes this RED (the real verdict is never built)."""
    import paired_eval
    spy = MagicMock( wraps=paired_eval.build_paired_verdict )   # the REAL fn, delegated to
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997" } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=_V2_ART ), \
         patch.object( paired_eval, "build_paired_verdict", spy ):
        verdict = bridge.test_v2_paired_go_no_go_live()

    spy.assert_called_once_with( _V1_ART, _V2_ART )   # the caller the verdict lacked
    assert verdict[ "provenance_ok" ] is True         # provenance-bound, not a shape-only pass


def test_bridge_refuses_when_arms_measured_different_samples():
    """Provenance BINDING control: if the two arms measured DIFFERENT samples, build_paired_verdict
    returns provenance_ok=False and the bridge REFUSES with an AssertionError naming the un-bound
    arms — proving the gate is provenance-checked, not shape-only. A weakening that skipped the
    provenance check would let this pass -> RED."""
    v2_mismatch = _canned_artifact( "v2", spans={ "x1": 40.0, "x2": 50.0 },
                                    pairs=[ ( "x1", "c1" ), ( "x2", "c2" ) ] )   # different pairs -> different signature
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997" } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=v2_mismatch ):
        with pytest.raises( AssertionError ) as exc:
            bridge.test_v2_paired_go_no_go_live()
        assert "provenance" in str( exc.value ).lower()
