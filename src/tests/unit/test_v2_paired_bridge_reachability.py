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

import json
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

# Where this file's canned artifacts are allowed to land. The bridge's dump runs BEFORE the
# provenance assertion (deliberately — a downstream error must not destroy recoverable data),
# so every test below that reaches the bridge WOULD otherwise write io/v2-flow/paired-run-latest,
# the directory people read as results. On 2026-08-17 it did exactly that, leaving a fake
# v1 n=3 / v2 n=2 pair a session nearly mistook for a real run.
import tempfile                                            # noqa: E402
_ARTIFACT_TMPDIR = tempfile.mkdtemp( prefix="paired-artifacts-unit-" )

_PAIRS = [ ( "u1", "c1" ), ( "u2", "c2" ), ( "u3", "c3" ) ]


def _canned_artifact( arm, *, spans, pairs=_PAIRS ):
    """A mocked arm {metrics, provenance} artifact — a REAL provenance stamp (so the paired
    provenance check runs for real, not a fake pass) over `pairs`, plus per-utterance client spans."""
    import paired_eval
    # KEY ASYMMETRY (row d8d019f6): the REAL metrics dicts name the usable-record count differently
    # per arm — v1 compute_v1_metrics -> "ok_n", v2 compute_metrics -> "n_ok". The canned artifact
    # MUST mirror that, else it masks the very KeyError the live run hit (the old canned used "n_ok"
    # for both arms, so the bridge's wrong v1 key passed in unit but KeyError'd live).
    count_key = "ok_n" if arm == "v1" else "n_ok"
    return {
        "metrics"    : { count_key: len( spans ), "spans_by_utterance": dict( spans ) },
        # Each arm records the tree it measured (row c9b43538); the two differ by design.
        "provenance" : paired_eval.make_provenance( arm, "simple", 1024, 60, pairs,
                                                    git_sha="b0735467" if arm == "v1" else "f7c5e349" ),
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
         patch.object( bridge, "_require_model_servers_live", lambda cfg: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   # NEVER let a unit test publish to the live results dir:
                                   # the artifact dump runs BEFORE the provenance assertion,
                                   # so canned fixtures reached paired-run-latest and a
                                   # session nearly read them as a real run (2026-08-17).
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
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
         patch.object( bridge, "_require_model_servers_live", lambda cfg: None ), \
         patch.object( bridge, "_open_v2_arm_connection", return_value=fake_conn ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   # NEVER let a unit test publish to the live results dir:
                                   # the artifact dump runs BEFORE the provenance assertion,
                                   # so canned fixtures reached paired-run-latest and a
                                   # session nearly read them as a real run (2026-08-17).
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
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
# The V1 half of the per-arm clean-step (row 3bfd3fbc, Rio's finding).
#
# WHY THIS EXISTS. The v2 clean above ran BEFORE the VALIDITY check; the v1 arm had no clean on the
# path at all — v1_eval_arm.truncate_snapshots was unit-proven with nothing calling it, the orphan
# shape of bug 080821da. So an aborted run left v1 residue that VALIDITY refused the NEXT run on,
# and only a human with destructive-SQL permission could clear it: on 2026-08-17 that was 66 rows,
# three seats, an evening, and no run. These three tests prove the v1 clean is REACHED, that it
# fires BEFORE the check that would otherwise refuse on the residue, and that it is still gated
# behind the preconditions rather than free-standing.
# ---------------------------------------------------------------------------
def test_bridge_reaches_and_fires_the_v1_clean_step():
    """Preconditions 0-2 pass -> the bridge MUST invoke the REAL v1_eval_arm.truncate_snapshots on a
    connection to the v1 arm's OWN measurement db, running assert_test_db through to the TRUNCATE.
    The connection is injected, so the real fn's TRUNCATE lands on a MagicMock — no live DB."""
    import v1_eval_arm

    fake_conn               = MagicMock()
    fake_conn.engine.url    = "postgresql://u:p@h/lupin_db_v1baseline"   # the v1 measurement db
    cfg                     = MagicMock()
    cfg.get.return_value    = "solution_snapshots"
    spy                     = MagicMock( wraps=v1_eval_arm.truncate_snapshots )   # the REAL fn

    with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_require_model_servers_live", lambda cfg: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_open_v1_arm_connection", return_value=fake_conn ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=_V2_ART ), \
         patch.object( v1_eval_arm, "truncate_snapshots", spy ):
        bridge.test_v2_paired_go_no_go_live()

    spy.assert_called_once_with( fake_conn )
    # The REAL primitive ran through assert_test_db to the TRUNCATE on the injected connection.
    fake_conn.execute.assert_called_once()
    ( truncate_stmt, ), _kwargs = fake_conn.execute.call_args
    from sqlalchemy.sql.elements import TextClause
    assert isinstance( truncate_stmt, TextClause ), f"TRUNCATE must be a text() clause, got {type( truncate_stmt )}"
    assert str( truncate_stmt ) == "TRUNCATE TABLE solution_snapshots"
    # Commit-as-you-go: without this the TRUNCATE rolls back on close and the store stays dirty —
    # which is the whole failure this row is about, so it is asserted rather than assumed.
    fake_conn.commit.assert_called_once()
    fake_conn.close.assert_called_once()


def test_the_v1_clean_fires_before_the_check_that_would_refuse_on_residue():
    """ORDERING IS THE FIX. A v1 clean placed after the VALIDITY check would be unreachable on
    exactly the runs that need it — the check refuses on the residue first, which is what happened
    on 2026-08-17. This pins the order: when assert_paired_isolation is entered, the v1 clean has
    already fired. Moving the clean below the check makes this RED."""
    import v1_eval_arm

    order     = []
    fake_conn = MagicMock()
    fake_conn.engine.url = "postgresql://u:p@h/lupin_db_v1baseline"
    cfg       = MagicMock()
    cfg.get.return_value = "solution_snapshots"

    def _record_clean( connection ):
        order.append( "v1_clean" )
        return "solution_snapshots"

    def _record_validity( v1_store, v2_store, rowcount_fn=None ):
        order.append( "validity" )

    with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_require_model_servers_live", lambda cfg: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_open_v1_arm_connection", return_value=fake_conn ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "assert_paired_isolation", _record_validity ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=_V2_ART ), \
         patch.object( v1_eval_arm, "truncate_snapshots", _record_clean ):
        bridge.test_v2_paired_go_no_go_live()

    assert order == [ "v1_clean", "validity" ], f"the v1 clean must precede the VALIDITY check; got {order}"


def test_bridge_never_reaches_the_v1_clean_when_safety_refuses():
    """Negative control: precondition 1 (SAFETY) refuses -> no v1 TRUNCATE. The clean is a step
    inside the gated path, not something that fires on the way to a refusal."""
    import v1_eval_arm

    spy    = MagicMock( wraps=v1_eval_arm.truncate_snapshots )
    refuse = guard.IsolationNotConfigured( "SAFETY refuses (simulated precondition 1)" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", MagicMock() ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", side_effect=refuse ), \
         patch.object( v1_eval_arm, "truncate_snapshots", spy ):
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
         patch.object( bridge, "_require_model_servers_live", lambda cfg: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   # NEVER let a unit test publish to the live results dir:
                                   # the artifact dump runs BEFORE the provenance assertion,
                                   # so canned fixtures reached paired-run-latest and a
                                   # session nearly read them as a real run (2026-08-17).
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
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
         patch.object( bridge, "_require_model_servers_live", lambda cfg: None ), \
         patch.object( bridge, "_clean_v2_arm_store", lambda config_mgr: "solution_snapshots" ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   # NEVER let a unit test publish to the live results dir:
                                   # the artifact dump runs BEFORE the provenance assertion,
                                   # so canned fixtures reached paired-run-latest and a
                                   # session nearly read them as a real run (2026-08-17).
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=v2_mismatch ):
        with pytest.raises( AssertionError ) as exc:
            bridge.test_v2_paired_go_no_go_live()
        assert "provenance" in str( exc.value ).lower()


# ---------------------------------------------------------------------------
# Cold-start guard OFF on both arms — RULED by Tiberius 2026-08-17 (row d8d019f6).
# F3 demands cache_hit_rate==0, but the snapshot manager's SIMILARITY cache self-warms
# within the cold pass (deterministic 0.0126 over 300 UNIQUE utterances, identical across
# a full :7997 restart). The Δ is warm-vs-warm and never reads the cold pass; stores are
# isolated (no cross-arm warming); VALIDITY still guards clean-start. Both arms skip the
# guard SYMMETRICALLY. These assert the flags are actually threaded — RED if dropped.
# ---------------------------------------------------------------------------
def test_v1_arm_threads_assert_cold_false():
    import v1_eval_arm
    listener = MagicMock()
    spy = MagicMock( return_value={ "warm": {}, "provenance": {} } )
    with patch.dict( os.environ, { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "t@e.com" } ), \
         patch.object( v1_eval_arm, "load_v1_class_to_command", return_value=( {}, [] ) ), \
         patch.object( v1_eval_arm, "make_ws_recv_events", return_value=( listener, MagicMock() ) ), \
         patch.object( v1_eval_arm, "_default_push_fn", return_value=MagicMock() ), \
         patch.object( v1_eval_arm, "_default_collect_fn", return_value=MagicMock() ), \
         patch.object( v1_eval_arm, "run_v1_baseline", spy ):
        bridge._run_v1_arm( corpus="simple", seed=1024, n_per_command=60, base_url="http://stub:7997" )
    _args, kwargs = spy.call_args
    assert kwargs.get( "assert_cold" ) is False   # RED if dropped -> defaults True -> F3 re-arms
    listener.stop.assert_called_once()


def test_v2_arm_passes_allow_warm_cold():
    import v2_eval
    spy = MagicMock( return_value={ "warm": {}, "provenance": {} } )
    with patch.object( v2_eval, "main", spy ):
        bridge._run_v2_arm( corpus="simple", seed=1024, n_per_command=60, base_url="http://stub:8000" )
    _args, kwargs = spy.call_args
    argv = kwargs.get( "argv" ) if kwargs.get( "argv" ) is not None else ( _args[ 0 ] if _args else [] )
    assert "--allow-warm-cold" in argv            # RED if dropped -> v2 cold-start guard re-arms


# ---------------------------------------------------------------------------
# The publish-containment control (2026-08-17). A unit test must never be able to write
# io/v2-flow/paired-run-latest — that directory is read as RESULTS.
# ---------------------------------------------------------------------------
def test_unit_fixtures_cannot_publish_to_the_live_results_dir():
    """RED if the artifact dump stops honoring LUPIN_PAIRED_ARTIFACT_DIR.

    This file's canned artifacts DID reach io/v2-flow/paired-run-latest, because the dump runs
    before the provenance assertion and therefore fires for any caller that gets that far. The
    result was a fake v1 n=3 / v2 n=2 pair sitting where a real median-Δ belongs. Redirecting the
    dump is the containment; this asserts the redirect actually holds, and that the live path is
    what gets used when nobody redirects.
    """
    import cosa.utils.util as cu
    live = os.path.join( cu.get_project_root(), "io", "v2-flow", "paired-run-latest" )
    with tempfile.TemporaryDirectory() as sandbox:
        with patch.dict( os.environ, { "LUPIN_PAIRED_ARTIFACT_DIR": sandbox } ):
            bridge._dump_paired_artifacts( _V1_ART, _V2_ART )
        assert sorted( os.listdir( sandbox ) ) == [ "v1-arm-artifact.json", "v2-arm-artifact.json" ]
        written = json.load( open( os.path.join( sandbox, "v1-arm-artifact.json" ) ) )
        # The stamp is the backstop for when someone forgets to redirect: a reader can tell a
        # real run's artifact from a test's by who wrote it.
        assert "written_at" in written and written[ "written_by" ] == "unknown-caller"
    assert sandbox != live


def test_artifact_dump_defaults_to_the_live_dir_when_unredirected():
    """The other half: without the env var the dump still targets the real results directory,
    so the containment above is a REDIRECT and not an accidental disabling of the insurance."""
    import cosa.utils.util as cu
    live = os.path.join( cu.get_project_root(), "io", "v2-flow", "paired-run-latest" )
    seen = {}
    real_makedirs = os.makedirs
    def spy_makedirs( path, **kw ):
        seen[ "path" ] = path
        raise RuntimeError( "stop before writing — we only need the resolved target" )
    with patch.dict( os.environ, {}, clear=False ):
        os.environ.pop( "LUPIN_PAIRED_ARTIFACT_DIR", None )
        with patch.object( os, "makedirs", spy_makedirs ):
            bridge._dump_paired_artifacts( _V1_ART, _V2_ART )   # best-effort: swallows the raise
    assert seen[ "path" ] == live


# ---------------------------------------------------------------------------
# Precondition 2b — the model-server DEPENDENCY guard is REACHED and GATES the run
# (row b9604f8c). The other tests in this file neutralise it, exactly as they neutralise
# every other precondition; these two are the pair that prove it is really there.
# ---------------------------------------------------------------------------
def test_bridge_refuses_when_a_model_server_port_is_dead():
    """
    THE FIRING ARM. A dead endpoint must stop the paired run BEFORE either arm measures
    anything — the whole point is that the refusal costs seconds rather than three hours.
    `_run_v1_arm` is the control: if it ran, the guard fired too late to save the run.
    """
    import v2_eval
    from cosa.utils.model_server_liveness import ModelServerUnavailable

    cfg      = MagicMock()
    cfg.get.return_value = "solution_snapshots"
    v1_spy   = MagicMock( return_value=_V1_ART )
    refusal  = ModelServerUnavailable( "192.168.1.21:3000 did not answer" )

    with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_require_model_servers_live", MagicMock( side_effect=refusal ) ), \
         patch.object( bridge, "_run_v1_arm", v1_spy ):
        with pytest.raises( ModelServerUnavailable, match="3000" ):
            bridge.test_v2_paired_go_no_go_live()

    v1_spy.assert_not_called()


def test_bridge_reaches_the_model_server_guard_with_the_run_s_own_config():
    """
    The guard must be handed the SAME config object the run resolved its stores from —
    probing a different configuration would answer a question nobody asked.
    """
    import v2_eval

    fake_conn = MagicMock()
    fake_conn.engine.url = "postgresql://u:p@h/lupin_db_test"
    cfg = MagicMock()
    cfg.get.return_value = "solution_snapshots"
    probe_spy = MagicMock( return_value=[] )

    with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg ), \
         patch( "v2_eval.load_corpus", return_value=[ ( "u", "agent router go to todo" ) ] ), \
         patch.object( guard, "require_isolated_snapshot_table", return_value=_V2_STORE ), \
         patch.object( bridge, "_require_v1_live_seam_and_worktree", lambda: None ), \
         patch.object( bridge, "_require_model_servers_live", probe_spy ), \
         patch.object( bridge, "_open_v2_arm_connection", return_value=fake_conn ), \
         patch.object( bridge, "_resolve_v1_paired_store", return_value=_V1_STORE ), \
         patch.object( guard, "count_store_rows", return_value=0 ), \
         patch.dict( os.environ, { "LUPIN_V1_ARM_BASE_URL": "http://stub-v1:7997",
                                   "LUPIN_PAIRED_ARTIFACT_DIR": _ARTIFACT_TMPDIR } ), \
         patch.object( bridge, "_run_v1_arm", return_value=_V1_ART ), \
         patch.object( bridge, "_run_v2_arm", return_value=_V2_ART ):
        bridge.test_v2_paired_go_no_go_live()

    probe_spy.assert_called_once_with( cfg )
